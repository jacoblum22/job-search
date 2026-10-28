"""Move the main database from jobs.db to Postgres, back it up, and move it back
(Azure plan, phase 4; docs/postgres-mirror.md).

`cutover` copies jobs.db into Postgres with the app's own schema (identity ids, defaults,
indexes; the mirror's tables are replaced), checks every row arrived, moves jobs.db aside to
backups/ and sets JOBSEARCH_DB=postgres in .env. From then on `src.db.connect` opens Postgres
for the main database. `backup` writes Postgres to a dated SQLite file in backups/ (the daily
run does it), `export` writes one anywhere, and `rollback` writes Postgres back to jobs.db and
clears the setting.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src import pg_mirror
from src.pgdb import split_script, translate

BACKUP_GLOB = "jobs-20*.db"
ROLLED_BACK_PREFIX = "pre_rollback_"
_BATCH = 500


class CutoverError(RuntimeError):
    pass


def app_schema() -> list[str]:
    """Every CREATE statement the app runs on its database, in SQLite's dialect."""
    from src.db import SCHEMA as JOBS
    from src.enrich import ENRICH_SCHEMA
    from src.retention import SCHEMA as PRUNED
    from src.tailor.store import SCHEMA as APPLICATIONS

    return [s for script in (JOBS, APPLICATIONS, PRUNED, ENRICH_SCHEMA) for s in split_script(script)]


def fingerprint(db_path: str | Path) -> str:
    """A hash of jobs.db's bytes, to prove nothing wrote to it while it was copied."""
    path = Path(db_path)
    for side in (path.with_name(path.name + "-wal"), path.with_name(path.name + "-journal")):
        if side.exists():
            raise CutoverError(f"{side.name} exists: something has jobs.db open for writing")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_sqlite(db_path: str | Path) -> tuple[list[pg_mirror.Table], dict[str, list[tuple]], dict[str, int]]:
    lite = pg_mirror.open_sqlite(db_path)
    try:
        lite.execute("BEGIN")
        tables = pg_mirror.sqlite_tables(lite)
        data = {t.name: pg_mirror._read(lite, t) for t in tables}
        seq = {}
        if lite.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone():
            seq = dict(lite.execute("SELECT name, seq FROM sqlite_sequence").fetchall())
    finally:
        lite.close()
    return tables, data, seq


def _pg_columns(pg, table: str) -> list[str]:
    return [r[0] for r in pg.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = %s ORDER BY ordinal_position", (table,))]


def _pg_tables(pg) -> list[str]:
    return sorted(r[0] for r in pg.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() "
        "AND table_type = 'BASE TABLE'") if not r[0].startswith(ROLLED_BACK_PREFIX))


def copy_to_postgres(db_path: str | Path, pg) -> dict[str, int]:
    """Replace the Postgres tables with jobs.db's rows under the app's schema, in one
    transaction. Returns rows copied per table."""
    from psycopg import sql

    tables, data, seq = _read_sqlite(db_path)
    out = {}
    with pg.transaction():
        for t in tables:
            pg.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(t.name)))
        for stmt in app_schema():
            pg.execute(translate(stmt, has_params=False))
        for t in tables:
            _ensure_columns(pg, t)
            names = [c for c, _ in t.columns]
            insert = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                sql.Identifier(t.name), sql.SQL(", ").join(map(sql.Identifier, names)),
                sql.SQL(", ").join(sql.Placeholder() * len(names)))
            rows = [pg_mirror._fit(t, r) for r in data[t.name]]
            with pg.cursor() as cur:
                for i in range(0, len(rows), _BATCH):
                    cur.executemany(insert, rows[i:i + _BATCH])
            if "id" in names:
                _set_identity(pg, t.name, seq.get(t.name, 0))
            out[t.name] = len(rows)
    return out


def _ensure_columns(pg, t: pg_mirror.Table) -> None:
    """A table or column jobs.db has that no app schema names still comes across."""
    from psycopg import sql

    have = _pg_columns(pg, t.name)
    if not have:
        cols = [sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(typ)) for c, typ in t.columns]
        if t.pk:
            cols.append(sql.SQL("PRIMARY KEY ({})").format(sql.SQL(", ").join(map(sql.Identifier, t.pk))))
        pg.execute(sql.SQL("CREATE TABLE {} ({})").format(sql.Identifier(t.name), sql.SQL(", ").join(cols)))
        return
    for c, typ in t.columns:
        if c not in have:
            pg.execute(sql.SQL("ALTER TABLE {} ADD COLUMN {} {}").format(
                sql.Identifier(t.name), sql.Identifier(c), sql.SQL(typ)))


