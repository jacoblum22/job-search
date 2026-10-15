"""CareerJet job-search API adapter.

Public docs disagree on the current endpoint/auth scheme. The version
confirmed working by live testing is the v4 query API, which requires four
things together or it rejects the request: HTTP Basic auth (affiliate ID as
username, blank password), a real client IP, a user agent, and a Referer
header matching the site registered on the CareerJet publisher dashboard.

Search snippets are ~300 characters; CareerJet does not expose a details
API. Tracking URLs are unstable (see `_to_job`). We paginate via `page`
when the response includes `pages`.

One failed query never aborts the source. Timeouts and 403s skip that query.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Any

import httpx

from src.db import Job, normalize
from src.http_retry import request_with_retry
from src.location_filter import is_remote

logger = logging.getLogger(__name__)

QUERY_URL = "https://search.api.careerjet.net/v4/query"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def fetch_careerjet_jobs(
    *,
    keywords: list[str],
    location: str,
    referer: str,
    locale_code: str = "en_CA",
    remote_sweep_location: str | None = "Canada",
    max_pages: int = 3,
    request_pause: float = 0.4,
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
    timeout = httpx.Timeout(90.0, connect=20.0)
    client = client or httpx.Client(timeout=timeout)
    by_id: dict[str, Job] = {}
    sweep = remote_sweep_location
    if sweep and sweep.strip().lower() == (location or "").strip().lower():
        sweep = None

    try:
        user_ip = _public_ip(client)
        headers = {"Referer": referer, "User-Agent": USER_AGENT}

        consecutive_403 = 0

        def absorb_search(keyword: str, loc: str, *, remote_only: bool) -> bool:
            """Return False if CareerJet is blocked (circuit open)."""
            nonlocal consecutive_403
            if consecutive_403 >= 3:
                return False
            found, status = _search(
                client,
                keyword,
                loc,
                locale_code,
                user_ip,
                headers,
                affid,
                max_pages,
                request_pause,
            )
            if status == 403:
                consecutive_403 += 1
                if consecutive_403 >= 3:
                    logger.error(
                        "CareerJet returned 403 three times — affiliate/IP/referer is blocked; "
                        "skipping remaining CareerJet queries this run"
                    )
                    return False
            else:
                consecutive_403 = 0
            for job in found:
                if remote_only and not is_remote(job.location):
                    continue
                by_id[job.external_id] = job
            return True

        for keyword in keywords:
            try:
                if not absorb_search(keyword, location, remote_only=False):
                    break
            except Exception:
                logger.exception("CareerJet query %r in %r failed — continuing", keyword, location)

        if sweep and consecutive_403 < 3:
            for keyword in keywords:
                try:
                    if not absorb_search(keyword, sweep, remote_only=True):
                        break
                except Exception:
                    logger.exception(
                        "CareerJet remote-sweep %r in %r failed — continuing", keyword, sweep
                    )
    finally:
        if owns_client:
            client.close()

    jobs = list(by_id.values())
    logger.info("CareerJet: fetched %d jobs", len(jobs))
    return jobs


def _search(
    client: httpx.Client,
    keyword: str,
    location: str,
    locale_code: str,
    user_ip: str,
    headers: dict[str, str],
    affid: str,
    max_pages: int = 1,
    request_pause: float = 0.0,
) -> tuple[list[Job], int]:
    jobs: list[Job] = []
    last_status = 200
    pages_cap = max(1, max_pages)
    total_pages = pages_cap
    for page in range(1, pages_cap + 1):
        if page > total_pages:
            break
        if request_pause:
            time.sleep(request_pause)
        params = {
            "keywords": keyword,
            "location": location,
            "locale_code": locale_code,
            "user_ip": user_ip,
            "user_agent": USER_AGENT,
            "page": page,
        }
        logger.info("CareerJet: searching %r in %r (page %d)", keyword, location, page)
        try:
            resp = request_with_retry(
                client,
                "GET",
                QUERY_URL,
                params=params,
                headers=headers,
                auth=(affid, ""),
                retries=4,
                backoff=2.0,
            )
        except httpx.RequestError as exc:
            logger.error("CareerJet network error for %r in %r: %s", keyword, location, exc)
            return jobs, 0
        last_status = resp.status_code
        if resp.status_code in (429, 502, 503, 504):
            logger.error(
                "CareerJet HTTP %s for %r in %r — stopping this query after %d job(s)",
                resp.status_code,
                keyword,
                location,
                len(jobs),
            )
            return jobs, resp.status_code
        if resp.status_code == 403:
            logger.error("CareerJet HTTP 403 for %r in %r — skipping this query", keyword, location)
            return jobs, 403
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.error(
                "CareerJet HTTP %s for %r in %r — skipping this query",
                exc.response.status_code,
                keyword,
                location,
            )
            return jobs, exc.response.status_code
        data = resp.json()
        if data.get("type") == "ERROR":
            logger.error("CareerJet error: %s", data.get("error"))
            return jobs, 200
        reported = data.get("pages")
        if isinstance(reported, int) and reported > 0:
            total_pages = min(pages_cap, reported)
        batch = []
        for result in data.get("jobs", []) or []:
            job = _to_job(result)
            if job:
                batch.append(job)
        jobs.extend(batch)
        if not batch:
            break
    return jobs, last_status


def _public_ip(client: httpx.Client) -> str:
    """CareerJet validates user_ip looks like a real client address."""
    resp = request_with_retry(client, "GET", "https://api.ipify.org", retries=3, timeout=10.0)
    resp.raise_for_status()
    return resp.text.strip()


def _to_job(result: dict[str, Any]) -> Job | None:
    url = result.get("url")
    title = result.get("title")
    company = result.get("company", "")
    location = result.get("locations", "")
    if not url or not title:
        return None

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
