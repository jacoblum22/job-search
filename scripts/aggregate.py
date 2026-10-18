"""CLI entry point for the multi-source job aggregator.

Pulls from Workday sources + the API sources (Adzuna, CareerJet) + Gmail
email-alert sources (LinkedIn/Indeed/Glassdoor), dedups everything, and
regenerates the dashboard (after each source, and again at the end) + xlsx export.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import partial
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv

from src.dashboard import generate_dashboard
from src.db import connect, upsert_job
from src.dedup import run_dedup
from src.enrich import DEFAULT_WORKERS as DEFAULT_ENRICH_WORKERS
from src.enrich import (
    SNIPPET_MAX_CHARS,
    backfill_stored,
    enrich_descriptions,
    worth_keeping,
)
from src.export_xlsx import generate_xlsx
from src.retention import is_stale, max_age_days, prune, pruned_keys
from src.score import rescore_all
from src.search_match import api_queries, keep_job, should_hydrate_record
from src.sources import ats_common
from src.sources.adzuna import fetch_adzuna_jobs
from src.sources.careerjet import fetch_careerjet_jobs
from src.sources.glassdoor_email import fetch_glassdoor_jobs
from src.sources.indeed_email import fetch_indeed_jobs
from src.sources.jobright_email import fetch_jobright_jobs
from src.sources.linkedin_email import fetch_linkedin_jobs
from src.sources.registry import BOARD_PLATFORMS, FEEDS
from src.sources.wellfound_email import fetch_wellfound_jobs
from src.sources.workday import fetch_workday_jobs

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "settings.yaml"
# Company job boards (Workday tenants + Greenhouse/Lever/Ashby/SmartRecruiters/
# Workable slugs), kept apart from settings.yaml so the list can grow without
# touching search settings.
DEFAULT_BOARDS = PROJECT_ROOT / "config" / "ats_boards.yaml"
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


def merge_boards(cfg: dict, boards_path: Path | None) -> dict:
    """Fold config/ats_boards.yaml into cfg: its `workday` entries join
    cfg["sources"] (skipping tenant/site pairs already there) and the other
    platforms land under cfg["ats_boards"]."""
    if not boards_path or not boards_path.exists():
        return cfg
    boards = load_config(boards_path) or {}
    boards.pop("bc_locations", None)  # YAML anchor holder, not a platform
    sources = list(cfg.get("sources") or [])
    seen = {(s.get("tenant"), s.get("site")) for s in sources}
    for entry in boards.pop("workday", None) or []:
        key = (entry.get("tenant"), entry.get("site"))
        if key not in seen:
            sources.append(entry)
            seen.add(key)
    return {**cfg, "sources": sources, "ats_boards": boards}


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


# Same list as BROWSER_SOURCES in scripts/browser_queue.py (stdlib-only, so
# it can't import from here).
BROWSER_SOURCES = ("linkedin", "indeed", "glassdoor", "careerjet", "jobright", "wellfound")


def _awaits_browser(job) -> bool:
    """A snippet-only listing the scheduled Chrome task will fill in."""
    return job.source in BROWSER_SOURCES and len(job.description or "") < SNIPPET_MAX_CHARS


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
    skip_ats: bool = False,
) -> None:
    conn = connect(db_path)
    new_count = 0
    total_fetched = 0
    search = cfg.get("search", {})
    enrich_cfg = cfg.get("enrich", {})
    par = cfg.get("concurrency") or {}
    ats_common.BOARD_WORKERS = par.get("board_workers", ats_common.BOARD_WORKERS)
    enrich_workers = par.get("enrich_workers", DEFAULT_ENRICH_WORKERS)

    max_days = max_age_days(cfg)
    pruned = pruned_keys(conn)
    # Prune first, so the dashboard refreshed after each source never shows them.
    removed = prune(conn, max_days)
    if removed:
        log.info("Deleted %d job(s) older than %d days", removed, max_days)
    conn.commit()

    def wanted(j) -> bool:
        return should_hydrate_record(j.title, search, company=j.company, location=j.location)

    def ingest(jobs: list, *, match_keywords: bool) -> None:
        nonlocal new_count, total_fetched
        # Old or already-deleted postings never come back (and aren't enriched).
        fresh = [j for j in jobs if (j.source, j.external_id) not in pruned and not is_stale(j.posted_date, max_days)]
        if len(fresh) != len(jobs):
            log.info("Skipped %d of %d job(s) older than %d days or deleted before", len(jobs) - len(fresh), len(jobs), max_days)
        jobs = fresh
        # Before filtering, so a keyword that only appears in the full posting
        # (not the snippet or title) still counts.
        if enrich_cfg.get("enabled", True):
            try:
                enrich_descriptions(
                    jobs,
                    conn=conn,
                    should_fetch=wanted,
                    host_pause=enrich_cfg.get("host_pause_seconds", 1.0),
                    max_fetches=enrich_cfg.get("max_fetches_per_source", 150),
                    workers=enrich_workers,
                )
            except Exception:
                log.exception("Description enrichment failed — keeping snippets")
            # Postings that turned out expired (404/410) were tombstoned; skip them
            # if a later source or query returns them again this run.
            pruned.update(pruned_keys(conn))
        # Don't store listings we wouldn't even fetch the full posting for.
        before = len(jobs)
        jobs = [j for j in jobs if worth_keeping(j, wanted)]
        if len(jobs) != before:
            log.info("Dropped %d of %d snippet-only listing(s) with irrelevant titles", before - len(jobs), before)
        # A snippet from a site only the Chrome task can read (LinkedIn,
        # Indeed, Glassdoor, ... — see BROWSER_SOURCES in
        # scripts/browser_queue.py) is stored once its title is worth a fetch
        # (worth_keeping above), without the keyword match: the snippet is too
        # short to judge, and the Chrome task fills in the full posting.
        kept = [
            j
            for j in jobs
            if keep_job(j, search, match_keywords=match_keywords and not _awaits_browser(j))
        ]
        if len(kept) != len(jobs):
            log.info("Filtered out %d of %d job(s) (keywords/location/level)", len(jobs) - len(kept), len(jobs))
        total_fetched += len(kept)
        for j in kept:
            _, was_new = upsert_job(conn, j)
            new_count += was_new
        if kept:
            refresh_dashboard()

    def refresh_dashboard() -> None:
        # Save and redraw after every source, so a long run shows results as it
        # goes instead of only at the end. Dedup and the xlsx still wait for the end.
        conn.commit()
        try:
            rescore_all(conn, cfg.get("score", {}))
            conn.commit()
            generate_dashboard(conn, dashboard_path)
        except Exception:
            log.exception("Dashboard refresh failed — continuing")

    # Every source except the email ones only talks to the web, so they all
    # download side by side on worker threads. Each finished download is then
    # enriched, filtered, saved and drawn into the dashboard here on the main
    # thread, one at a time, since jobs.db belongs to this thread.
    downloads: list[tuple[str, Callable[[], list]]] = []

    if not skip_apis:
        api_cfg = cfg.get("api_sources", {})
        queries = api_queries(search)
        location = search.get("location", "")
        remote_sweep = search.get("remote_sweep_location", "Canada")
        results_per_page = api_cfg.get("results_per_page", 20)
        max_pages = api_cfg.get("max_pages", 3)

        adzuna_cfg = api_cfg.get("adzuna", {})
        if adzuna_cfg.get("enabled", True):
            # Adzuna's free key allows 25 calls/minute and 2,500/month
            # (developer.adzuna.com/docs/terms_of_service), so it skips the
            # keyword x level searches and paces itself under the minute limit.
            adzuna_queries = api_queries(search, level_variants=adzuna_cfg.get("level_variants", False))
            downloads.append((
                "Adzuna",
                lambda: fetch_adzuna_jobs(
                    keywords=adzuna_queries,
                    location=location,
                    country=adzuna_cfg.get("country", "ca"),
                    results_per_page=results_per_page,
                    max_pages=max_pages,
                    remote_sweep_location=remote_sweep,
                    request_pause=adzuna_cfg.get("request_pause_seconds", 2.5),
                    max_days_old=max_days,
                    workers=par.get("adzuna_workers", 3),
                ),
            ))

        cj_cfg = api_cfg.get("careerjet", {})
        if cj_cfg.get("enabled", True):
            downloads.append((
                "CareerJet",
                lambda: fetch_careerjet_jobs(
                    keywords=queries,
                    location=location,
                    referer=cj_cfg.get("referer", ""),
                    locale_code=cj_cfg.get("locale_code", "en_CA"),
                    remote_sweep_location=remote_sweep,
                    max_pages=max_pages,
                ),
            ))

    if not skip_workday:
        downloads.append((
            "Workday",
            lambda: fetch_workday_jobs(
                cfg.get("sources", []),
                max_jobs=workday_limit,
                search=search,
                tenant_workers=par.get("workday_tenant_workers", 8),
            ),
        ))

    if not skip_ats:
        ats = cfg.get("ats_boards", {})
        for platform, fetch in BOARD_PLATFORMS.items():
            if ats.get(platform):
                downloads.append((platform, partial(fetch, ats[platform], search)))

        for name, options in (ats.get("feeds") or {}).items():
            options = options or {}
            if name not in FEEDS or options.get("enabled", True) is False:
                continue
            downloads.append((name, partial(FEEDS[name], options, search, list(search.get("keywords") or []))))

        unknown = set(ats) - set(BOARD_PLATFORMS) - {"feeds"}
        if unknown:
            log.warning("Unknown sections in the board list (ignored): %s", ", ".join(sorted(unknown)))

    def safe_ingest(label: str, jobs: list) -> None:
        try:
            ingest(jobs, match_keywords=True)
        except Exception:
            log.exception("Saving %s jobs failed — continuing with other sources", label)

    with ThreadPoolExecutor(max_workers=max(1, par.get("source_workers", 4))) as pool:
        pending = {pool.submit(fetch): label for label, fetch in downloads}

        # Email alerts read and update their cursors in jobs.db, so they run
        # here while the downloads above get going.
        if not skip_email:
            forward_from = cfg.get("email_sources", {}).get("forward_from") or None
            for fetch_fn in (
                fetch_linkedin_jobs, fetch_indeed_jobs, fetch_glassdoor_jobs,
                fetch_jobright_jobs, fetch_wellfound_jobs,
            ):
                try:
                    jobs = fetch_fn(conn, forward_from=forward_from)
                except Exception:
                    log.exception("%s fetch failed — continuing with other sources", fetch_fn.__module__)
                    continue
                safe_ingest(fetch_fn.__module__, jobs)

        for future in as_completed(pending):
            label = pending[future]
            try:
                jobs = future.result()
            except Exception:
                log.exception("%s fetch failed — continuing with other sources", label)
                continue
            log.info("%s: downloaded %d listing(s)", label, len(jobs))
            safe_ingest(label, jobs)

    conn.commit()
    log.info("Fetched %d jobs total (%d new)", total_fetched, new_count)

    # Work through stored listings still holding a snippet (over last run's
    # cap, or saved before enrichment existed). Login-walled links are left
    # to the Claude in Chrome task (scripts/browser_queue.py).
    if enrich_cfg.get("enabled", True):
        try:
            backfill_stored(
                conn,
                should_fetch=wanted,
                host_pause=enrich_cfg.get("host_pause_seconds", 1.0),
                max_fetches=enrich_cfg.get("backlog_fetches_per_run", 150),
                workers=enrich_workers,
            )
        except Exception:
            log.exception("Description backlog catch-up failed — continuing")

    merged = run_dedup(conn)
    log.info("Dedup merged %d job(s)", merged)

    tiers = rescore_all(conn, cfg.get("score", {}))
    log.info("Scored jobs by tier: %s", dict(sorted(tiers.items())))

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
@click.option(
    "--boards",
    "boards_path",
    type=click.Path(path_type=Path),
    default=DEFAULT_BOARDS,
    help="Company job-board list (Workday/Greenhouse/Lever/Ashby/SmartRecruiters/Workable)",
)
@click.option("--skip-ats", is_flag=True, help="Skip Greenhouse/Lever/Ashby/SmartRecruiters/Workable boards this run")
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
    boards_path: Path,
    skip_ats: bool,
    verbose: bool,
) -> None:
    """Aggregate jobs from all configured sources into the DB + dashboard + xlsx."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )
    # httpx INFO logs include the full URL, which embeds Adzuna app_key.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    if not _acquire_lock():
        log.warning("Another aggregate.py run is already in progress — skipping this run")
        return
    try:
        load_dotenv()
        cfg = merge_boards(load_config(config_path), boards_path)
        run(
            cfg,
            db_path=db_path,
            dashboard_path=dashboard_path,
            xlsx_path=xlsx_path,
            skip_workday=skip_workday,
            skip_apis=skip_apis,
            skip_email=skip_email,
            workday_limit=workday_limit,
            skip_ats=skip_ats,
        )
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