def _set_identity(pg, table: str, sqlite_seq: int) -> None:
    """New ids continue after the highest id SQLite ever handed out (deleted ones included),
    so a new job never takes an old job's number."""
    seq = pg.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table,)).fetchone()[0]
    if not seq:
        return
    top = pg.execute(f'SELECT COALESCE(MAX(id), 0) FROM "{table}"').fetchone()[0]
    last = max(int(top), int(sqlite_seq or 0))
    if last > 0:
        pg.execute("SELECT setval(%s::regclass, %s, true)", (seq, last))


def verify(db_path: str | Path, pg) -> dict[str, dict[str, Any]]:
    """Every jobs.db row, value for value, against Postgres (same shape as pg_mirror.check)."""
    from psycopg import sql

    tables, data, _ = _read_sqlite(db_path)
    out: dict[str, dict[str, Any]] = {}
    for t in tables:
        mine = pg_mirror._counts([pg_mirror.row_hash(pg_mirror._fit(t, r)) for r in data[t.name]])
        names = [c for c, _ in t.columns]
        rows = pg.execute(sql.SQL("SELECT {} FROM {}").format(
            sql.SQL(", ").join(map(sql.Identifier, names)), sql.Identifier(t.name))).fetchall()
        theirs = pg_mirror._counts([pg_mirror.row_hash(tuple(r)) for r in rows])
        differ = sum(abs(mine.get(h, 0) - theirs.get(h, 0)) for h in mine.keys() | theirs.keys())
        out[t.name] = {"sqlite": len(data[t.name]), "postgres": len(rows), "differ": differ,
                       "match": differ == 0}
    pg.rollback()
    return out


_SQLITE_TYPES = {"bigint": "INTEGER", "integer": "INTEGER", "smallint": "INTEGER",
                 "double precision": "REAL", "real": "REAL", "numeric": "NUMERIC", "bytea": "BLOB"}


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _identity_last(pg, table: str) -> int | None:
    seq = pg.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table,)).fetchone()[0]
    return pg.execute("SELECT pg_sequence_last_value(%s::regclass)", (seq,)).fetchone()[0] if seq else None


def export_sqlite(pg, dest: str | Path) -> dict[str, int]:
    """Write every Postgres table to a new SQLite file at `dest` with the app's schema
    (written beside it first, then moved into place). Returns rows per table."""
    from psycopg import sql

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".partial")
    tmp.unlink(missing_ok=True)
    lite = sqlite3.connect(tmp)
    out = {}
    try:
        for stmt in app_schema():
            lite.execute(stmt)
        for name in _pg_tables(pg):
            cols = pg.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position",
                (name,)).fetchall()
            have = [r[1] for r in lite.execute(f'PRAGMA table_info("{name}")')]
            if not have:
                defs = ", ".join(f"{_q(c)} {_SQLITE_TYPES.get(t, 'TEXT')}" for c, t in cols)
                lite.execute(f"CREATE TABLE {_q(name)} ({defs})")
            for c, t in cols:
                if have and c not in have:
                    lite.execute(f"ALTER TABLE {_q(name)} ADD COLUMN {_q(c)} {_SQLITE_TYPES.get(t, 'TEXT')}")
            names = [c for c, _ in cols]
            rows = pg.execute(sql.SQL("SELECT {} FROM {}").format(
                sql.SQL(", ").join(map(sql.Identifier, names)), sql.Identifier(name))).fetchall()
            marks = ", ".join("?" * len(names))
            lite.executemany(f"INSERT INTO {_q(name)} ({', '.join(map(_q, names))}) VALUES ({marks})", rows)
            out[name] = len(rows)
            last = _identity_last(pg, name) if "id" in names else None
            if last:
                lite.execute("UPDATE sqlite_sequence SET seq = max(seq, ?) WHERE name = ?", (last, name))
                if lite.execute("SELECT changes()").fetchone()[0] == 0:
                    lite.execute("INSERT INTO sqlite_sequence (name, seq) VALUES (?, ?)", (name, last))
        lite.commit()
        for name, n in out.items():
            if lite.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] != n:
                raise CutoverError(f"{name}: wrote {n} rows but the file holds a different count")
    finally:
        lite.close()
        pg.rollback()
    os.replace(tmp, dest)
    return out


def backup(pg, backups_dir: str | Path, keep: int = 14, today: str | None = None) -> tuple[Path, dict[str, int]]:
    """Today's SQLite copy of Postgres in backups/, keeping the newest `keep` of them."""
    backups_dir = Path(backups_dir)
    day = today or datetime.now().astimezone().date().isoformat()
    path = backups_dir / f"jobs-{day}.db"
    counts = export_sqlite(pg, path)
    for old in sorted(backups_dir.glob(BACKUP_GLOB))[:-keep] if keep > 0 else []:
        old.unlink(missing_ok=True)
    return path, counts


