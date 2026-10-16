"""Adzuna job-search API adapter.

Docs: https://developer.adzuna.com/docs/search
Auth: app_id + app_key as query params (no header-based auth).

The search endpoint only returns ~500-character snippets (confirmed against
live JSON). Adzuna has no public job-details API; the full posting is
filled in afterwards from each result's redirect_url by src/enrich.py.

Runs two geo passes: `location` (e.g. Vancouver) plus `remote_sweep_location`
filtered to `is_remote()` so Ottawa-tagged WFH is not missed.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from src.concurrency import RateLimiter, parallel_map
from src.db import Job
from src.http_retry import request_with_retry
from src.location_filter import is_remote

logger = logging.getLogger(__name__)

BASE_URL = "https://api.adzuna.com/v1/api/jobs"


def fetch_adzuna_jobs(
    *,
    keywords: list[str],
    location: str,
    country: str = "ca",
    results_per_page: int = 20,
    max_pages: int = 3,
    remote_sweep_location: str | None = "Canada",
    request_pause: float = 0.35,
    workers: int = 3,
    app_id: str | None = None,
    app_key: str | None = None,
    client: httpx.Client | None = None,
) -> list[Job]:
    """Fetch jobs from Adzuna for each keyword. Returns normalized Job records.

    Queries run `workers` at a time, but request starts are still spaced
    `request_pause` apart across all of them, so Adzuna never sees a burst.
    One failed query never aborts the rest. Transient 429/503 are retried;
    a persistent 503 stops *that query's* remaining pages only.
    """
    app_id = app_id or os.environ.get("ADZUNA_APP_ID", "")
    app_key = app_key or os.environ.get("ADZUNA_APP_KEY", "")
    if not app_id or not app_key:
        raise RuntimeError("Missing ADZUNA_APP_ID / ADZUNA_APP_KEY (set in .env)")

    owns_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(45.0, connect=15.0))
    limiter = RateLimiter(request_pause)
    sweep = remote_sweep_location
    if sweep and sweep.strip().lower() == (location or "").strip().lower():
        sweep = None

    # (keyword, where, remote_only): the local pass, then the remote sweep.
    tasks = [(kw, location, False) for kw in keywords]
    if sweep:
        tasks += [(kw, sweep, True) for kw in keywords]

    def run(task: tuple[str, str, bool]) -> list[Job]:
        keyword, where, remote_only = task
        try:
            found = _search(
                client, keyword, where, country, results_per_page, max_pages, app_id, app_key, limiter
            )
        except Exception:
            label = "remote-sweep query" if remote_only else "query"
            logger.exception("Adzuna %s %r in %r failed — continuing", label, keyword, where)
            return []
        return [j for j in found if not remote_only or is_remote(j.location)]

    by_id: dict[str, Job] = {}
    try:
        # Merged in task order, so the result doesn't depend on which query finished first.
        for found in parallel_map(run, tasks, workers):
            for job in found:
                by_id[job.external_id] = job
        jobs = list(by_id.values())
    finally:
        if owns_client:
            client.close()

    logger.info("Adzuna: fetched %d jobs", len(jobs))
    return jobs


def _search(
    client: httpx.Client,
    keyword: str,
    where: str,
    country: str,
    results_per_page: int,
    max_pages: int,
    app_id: str,
    app_key: str,
    limiter: RateLimiter | None = None,
) -> list[Job]:
    jobs: list[Job] = []
    pages = max(1, max_pages)
    for page in range(1, pages + 1):
        if limiter:
            limiter.wait()
        url = f"{BASE_URL}/{country}/search/{page}"
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "what": keyword,
            "where": where,
            "results_per_page": results_per_page,
            "content-type": "application/json",
        }
        logger.info("Adzuna: searching %r in %r (page %d)", keyword, where, page)
        resp = request_with_retry(client, "GET", url, params=params)
        if resp.status_code in (429, 502, 503, 504):
            logger.warning(
                "Adzuna HTTP %s for %r in %r page %d — keeping %d hit(s) for this query",
                resp.status_code,
                keyword,
                where,
                page,
                len(jobs),
            )
            break
        resp.raise_for_status()
        data = resp.json()
        batch = []
        for result in data.get("results", []):
            job = _to_job(result)
            if job:
                batch.append(job)
        jobs.extend(batch)
        if len(batch) < results_per_page:
            break
        total = data.get("count")
        if isinstance(total, int) and page * results_per_page >= total:
            break
    return jobs


def _to_job(result: dict[str, Any]) -> Job | None:
    job_id = result.get("id")
    title = result.get("title")
    if job_id is None or not title:
        return None

    return Job(
        source="adzuna",
        external_id=str(job_id),
        title=title,
        company=(result.get("company") or {}).get("display_name", ""),
        location=(result.get("location") or {}).get("display_name", ""),
        description=result.get("description", ""),
        url=result.get("redirect_url", ""),
        posted_date=result.get("created"),
        raw=result,
    )
