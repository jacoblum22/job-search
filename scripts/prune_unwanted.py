"""One-off clean-up: delete stored listings that hold only a snippet and whose
title isn't relevant enough to be worth fetching the full posting for.

New runs of scripts/aggregate.py no longer store these (see
src.enrich.worth_keeping); this clears the ones saved before that rule.
Dry run by default; pass --apply to delete. Jobs marked applied are never
deleted.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import click
import yaml

from src.db import Job, connect
from src.enrich import worth_keeping
from src.search_match import should_hydrate_record

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def unwanted_rows(conn, search: dict) -> list[tuple]:
    rows = conn.execute(
        "SELECT id, source, external_id, title, company, location, description, url FROM jobs"
        " WHERE status != 'applied'"
    ).fetchall()

    def wanted(j: Job) -> bool:
        return should_hydrate_record(j.title, search, company=j.company, location=j.location)

    out = []
    for row in rows:
        job = Job(*tuple(row)[1:])
        if not worth_keeping(job, wanted):
            out.append((row[0], row[1], row[3], row[4]))
    return out


@click.command()
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=PROJECT_ROOT / "jobs.db")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=PROJECT_ROOT / "config" / "settings.yaml",
)
@click.option("--apply", is_flag=True, help="Actually delete (default: just report)")
def main(db_path: Path, config_path: Path, apply: bool) -> None:
    search = yaml.safe_load(config_path.read_text(encoding="utf-8")).get("search", {})
    conn = connect(db_path)
    try:
        doomed = unwanted_rows(conn, search)
        by_source = Counter(src.split(":")[0] for _, src, _, _ in doomed)
        click.echo(f"{len(doomed)} snippet-only listing(s) with irrelevant titles: {dict(by_source.most_common())}")
        for _, src, title, company in doomed[:15]:
            click.echo(f"  {src}: {title} — {company}")
        if apply and doomed:
            conn.executemany("DELETE FROM jobs WHERE id = ?", [(d[0],) for d in doomed])
            conn.commit()
            click.echo(f"Deleted {len(doomed)}.")
        elif doomed:
            click.echo("Dry run; pass --apply to delete them.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
