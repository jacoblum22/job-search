"""Copy jobs.db into the Azure Postgres shadow copy, or compare the two (src/pg_mirror.py).

    uv run python scripts/pg_mirror.py sync      # make Postgres match jobs.db, then check
    uv run python scripts/pg_mirror.py check     # row counts per table, no changes
    uv run python scripts/pg_mirror.py history   # one line per logged sync/check

`sync --if-enabled` (what run_tailoring.ps1 calls) does nothing unless settings.yaml has
`database: {postgres_mirror: true}`. Exit codes: 0 ok, 1 error, 2 counts don't match.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import pg_mirror  # noqa: E402

DEFAULT_LOG = ROOT / "logs" / "pg-mirror.jsonl"


def _print_check(report: dict) -> bool:
    ok = all(r["match"] for r in report.values())
    for name, r in report.items():
        pg = "missing" if r["postgres"] is None else r["postgres"]
        mark = "ok" if r["match"] else f"DIFFERS ({r['differ']} rows)"
        click.echo(f"  {name:<20} sqlite {r['sqlite']:>6}   postgres {pg:>7}   {mark}")
    click.echo("All tables match." if ok else "Some tables don't match.")
    return ok


@click.command()
@click.argument("action", type=click.Choice(["sync", "check", "history"]), default="sync")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=ROOT / "jobs.db")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=ROOT / "config" / "settings.yaml")
@click.option("--log", "log_path", type=click.Path(path_type=Path), default=DEFAULT_LOG)
@click.option("--if-enabled", is_flag=True, help="Do nothing unless database.postgres_mirror is on.")
def main(action: str, db_path: Path, config_path: Path, log_path: Path, if_enabled: bool) -> None:
    if action == "history":
        if not log_path.exists():
            click.echo("No mirror runs logged yet.")
            return
        for line in log_path.read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            if not e["ok"]:
                click.echo(f"{e['at']}  {e['action']:<5}  ERROR {e['error']}")
                continue
            t = e["tables"]
            counts = ", ".join(f"{n} {r.get('sqlite', r.get('rows'))}" for n, r in t.items())
            if e["action"] == "sync":
                state = "synced"
            else:
                state = "match" if all(r["match"] for r in t.values()) else "MISMATCH"
            click.echo(f"{e['at']}  {e['action']:<5}  {state:<8}  {counts}")
        return

    if if_enabled:
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if not pg_mirror.enabled(cfg):
            return
    load_dotenv(ROOT / ".env")
    try:
        pg = pg_mirror.connect_pg()
    except Exception as e:  # noqa: BLE001 - logged and reported, never raised into the daily run
        pg_mirror.log_line(log_path, action, False, e)
        click.echo(f"Couldn't connect to Postgres: {e}", err=True)
        raise SystemExit(1) from None
    with pg:
        try:
            if action == "sync":
                stats = pg_mirror.sync(db_path, pg)
                pg_mirror.log_line(log_path, "sync", True, stats)
                for name, s in stats.items():
                    click.echo(f"  {name:<20} {s['rows']:>6} rows  +{s['inserted']} ~{s['updated']} -{s['deleted']}")
            report = pg_mirror.check(db_path, pg)
            pg_mirror.log_line(log_path, "check", True, report)
        except Exception as e:  # noqa: BLE001
            pg_mirror.log_line(log_path, action, False, e)
            click.echo(f"Mirror {action} failed: {e}", err=True)
            raise SystemExit(1) from None
    if not _print_check(report):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
