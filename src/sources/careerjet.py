"""CareerJet job-search API adapter.

Public docs disagree on the current endpoint/auth scheme. The version
confirmed working by live testing is the v4 query API, which requires four
things together or it rejects the request: HTTP Basic auth (affiliate ID as
username, blank password), a real client IP, a user agent, and a Referer
header matching the site registered on the CareerJet publisher dashboard.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

import httpx

from src.db import Job, normalize

logger = logging.getLogger(__name__)

QUERY_URL = "https://search.api.careerjet.net/v4/query"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def fetch_careerjet_jobs(
    *,
    keywords: list[str],
    location: str,
    referer: str,
    locale_code: str = "en_CA",
    affid: str | None = None,
    client: httpx.Client | None = None,
) -> list[Job]:
    """Fetch jobs from CareerJet for each keyword. Returns normalized Job records."""
    affid = affid or os.environ.get("CAREERJET_AFFID", "")
    if not affid:
        raise RuntimeError("Missing CAREERJET_AFFID (set in .env)")
    if not referer:
        raise RuntimeError("CareerJet requires a Referer matching the registered publisher site")

    owns_client = client is None
    client = client or httpx.Client(timeout=30.0)
    jobs: list[Job] = []

    try:
        user_ip = _public_ip(client)
        headers = {"Referer": referer}

        for keyword in keywords:
            params = {
                "keywords": keyword,
                "location": location,
                "locale_code": locale_code,
                "user_ip": user_ip,
                "user_agent": USER_AGENT,
            }
            logger.info("CareerJet: searching %r in %r", keyword, location)
            resp = client.get(QUERY_URL, params=params, headers=headers, auth=(affid, ""))
            resp.raise_for_status()
            data = resp.json()

            if data.get("type") == "ERROR":
                logger.error("CareerJet error: %s", data.get("error"))
                continue

            for result in data.get("jobs", []):
                job = _to_job(result)
                if job:
                    jobs.append(job)
    finally:
        if owns_client:
            client.close()

    logger.info("CareerJet: fetched %d jobs", len(jobs))
    return jobs


def _public_ip(client: httpx.Client) -> str:
    """CareerJet validates user_ip looks like a real client address."""
    resp = client.get("https://api.ipify.org", timeout=10.0)
    resp.raise_for_status()
    return resp.text.strip()


def _to_job(result: dict[str, Any]) -> Job | None:
    url = result.get("url")
    title = result.get("title")
    company = result.get("company", "")
    location = result.get("locations", "")
    if not url or not title:
        return None

    # No stable ID is exposed, and the `url` itself is NOT stable either —
    # CareerJet mints a fresh jobviewtrack.com tracking URL on every single
    # call, even for the exact same query seconds apart (confirmed by
    # testing). Hashing it would make every job look "new" on every run and
    # the DB would grow unbounded. Hash normalized (title, company,
    # location) instead — stable across calls for the same real posting.
    key = f"{normalize(title)}|{normalize(company)}|{normalize(location)}"
    external_id = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]

    return Job(
        source="careerjet",
        external_id=external_id,
        title=title,
        company=company,
        location=location,
        description=result.get("description", ""),
        url=url,
        posted_date=result.get("date"),
        raw=result,
    )
