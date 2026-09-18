"""CLI entry point for the multi-source job aggregator.

Pulls from Workday sources + the API sources (Adzuna, CareerJet) configured
in settings.yaml, dedups everything, and regenerates the dashboard + xlsx
export. Email-alert sources (LinkedIn/Indeed/Glassdoor) are not wired in
yet — see AGGREGATION_PLAN.md.
"""

from __future__ import annotations

import logging
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv

from src.dashboard import generate_dashboard
from src.db import connect, upsert_job
from src.dedup import run_dedup
from src.export_xlsx import generate_xlsx
from src.sources.adzuna import fetch_adzuna_jobs
from src.sources.careerjet import fetch_careerjet_jobs
from src.sources.workday import fetch_workday_jobs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "settings.yaml"
DEFAULT_DB = PROJECT_ROOT / "jobs.db"
DEFAULT_DASHBOARD = PROJECT_ROOT / "dashboard.html"
DEFAULT_XLSX = PROJECT_ROOT / "export.xlsx"

log = logging.getLogger("aggregate")


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def run(
    cfg: dict,
    *,
    db_path: Path,
    dashboard_path: Path,
    xlsx_path: Path,
    skip_workday: bool,
    skip_apis: bool,
    workday_limit: int,
) -> None:
    conn = connect(db_path)
    new_count = 0
    total_fetched = 0

    if not skip_apis:
        api_cfg = cfg.get("api_sources", {})
        keywords = api_cfg.get("keywords", [])
        location = api_cfg.get("location", "")
        results_per_page = api_cfg.get("results_per_page", 20)

        if api_cfg.get("adzuna", {}).get("enabled", True):
            try:
                jobs = fetch_adzuna_jobs(
                    keywords=keywords,
                    location=location,
                    country=api_cfg.get("adzuna", {}).get("country", "ca"),
                    results_per_page=results_per_page,
                )
                total_fetched += len(jobs)
                for j in jobs:
                    _, was_new = upsert_job(conn, j)
                    new_count += was_new
            except Exception:
                log.exception("Adzuna fetch failed — continuing with other sources")

        cj_cfg = api_cfg.get("careerjet", {})
        if cj_cfg.get("enabled", True):
            try:
                jobs = fetch_careerjet_jobs(
                    keywords=keywords,
                    location=location,
                    referer=cj_cfg.get("referer", ""),
                    locale_code=cj_cfg.get("locale_code", "en_CA"),
                )
                total_fetched += len(jobs)
                for j in jobs:
                    _, was_new = upsert_job(conn, j)
                    new_count += was_new
            except Exception:
                log.exception("CareerJet fetch failed — continuing with other sources")

    if not skip_workday:
        try:
            jobs = fetch_workday_jobs(cfg.get("sources", []), max_jobs=workday_limit)
            total_fetched += len(jobs)
            for j in jobs:
                _, was_new = upsert_job(conn, j)
                new_count += was_new
        except Exception:
            log.exception("Workday fetch failed — continuing")

    conn.commit()
    log.info("Fetched %d jobs total (%d new)", total_fetched, new_count)

    merged = run_dedup(conn)
    log.info("Dedup merged %d job(s)", merged)

    generate_dashboard(conn, dashboard_path)
    generate_xlsx(conn, xlsx_path)
    log.info("Dashboard: %s", dashboard_path)
    log.info("Export: %s", xlsx_path)

    conn.close()


@click.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=DEFAULT_CONFIG,
)
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=DEFAULT_DB)
@click.option("--dashboard", "dashboard_path", type=click.Path(path_type=Path), default=DEFAULT_DASHBOARD)
@click.option("--xlsx", "xlsx_path", type=click.Path(path_type=Path), default=DEFAULT_XLSX)
@click.option("--skip-workday", is_flag=True, help="Skip Workday sources this run")
@click.option("--skip-apis", is_flag=True, help="Skip Adzuna/CareerJet this run")
@click.option("--workday-limit", type=int, default=0, help="Max jobs per Workday source (0 = all)")
@click.option("--verbose", "-v", is_flag=True)
def main(
    config_path: Path,
    db_path: Path,
    dashboard_path: Path,
    xlsx_path: Path,
    skip_workday: bool,
    skip_apis: bool,
    workday_limit: int,
    verbose: bool,
) -> None:
    """Aggregate jobs from all configured sources into the DB + dashboard + xlsx."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    load_dotenv()
    cfg = load_config(config_path)
    run(
        cfg,
        db_path=db_path,
        dashboard_path=dashboard_path,
        xlsx_path=xlsx_path,
        skip_workday=skip_workday,
        skip_apis=skip_apis,
        workday_limit=workday_limit,
    )


if __name__ == "__main__":
    main()
