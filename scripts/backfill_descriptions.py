"""One-off catch-up: fetch full descriptions for jobs already stored as snippets.

New listings are enriched automatically during scripts/aggregate.py; this is
for rows saved before that existed. Safe to re-run.
"""

from __future__ import annotations

import logging
from pathlib import Path

import click
import yaml

from src.db import connect
from src.enrich import backfill_stored
from src.search_match import should_hydrate_record

PROJECT_ROOT = Path(__file__).resolve().parent.parent


@click.command()
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=PROJECT_ROOT / "jobs.db")
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=PROJECT_ROOT / "config" / "settings.yaml",
)
@click.option("--limit", type=int, default=None, help="Max jobs to fetch (newest first)")
def main(db_path: Path, config_path: Path, limit: int | None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    search = yaml.safe_load(config_path.read_text(encoding="utf-8")).get("search", {})
    conn = connect(db_path)
    try:
        backfill_stored(
            conn,
            should_fetch=lambda j: should_hydrate_record(j.title, search, company=j.company, location=j.location),
            limit=limit,
            max_fetches=limit or 10_000,
        )
    finally:
        conn.close()


if __name__ == "__main__":
    main()
