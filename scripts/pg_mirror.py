"""The Azure Postgres copy of the job database (src/pg_mirror.py, src/pg_cutover.py).

Phase 3, while jobs.db is the main database:

    uv run python scripts/pg_mirror.py sync      # make Postgres match jobs.db, then check
    uv run python scripts/pg_mirror.py check     # row counts per table, no changes
    uv run python scripts/pg_mirror.py history   # one line per logged step

Phase 4 (docs/postgres-mirror.md):

    uv run python scripts/pg_mirror.py cutover   # move the main database to Postgres
    uv run python scripts/pg_mirror.py backup    # Postgres to backups/jobs-<date>.db
    uv run python scripts/pg_mirror.py export --to PATH   # a SQLite copy of the main database
    uv run python scripts/pg_mirror.py rollback  # Postgres back to jobs.db
    uv run python scripts/pg_mirror.py rollback --from-backup   # newest backup, Postgres unreachable
    uv run python scripts/pg_mirror.py rollback --from-backup --backup-file backups/jobs-2026-11-02.db

`daily` (what run_tailoring.ps1 calls) backs Postgres up once it is the main database, else
syncs the mirror when settings.yaml has `database: {postgres_mirror: true}`, else does nothing.
Exit codes: 0 ok, 1 error, 2 counts don't match.
"""

from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import pg_cutover, pg_mirror  # noqa: E402
from src.db import backend  # noqa: E402

DEFAULT_LOG = ROOT / "logs" / "pg-mirror.jsonl"
BACKUPS = ROOT / "backups"
ENV = ROOT / ".env"


def _print_check(report: dict) -> bool:
    ok = all(r["match"] for r in report.values())
    for name, r in report.items():
        pg = "missing" if r["postgres"] is None else r["postgres"]
        mark = "ok" if r["match"] else f"DIFFERS ({r['differ']} rows)"
        click.echo(f"  {name:<20} sqlite {r['sqlite']:>6}   postgres {pg:>7}   {mark}")
    click.echo("All tables match." if ok else "Some tables don't match.")
    return ok


def _print_counts(counts: dict) -> None:
    for name, n in counts.items():
        click.echo(f"  {name:<20} {n:>6} rows")


def _history(log_path: Path) -> None:
    if not log_path.exists():
        click.echo("No mirror runs logged yet.")
        return
    for line in log_path.read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if not e["ok"]:
            click.echo(f"{e['at']}  {e['action']:<8}  ERROR {e['error']}")
            continue
        t = e["tables"]
        if e["action"] in ("check", "cutover"):
            report = t.get("report", t) if e["action"] == "cutover" else t
            state = "match" if all(r["match"] for r in report.values()) else "MISMATCH"
            counts = ", ".join(f"{n} {r['sqlite']}" for n, r in report.items())
        elif e["action"] == "sync":
            state, counts = "synced", ", ".join(f"{n} {r['rows']}" for n, r in t.items())
        else:
            state = "done"
            counts = ", ".join(f"{n} {v}" for n, v in (t.get("counts") or {}).items()) or t.get("path", "")
        click.echo(f"{e['at']}  {e['action']:<8}  {state:<8}  {counts}")


def _busy() -> list[str]:
    """Anything that could write the database while it moves."""
    from src.tailor_runner import TailoringRunner

    found = []
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=1):
            found.append("the dashboard is running (stop the JobSearch-Dashboard task first)")
    except OSError:
        pass
    if (ROOT / ".aggregate.lock").exists():
        found.append("a scrape is running (.aggregate.lock exists)")
    if TailoringRunner(ROOT).status()["running"]:
        found.append("a tailoring run is going")
    return found


def _connect(log_path: Path, action: str):
    load_dotenv(ENV)
    try:
        return pg_mirror.connect_pg()
    except Exception as e:  # noqa: BLE001 - logged and reported, never raised into the daily run
        pg_mirror.log_line(log_path, action, False, e)
        click.echo(f"Couldn't connect to Postgres: {e}", err=True)
        raise SystemExit(1) from None


@click.command()
@click.argument("action", type=click.Choice(
    ["sync", "check", "history", "daily", "cutover", "backup", "export", "rollback"]), default="sync")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=ROOT / "jobs.db")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=ROOT / "config" / "settings.yaml")
@click.option("--log", "log_path", type=click.Path(path_type=Path), default=DEFAULT_LOG)
@click.option("--if-enabled", is_flag=True, help="Do nothing unless database.postgres_mirror is on.")
@click.option("--to", "to_path", type=click.Path(path_type=Path), help="export: the SQLite file to write.")
@click.option("--from-backup", is_flag=True,
              help="rollback: restore the newest backups/jobs-<date>.db instead of reading Postgres.")
