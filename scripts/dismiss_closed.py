"""Dismiss every closed posting (past its deadline, or filled internally) in the live database.

    uv run python scripts/dismiss_closed.py            # do it
    uv run python scripts/dismiss_closed.py --dry-run  # only list them

The daily scrape does this on its own; run this to catch up right away.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.db import connect  # noqa: E402
from src.posting_status import dismiss_closed  # noqa: E402


@click.command()
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=PROJECT_ROOT / "jobs.db")
@click.option("--dry-run", is_flag=True, help="List what would be dismissed, change nothing")
def main(db_path: Path, dry_run: bool) -> None:
    conn = connect(db_path)
    closed = dismiss_closed(conn)
    if dry_run:
        conn.rollback()
    else:
        conn.commit()
    for c in closed:
        click.echo(f"{c['id']:>6}  {c['company']} - {c['title']}  ({c['reason']})")
    click.echo(f"{len(closed)} closed posting(s) {'would be ' if dry_run else ''}dismissed")
    conn.close()


if __name__ == "__main__":
    main()
