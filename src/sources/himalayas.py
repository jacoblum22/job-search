"""Himalayas remote-job board adapter (free public API).

Search: GET https://himalayas.app/jobs/api/search?q=..&country=CA&seniority=Entry-level,Mid-level&page=N
20 jobs a page with the full HTML `description`; page until one comes back
empty. One query per search keyword. `locationRestrictions` lists the
countries a remote job hires in; an empty list means worldwide.

No key is needed (unkeyed callers share one allowance). A free key from
himalayas.app/api-keys in .env as HIMALAYAS_API_KEY raises it to 10,000/day.
Terms: link back to the Himalayas listing and name Himalayas as the source,
so the stored url is the Himalayas page and the source is "himalayas".
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime

import httpx

from src.db import Job
from src.sources.ats_common import get_json, location_ok, make_client, to_markdown

logger = logging.getLogger(__name__)

API = "https://himalayas.app/jobs/api/search"
DEFAULT_SENIORITY = ["Entry-level", "Mid-level"]


def job_location(restrictions: list | None) -> str:
    countries = [c for c in restrictions or [] if isinstance(c, str) and c.strip()]
    return f"Remote - {', '.join(countries)}" if countries else "Remote - Worldwide"


def _date(ts) -> str | None:
    if isinstance(ts, (int, float)) and ts > 0:
        return datetime.fromtimestamp(ts, tz=UTC).date().isoformat()
    return None


def parse_page(data: dict | None) -> list[Job]:
    jobs = []
    for post in (data or {}).get("jobs") or []:
        guid = post.get("guid") or post.get("applicationLink")
        if not guid:
            continue
        location = job_location(post.get("locationRestrictions"))
        if not location_ok(location):
            continue
        jobs.append(
            Job(
                source="himalayas",
                external_id=guid,
                title=post.get("title") or "",
                company=post.get("companyName") or "",
                location=location,
                description=to_markdown(post.get("description")),
                url=guid,
                posted_date=_date(post.get("pubDate")),
                raw={
                    k: post.get(k)
                    for k in (
                        "companySlug", "seniority", "employmentType", "locationRestrictions",
                        "applicationLink", "minSalary", "maxSalary", "currency", "expiryDate",
                    )
                },
            )
        )
    return jobs


def fetch_himalayas_jobs(
    queries: list[str],
    *,
    country: str = "CA",
    seniority: list[str] | None = None,
    max_pages: int = 3,
    api_key: str | None = None,
    client: httpx.Client | None = None,
) -> list[Job]:
    own_client = client is None
    client = client or make_client()
    api_key = api_key if api_key is not None else os.environ.get("HIMALAYAS_API_KEY", "")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    levels = ",".join(seniority or DEFAULT_SENIORITY)
    found: dict[str, Job] = {}
    try:
        for query in queries:
            for page in range(1, max_pages + 1):
                params = {"q": query, "country": country, "sort": "recent", "page": page}
                if levels:
                    params["seniority"] = levels
                data = get_json(client, API, params=params, headers=headers)
                if not data or not data.get("jobs"):
                    break
                for job in parse_page(data):
                    found.setdefault(job.external_id, job)
                if len(data["jobs"]) < 20:
                    break
        logger.info("Himalayas: %d Canada-open remote job(s) from %d queries", len(found), len(queries))
        return list(found.values())
    finally:
        if own_client:
            client.close()