def latest_backup(backups_dir: str | Path) -> Path | None:
    found = sorted(Path(backups_dir).glob(BACKUP_GLOB))
    return found[-1] if found else None


def set_aside_pg_tables(pg) -> list[str]:
    """After a rollback, rename the Postgres tables out of the mirror's way (pre_rollback_*),
    so turning the mirror on again starts a fresh shadow copy. Nothing is deleted except an
    older set aside by an earlier rollback."""
    from psycopg import sql

    moved = []
    with pg.transaction():
        for name in _pg_tables(pg):
            aside = ROLLED_BACK_PREFIX + name
            pg.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(aside)))
            pg.execute(sql.SQL("ALTER TABLE {} RENAME TO {}").format(sql.Identifier(name), sql.Identifier(aside)))
            moved.append(name)
    return moved


def stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def move_aside(db_path: str | Path, backups_dir: str | Path, label: str) -> Path:
    """Move jobs.db into backups/ (fails while another program has it open on Windows)."""
    backups_dir = Path(backups_dir)
    backups_dir.mkdir(parents=True, exist_ok=True)
    dest = backups_dir / f"jobs-sqlite-{label}-{stamp()}.db"
    os.replace(db_path, dest)
    return dest


def restore_file(src: str | Path, db_path: str | Path) -> None:
    tmp = Path(str(db_path) + ".partial")
    shutil.copy2(src, tmp)
    os.replace(tmp, db_path)


def _drop(pg, names: list[str]) -> None:
    """Undo a copy that didn't pass: the next mirror sync builds its tables again."""
    from psycopg import sql

    pg.rollback()
    with pg.transaction():
        for name in names:
            pg.execute(sql.SQL("DROP TABLE IF EXISTS {} CASCADE").format(sql.Identifier(name)))


def run_cutover(db_path: str | Path, pg, *, env_path: str | Path, backups_dir: str | Path) -> dict[str, Any]:
    """The whole switch, stopping at the first thing that isn't right. jobs.db is only moved
    (never changed), so until the last step nothing the app reads has changed."""
    from dotenv import set_key, unset_key

    from src.db import BACKEND_ENV

    before = fingerprint(db_path)
    pg_mirror.sync(db_path, pg)
    gate = pg_mirror.check(db_path, pg)
    if not all(r["match"] for r in gate.values()):
        raise CutoverError("the mirror doesn't match jobs.db; nothing was switched")
    copied = copy_to_postgres(db_path, pg)
    report = verify(db_path, pg)
    if not all(r["match"] for r in report.values()):
        _drop(pg, list(copied))
        bad = ", ".join(n for n, r in report.items() if not r["match"])
        raise CutoverError(f"rows differ after the copy ({bad}); nothing was switched")
    if fingerprint(db_path) != before:
        _drop(pg, list(copied))
        raise CutoverError("jobs.db changed during the copy; stop whatever wrote it and run again")
    set_key(str(env_path), BACKEND_ENV, "postgres", quote_mode="never")
    try:
        moved = move_aside(db_path, backups_dir, "at-cutover")
    except OSError as e:
        unset_key(str(env_path), BACKEND_ENV)
        _drop(pg, list(copied))
        raise CutoverError(f"couldn't move jobs.db aside ({e}); is something holding it open? "
                           "Nothing was switched") from None
    return {"copied": copied, "report": report, "moved_to": str(moved)}


def run_rollback(pg, db_path: str | Path, *, env_path: str | Path, backups_dir: str | Path,
                 from_backup: str | Path | None = None) -> dict[str, Any]:
    """Back to jobs.db: Postgres written to jobs.db (or a backup copied there when Postgres
    can't be reached), then the setting cleared. Postgres keeps its tables, renamed."""
    from dotenv import unset_key

    from src.db import BACKEND_ENV

    stray = str(move_aside(db_path, backups_dir, "stray")) if Path(db_path).exists() else None
    if from_backup:
        restore_file(from_backup, db_path)
        counts: dict[str, int] = {}
    else:
        counts = export_sqlite(pg, db_path)
    unset_key(str(env_path), BACKEND_ENV)
    aside = set_aside_pg_tables(pg) if pg is not None and not from_backup else []
    return {"restored": counts, "from_backup": str(from_backup) if from_backup else None,
            "stray": stray, "set_aside": aside}
