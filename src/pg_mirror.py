"""Shadow copy of jobs.db in Postgres (Azure plan, phase 3).

jobs.db stays the source of truth: nothing reads Postgres yet. `sync` makes every
table in Postgres match jobs.db (new rows inserted, changed rows updated, rows gone
from jobs.db deleted), and `check` compares the two table by table. Both append a
line to logs/pg-mirror.jsonl, so a week of matching counts can be read back.

Tables and columns are read from jobs.db itself, so a column a later change adds
(or a new table) reaches Postgres on the next sync without touching this file.

Turned on by `database: {postgres_mirror: true}` in settings.yaml; the connection
string comes from JOBSEARCH_PG_URL in the git-ignored .env, never from a tracked file.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

URL_ENV = "JOBSEARCH_PG_URL"
HASH_COL = "_row_hash"
_BATCH = 200


class MirrorError(RuntimeError):
    pass


@dataclass
class Table:
    name: str
    columns: list[tuple[str, str]]  # (name, Postgres type), in jobs.db order
    pk: list[str] = field(default_factory=list)


def pg_type(declared: str) -> str:
    """The Postgres type for a SQLite column, by SQLite's own type-affinity rules."""
    d = (declared or "").upper()
    if "INT" in d:
        return "BIGINT"
    if any(t in d for t in ("CHAR", "CLOB", "TEXT")) or not d:
        return "TEXT"
    if "BLOB" in d:
        return "BYTEA"
    if any(t in d for t in ("REAL", "FLOA", "DOUB")):
        return "DOUBLE PRECISION"
    return "NUMERIC"


def sqlite_tables(conn: sqlite3.Connection) -> list[Table]:
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    tables = []
    for name in names:
        info = conn.execute(f'PRAGMA table_info("{name}")').fetchall()
        cols = [(r[1], pg_type(r[2])) for r in info]
        pk = [r[1] for r in sorted((r for r in info if r[5]), key=lambda r: r[5])]
        tables.append(Table(name, cols, pk))
    return tables


def row_hash(values: tuple) -> str:
    return hashlib.sha1(json.dumps(list(values), default=repr).encode("utf-8")).hexdigest()


def _coerce(value: Any, typ: str, where: str) -> Any:
    """SQLite lets any column hold any type; Postgres doesn't. Fit the value to the column
    or say exactly which row and column doesn't fit."""
    if value is None:
        return None
    if typ == "TEXT":
        if isinstance(value, bytes):
            raise MirrorError(f"{where}: bytes in a TEXT column")
        # Postgres text can't hold NUL characters; scraped text occasionally has them.
        return str(value).replace("\x00", "")
    if typ == "BIGINT":
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().lstrip("-").isdigit():
            return int(value)
        raise MirrorError(f"{where}: {value!r} in an INTEGER column")
    if typ in ("DOUBLE PRECISION", "NUMERIC"):
        if isinstance(value, (int, float)):
            return value
        try:
            return float(value)
        except (TypeError, ValueError):
            raise MirrorError(f"{where}: {value!r} in a {typ} column") from None
    return value


def open_sqlite(db_path: str | Path) -> sqlite3.Connection:
    """jobs.db read-only, so the mirror can never change it."""
    path = Path(db_path)
    if not path.exists():
        raise MirrorError(f"{path} does not exist")
    return sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=30)


def connect_pg(url: str | None = None):
    import psycopg

    url = url or os.environ.get(URL_ENV)
    if not url:
        raise MirrorError(f"{URL_ENV} is not set (add it to .env)")
    return psycopg.connect(url, connect_timeout=20)


def _ensure_pg_table(pg, t: Table) -> None:
    from psycopg import sql

    cols = [sql.SQL("{} {}").format(sql.Identifier(c), sql.SQL(typ)) for c, typ in t.columns]
    cols.append(sql.SQL("{} TEXT NOT NULL").format(sql.Identifier(HASH_COL)))
    if t.pk:
        cols.append(sql.SQL("PRIMARY KEY ({})").format(sql.SQL(", ").join(map(sql.Identifier, t.pk))))
    pg.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(
        sql.Identifier(t.name), sql.SQL(", ").join(cols)))
    have = {r[0] for r in pg.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
        "AND table_name = %s", (t.name,))}
    for c, typ in t.columns:
        if c not in have:
            pg.execute(sql.SQL("ALTER TABLE {} ADD COLUMN {} {}").format(
                sql.Identifier(t.name), sql.Identifier(c), sql.SQL(typ)))


def _read(lite: sqlite3.Connection, t: Table) -> list[tuple]:
    cols = ", ".join(f'"{c}"' for c, _ in t.columns)
    return lite.execute(f'SELECT {cols} FROM "{t.name}"').fetchall()


def _fit(t: Table, row: tuple) -> tuple:
    key = {c: row[i] for i, (c, _) in enumerate(t.columns) if c in t.pk}
    where = f"{t.name} {key}" if key else t.name
    return tuple(_coerce(v, typ, f"{where}.{c}") for v, (c, typ) in zip(row, t.columns, strict=True))


