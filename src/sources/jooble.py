"""Jooble job-search API adapter.

API: POST https://jooble.org/api/{JOOBLE_API_KEY} with JSON
`{"keywords": ..., "location": ..., "page": N}`; returns
`{"totalCount": N, "jobs": [{id, title, location, snippet, link, company, updated, ...}]}`.
Results carry a snippet only; src/enrich.py fills in the full posting where it can.
Needs a free Canada key from https://ca.jooble.org/api/about in .env as
JOOBLE_API_KEY; without one the source is skipped.
"""

from __future__ import annotations

import logging
import os

import httpx

from src.db import Job
from src.parser import html_to_markdown
from src.sources.ats_common import location_ok, make_client, post_json

logger = logging.getLogger(__name__)

API = "https://jooble.org/api/{key}"


def to_job(row: dict) -> Job:
    return Job(
        source="jooble",
        external_id=str(row.get("id") or row.get("link")),
        title=row.get("title") or "",
        company=row.get("company") or "",
        location=row.get("location") or "",
        description=html_to_markdown(row.get("snippet") or ""),
        url=row.get("link"),
        posted_date=(row.get("updated") or "")[:10] or None,
        raw={k: row.get(k) for k in ("source", "type", "salary")},
    )


def fetch_jooble_jobs(
    *,
    queries: list[str],
    location: str,
    max_pages: int = 2,
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> list[Job]:
    api_key = api_key or os.environ.get("JOOBLE_API_KEY")
    if not api_key:
        logger.info("Jooble: no JOOBLE_API_KEY set — skipping")
        return []
    own_client = client is None
    client = client or make_client()
    jobs: dict[str, Job] = {}
    try:
        for query in queries:
            for page in range(1, max_pages + 1):
                data = post_json(client, API.format(key=api_key), {"keywords": query, "location": location, "page": str(page)})
                rows = (data or {}).get("jobs") or []
                for row in rows:
                    job = to_job(row)
                    if job.external_id not in jobs and location_ok(job.location):
                        jobs[job.external_id] = job
                if len(rows) < 20:
                    break
    finally:
        if own_client:
            client.close()
    logger.info("Jooble: %d relevant job(s)", len(jobs))
    return list(jobs.values())