@click.option("--backup-file", type=click.Path(path_type=Path),
              help="rollback --from-backup: this file instead of the newest.")
@click.option("--keep", default=14, show_default=True, help="backup: how many daily files to keep.")
def main(action: str, db_path: Path, config_path: Path, log_path: Path, if_enabled: bool,
         to_path: Path | None, from_backup: bool, backup_file: Path | None, keep: int) -> None:
    if action == "history":
        _history(log_path)
        return
    live = backend() == "postgres"

    if action == "daily":
        if live:
            action = "backup"
        else:
            cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
            if not pg_mirror.enabled(cfg):
                return
            action = "sync"
    elif action in ("sync", "check") and if_enabled:
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if live or not pg_mirror.enabled(cfg):
            return

    if action == "export":
        if not to_path:
            raise click.UsageError("export needs --to PATH")
        if not live:
            # The main database is jobs.db: a consistent copy of the file itself.
            import sqlite3

            src, dst = sqlite3.connect(db_path), sqlite3.connect(to_path)
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
            click.echo(f"Copied {db_path.name} to {to_path}")
            return
        with _connect(log_path, action) as pg:
            _print_counts(pg_cutover.export_sqlite(pg, to_path))
        click.echo(f"Wrote {to_path}")
        return

    if action == "rollback" and from_backup:
        if not live:
            raise click.ClickException("JOBSEARCH_DB isn't postgres; nothing to roll back")
        if busy := _busy():
            raise click.ClickException("Not now: " + "; ".join(busy))
        src_file = backup_file or pg_cutover.latest_backup(BACKUPS)
        if not src_file or not src_file.exists():
            raise click.ClickException("no backup file found in backups/")
        out = pg_cutover.run_rollback(None, db_path, env_path=ENV, backups_dir=BACKUPS, from_backup=src_file)
        pg_mirror.log_line(log_path, "rollback", True, out)
        click.echo(f"Restored {src_file.name} to jobs.db; JOBSEARCH_DB cleared. The app uses jobs.db again.")
        return

    pg = _connect(log_path, action)
    with pg:
        try:
            if action == "cutover":
                if live:
                    raise click.ClickException("JOBSEARCH_DB is already postgres")
                if busy := _busy():
                    raise click.ClickException("Not now: " + "; ".join(busy))
                out = pg_cutover.run_cutover(db_path, pg, env_path=ENV, backups_dir=BACKUPS)
                pg_mirror.log_line(log_path, "cutover", True, out)
                _print_check(out["report"])
                click.echo(f"jobs.db moved to {out['moved_to']}; JOBSEARCH_DB=postgres is in .env.")
                click.echo("Every task and the dashboard now read and write Postgres.")
                return
            if action == "rollback":
                if not live:
                    raise click.ClickException("JOBSEARCH_DB isn't postgres; nothing to roll back")
                if busy := _busy():
                    raise click.ClickException("Not now: " + "; ".join(busy))
                out = pg_cutover.run_rollback(pg, db_path, env_path=ENV, backups_dir=BACKUPS)
                pg_mirror.log_line(log_path, "rollback", True, {"counts": out["restored"], **out})
                _print_counts(out["restored"])
                click.echo("Postgres written to jobs.db; JOBSEARCH_DB cleared. The app uses jobs.db again.")
                click.echo("Postgres tables renamed pre_rollback_*; a mirror sync starts a fresh copy.")
                return
            if action == "backup":
                path, counts = pg_cutover.backup(pg, BACKUPS, keep=keep)
                pg_mirror.log_line(log_path, "backup", True, {"path": str(path), "counts": counts})
                _print_counts(counts)
                click.echo(f"Backed up to {path}")
                return
            if action == "sync":
                stats = pg_mirror.sync(db_path, pg)
                pg_mirror.log_line(log_path, "sync", True, stats)
                for name, s in stats.items():
                    click.echo(f"  {name:<20} {s['rows']:>6} rows  +{s['inserted']} ~{s['updated']} -{s['deleted']}")
            report = pg_mirror.check(db_path, pg)
            pg_mirror.log_line(log_path, "check", True, report)
        except click.ClickException:
            raise
        except Exception as e:  # noqa: BLE001
            pg_mirror.log_line(log_path, action, False, e)
            click.echo(f"{action} failed: {e}", err=True)
            raise SystemExit(1) from None
    if not _print_check(report):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
