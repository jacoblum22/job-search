"""Adzuna job-search API adapter.

Docs: https://developer.adzuna.com/docs/search
Auth: app_id + app_key as query params (no header-based auth).
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from src.db import Job

logger = logging.getLogger(__name__)

BASE_URL = "https://api.adzuna.com/v1/api/jobs"


def fetch_adzuna_jobs(
    *,
    keywords: list[str],
    location: str,
    country: str = "ca",
    results_per_page: int = 20,
    app_id: str | None = None,
    app_key: str | None = None,
    client: httpx.Client | None = None,
) -> list[Job]:
    """Fetch jobs from Adzuna for each keyword. Returns normalized Job records."""
    app_id = app_id or os.environ.get("ADZUNA_APP_ID", "")
    app_key = app_key or os.environ.get("ADZUNA_APP_KEY", "")
    if not app_id or not app_key:
        raise RuntimeError("Missing ADZUNA_APP_ID / ADZUNA_APP_KEY (set in .env)")

    owns_client = client is None
    client = client or httpx.Client(timeout=30.0)
    jobs: list[Job] = []

    try:
        for keyword in keywords:
            url = f"{BASE_URL}/{country}/search/1"
            params = {
                "app_id": app_id,
                "app_key": app_key,
                "what": keyword,
                "where": location,
                "results_per_page": results_per_page,
                "content-type": "application/json",
            }
            logger.info("Adzuna: searching %r in %r", keyword, location)
            resp = client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()

            for result in data.get("results", []):
                job = _to_job(result)
                if job:
                    jobs.append(job)
    finally:
        if owns_client:
            client.close()

    logger.info("Adzuna: fetched %d jobs", len(jobs))
    return jobs


def _to_job(result: dict[str, Any]) -> Job | None:
    job_id = result.get("id")
    title = result.get("title")
    if not job_id or not title:
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
