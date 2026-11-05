"""Jobicy remote-job board adapter (free public API, no key).

GET https://jobicy.com/api/v2/remote-jobs?geo=canada&count=100[&cursor=..]
returns remote jobs published in the last 7 days that hire in Canada, with the
full HTML `jobDescription`; follow `nextCursor` while `hasMore`. Jobicy asks
for at most one pass an hour, which a daily scrape is well under.
Terms: credit Jobicy and link to its listing, so the stored url is the Jobicy
page and the source is "jobicy".
"""

from __future__ import annotations

import logging

import httpx

from src.db import Job
from src.sources.ats_common import get_json, location_ok, make_client, to_markdown

logger = logging.getLogger(__name__)

API = "https://jobicy.com/api/v2/remote-jobs"


def job_location(geo: str | None) -> str:
    geo = (geo or "").strip()
    return f"Remote - {geo}" if geo else "Remote - Canada"


def parse_page(data: dict | None) -> list[Job]:
    jobs = []
    for post in (data or {}).get("jobs") or []:
        if not post.get("id") or not post.get("url"):
            continue
        location = job_location(post.get("jobGeo"))
        if not location_ok(location):
            continue
        jobs.append(
            Job(
                source="jobicy",
                external_id=str(post["id"]),
                title=post.get("jobTitle") or "",
                company=post.get("companyName") or "",
                location=location,
                description=to_markdown(post.get("jobDescription")),
                url=post["url"],
                posted_date=(post.get("pubDate") or "")[:10] or None,
                raw={
                    k: post.get(k)
                    for k in ("jobGeo", "jobLevel", "jobType", "jobIndustry", "salaryMin", "salaryMax", "salaryCurrency")
                },
            )
        )
    return jobs


def fetch_jobicy_jobs(
    *,
    geo: str = "canada",
    industries: list[str] | None = None,
    max_pages: int = 5,
    client: httpx.Client | None = None,
) -> list[Job]:
    """One cursor walk per industry (or one unfiltered walk when none given)."""
    own_client = client is None
    client = client or make_client()
    found: dict[str, Job] = {}
    try:
        for industry in industries or [None]:
            cursor = None
            for _ in range(max_pages):
                params = {"geo": geo, "count": 100}
                if industry:
                    params["industry"] = industry
                if cursor:
                    params["cursor"] = cursor
                data = get_json(client, API, params=params)
                if not data:
                    break
                for job in parse_page(data):
                    found.setdefault(job.external_id, job)
                cursor = data.get("nextCursor")
                if not data.get("hasMore") or not cursor:
                    break
        logger.info("Jobicy: %d Canada-open remote job(s)", len(found))
        return list(found.values())
    finally:
        if own_client:
            client.close()