def _sync_table(pg, t: Table, rows: list[tuple]) -> dict[str, int]:
    from psycopg import sql

    ident = sql.Identifier(t.name)
    names = [c for c, _ in t.columns] + [HASH_COL]
    insert = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        ident, sql.SQL(", ").join(map(sql.Identifier, names)), sql.SQL(", ").join(sql.Placeholder() * len(names)))
    hashed = [(row, row_hash(row)) for row in rows]
    stats = {"rows": len(rows), "inserted": 0, "updated": 0, "deleted": 0}

    if not t.pk:
        # No key to match rows on: replace the table whenever its contents differ.
        have = sorted(r[0] for r in pg.execute(sql.SQL("SELECT {} FROM {}").format(sql.Identifier(HASH_COL), ident)))
        if have != sorted(h for _, h in hashed):
            stats["deleted"] = pg.execute(sql.SQL("DELETE FROM {}").format(ident)).rowcount
            with pg.cursor() as cur:
                cur.executemany(insert, [_fit(t, r) + (h,) for r, h in hashed])
            stats["inserted"] = len(rows)
        return stats

    pk_idx = [names.index(c) for c in t.pk]
    pk_cols = sql.SQL(", ").join(map(sql.Identifier, t.pk))
    have = {tuple(r[:-1]): r[-1] for r in pg.execute(
        sql.SQL("SELECT {}, {} FROM {}").format(pk_cols, sql.Identifier(HASH_COL), ident))}
    upsert = insert + sql.SQL(" ON CONFLICT ({}) DO UPDATE SET {}").format(
        pk_cols, sql.SQL(", ").join(
            sql.SQL("{0} = EXCLUDED.{0}").format(sql.Identifier(c)) for c in names if c not in t.pk))
    changed, seen = [], set()
    for row, h in hashed:
        fitted = _fit(t, row)
        key = tuple(fitted[i] for i in pk_idx)
        seen.add(key)
        old = have.get(key)
        if old == h:
            continue
        stats["updated" if old is not None else "inserted"] += 1
        changed.append(fitted + (h,))
    with pg.cursor() as cur:
        for i in range(0, len(changed), _BATCH):
            cur.executemany(upsert, changed[i:i + _BATCH])
        gone = [k for k in have if k not in seen]
        if gone:
            cond = sql.SQL(" AND ").join(sql.SQL("{} = %s").format(sql.Identifier(c)) for c in t.pk)
            cur.executemany(sql.SQL("DELETE FROM {} WHERE {}").format(ident, cond), gone)
    stats["deleted"] = len(gone)
    return stats


def sync(db_path: str | Path, pg) -> dict[str, dict[str, int]]:
    """Make Postgres match jobs.db, in one Postgres transaction (all tables or none)."""
    lite = open_sqlite(db_path)
    try:
        lite.execute("BEGIN")  # one consistent snapshot while the dashboard keeps writing
        tables = sqlite_tables(lite)
        data = {t.name: _read(lite, t) for t in tables}
    finally:
        lite.close()
    out = {}
    with pg.transaction():
        for t in tables:
            _ensure_pg_table(pg, t)
            out[t.name] = _sync_table(pg, t, data[t.name])
    return out


def check(db_path: str | Path, pg) -> dict[str, dict[str, Any]]:
    """Row counts per table on both sides, plus how many rows differ in content."""
    from psycopg import sql

    lite = open_sqlite(db_path)
    try:
        lite.execute("BEGIN")
        tables = sqlite_tables(lite)
        data = {t.name: _read(lite, t) for t in tables}
    finally:
        lite.close()
    pg_tables = {r[0] for r in pg.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()")}
    out: dict[str, dict[str, Any]] = {}
    for t in tables:
        mine = sorted(row_hash(r) for r in data[t.name])
        if t.name in pg_tables:
            theirs = sorted(r[0] for r in pg.execute(
                sql.SQL("SELECT {} FROM {}").format(sql.Identifier(HASH_COL), sql.Identifier(t.name))))
        else:
            theirs = None
        if theirs is None:
            out[t.name] = {"sqlite": len(mine), "postgres": None, "differ": len(mine), "match": False}
            continue
        a, b = _counts(mine), _counts(theirs)
        differ = sum(abs(a.get(h, 0) - b.get(h, 0)) for h in a.keys() | b.keys())
        out[t.name] = {"sqlite": len(mine), "postgres": len(theirs), "differ": differ, "match": differ == 0}
    pg.rollback()
    return out


def _counts(hashes: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for h in hashes:
        out[h] = out.get(h, 0) + 1
    return out


def enabled(cfg: dict | None) -> bool:
    return bool(((cfg or {}).get("database") or {}).get("postgres_mirror"))


def log_line(log_path: str | Path, action: str, ok: bool, detail: Any) -> None:
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "action": action,
             "ok": ok, "tables": detail} if ok else {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "action": action,
        "ok": False, "error": str(detail)}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
