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
import time
from typing import Any

import httpx

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
    app_id: str | None = None,
    app_key: str | None = None,
    client: httpx.Client | None = None,
) -> list[Job]:
    """Fetch jobs from Adzuna for each keyword. Returns normalized Job records.

    One failed query never aborts the rest. Transient 429/503 are retried;
    a persistent 503 stops *that query's* remaining pages only.
    """
    app_id = app_id or os.environ.get("ADZUNA_APP_ID", "")
    app_key = app_key or os.environ.get("ADZUNA_APP_KEY", "")
    if not app_id or not app_key:
        raise RuntimeError("Missing ADZUNA_APP_ID / ADZUNA_APP_KEY (set in .env)")

    owns_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(45.0, connect=15.0))
    by_id: dict[str, Job] = {}
    sweep = remote_sweep_location
    if sweep and sweep.strip().lower() == (location or "").strip().lower():
        sweep = None

    def _absorb(jobs: list[Job], *, remote_only: bool) -> None:
        for job in jobs:
            if remote_only and not is_remote(job.location):
                continue
            by_id[job.external_id] = job

    try:
        for keyword in keywords:
            try:
                _absorb(
                    _search(
                        client,
                        keyword,
                        location,
                        country,
                        results_per_page,
                        max_pages,
                        app_id,
                        app_key,
                        request_pause,
                    ),
                    remote_only=False,
                )
            except Exception:
                logger.exception("Adzuna query %r in %r failed — continuing", keyword, location)

        if sweep:
            for keyword in keywords:
                try:
                    _absorb(
                        _search(
                            client,
                            keyword,
                            sweep,
                            country,
                            results_per_page,
                            max_pages,
                            app_id,
                            app_key,
                            request_pause,
                        ),
                        remote_only=True,
                    )
                except Exception:
                    logger.exception(
                        "Adzuna remote-sweep query %r in %r failed — continuing", keyword, sweep
                    )

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
    request_pause: float = 0.0,
) -> list[Job]:
    jobs: list[Job] = []
    pages = max(1, max_pages)
    for page in range(1, pages + 1):
        if request_pause and page > 1:
            time.sleep(request_pause)
        elif request_pause and page == 1:
            time.sleep(request_pause)
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
