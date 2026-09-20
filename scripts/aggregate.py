"""CLI entry point for the multi-source job aggregator.

Pulls from Workday sources + the API sources (Adzuna, CareerJet) + Gmail
email-alert sources (LinkedIn/Indeed/Glassdoor), dedups everything, and
regenerates the dashboard + xlsx export.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv

from src.dashboard import generate_dashboard
from src.db import connect, upsert_job
from src.dedup import run_dedup
from src.export_xlsx import generate_xlsx
from src.gmail_client import get_gmail_service
from src.sources.adzuna import fetch_adzuna_jobs
from src.sources.careerjet import fetch_careerjet_jobs
from src.sources.glassdoor_email import fetch_glassdoor_jobs
from src.sources.indeed_email import fetch_indeed_jobs
from src.sources.linkedin_email import fetch_linkedin_jobs
from src.sources.workday import fetch_workday_jobs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "settings.yaml"
DEFAULT_DB = PROJECT_ROOT / "jobs.db"
DEFAULT_DASHBOARD = PROJECT_ROOT / "dashboard.html"
DEFAULT_XLSX = PROJECT_ROOT / "export.xlsx"

LOCK_PATH = PROJECT_ROOT / ".aggregate.lock"
# A real run finishes in well under this; anything older means a previous
# process crashed without cleaning up, not that it's still legitimately running.
STALE_LOCK_SECONDS = 30 * 60

log = logging.getLogger("aggregate")


def load_config(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _acquire_lock() -> bool:
    """Single-instance lock so overlapping scheduled runs (e.g. the 10-minute
    email check firing again while a slow Workday scrape is still running)
    can't pile up contending for jobs.db. Returns False if another instance
    already holds the lock — the caller should skip this run entirely rather
    than wait, since the other instance will finish on its own.
    """
    try:
        fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        age = time.time() - LOCK_PATH.stat().st_mtime
        if age < STALE_LOCK_SECONDS:
            return False
        log.warning("Clearing stale lock file (age %.0fs) — previous run likely crashed", age)
        LOCK_PATH.unlink(missing_ok=True)
        return _acquire_lock()


def _release_lock() -> None:
    LOCK_PATH.unlink(missing_ok=True)


def run(
    cfg: dict,
    *,
    db_path: Path,
    dashboard_path: Path,
    xlsx_path: Path,
    skip_workday: bool,
    skip_apis: bool,
    skip_email: bool,
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

    if not skip_email:
        try:
            gmail_service = get_gmail_service()
        except RuntimeError as e:
            log.warning("Skipping email-alert sources: %s", e)
        else:
            forward_from = cfg.get("email_sources", {}).get("forward_from") or None
            for fetch_fn in (fetch_linkedin_jobs, fetch_indeed_jobs, fetch_glassdoor_jobs):
                try:
                    jobs = fetch_fn(gmail_service, conn, forward_from=forward_from)
                    total_fetched += len(jobs)
                    for j in jobs:
                        _, was_new = upsert_job(conn, j)
                        new_count += was_new
                except Exception:
                    log.exception("%s fetch failed — continuing with other sources", fetch_fn.__module__)

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
@click.option("--skip-email", is_flag=True, help="Skip LinkedIn/Indeed/Glassdoor email alerts this run")
@click.option("--workday-limit", type=int, default=0, help="Max jobs per Workday source (0 = all)")
@click.option("--verbose", "-v", is_flag=True)
def main(
    config_path: Path,
    db_path: Path,
    dashboard_path: Path,
    xlsx_path: Path,
    skip_workday: bool,
    skip_apis: bool,
    skip_email: bool,
    workday_limit: int,
    verbose: bool,
) -> None:
    """Aggregate jobs from all configured sources into the DB + dashboard + xlsx."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    if not _acquire_lock():
        log.warning("Another aggregate.py run is already in progress — skipping this run")
        return
    try:
        load_dotenv()
        cfg = load_config(config_path)
        run(
            cfg,
            db_path=db_path,
            dashboard_path=dashboard_path,
            xlsx_path=xlsx_path,
            skip_workday=skip_workday,
            skip_apis=skip_apis,
            skip_email=skip_email,
            workday_limit=workday_limit,
        )
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
