"""Adzuna job-search API adapter.

Docs: https://developer.adzuna.com/docs/search
Auth: app_id + app_key as query params (no header-based auth).

The search endpoint only returns ~500-character snippets (confirmed against
live JSON). Adzuna has no public job-details API. The full posting is on
Adzuna's own land/ad page for that id — first-party HTML, not employer
scraping. We hydrate kept listings from that page (JSON-LD JobPosting).

Runs two geo passes: `location` (e.g. Vancouver) plus `remote_sweep_location`
filtered to `is_remote()` so Ottawa-tagged WFH is not missed.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

import httpx
from bs4 import BeautifulSoup

from src.db import Job
from src.http_retry import request_with_retry
from src.location_filter import is_remote
from src.parser import html_to_markdown
from src.search_match import should_hydrate_record

logger = logging.getLogger(__name__)

BASE_URL = "https://api.adzuna.com/v1/api/jobs"
# Public Adzuna job pages (same publisher as the API), keyed by country code.
_LAND_HOST = {
    "ca": "https://www.adzuna.ca",
    "gb": "https://www.adzuna.co.uk",
    "us": "https://www.adzuna.com",
    "au": "https://www.adzuna.com.au",
}


def fetch_adzuna_jobs(
    *,
    keywords: list[str],
    location: str,
    country: str = "ca",
    results_per_page: int = 20,
    max_pages: int = 3,
    remote_sweep_location: str | None = "Canada",
    request_pause: float = 0.35,
    hydrate: bool = True,
    search: dict[str, Any] | None = None,
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
        if hydrate:
            hydrate_adzuna_descriptions(jobs, country=country, client=client, search=search)
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


def hydrate_adzuna_descriptions(
    jobs: list[Job],
    *,
    country: str,
    client: httpx.Client,
    search: dict[str, Any] | None = None,
) -> None:
    """Replace search snippets with Adzuna land/ad JSON-LD when present."""
    host = _LAND_HOST.get(country, _LAND_HOST["ca"])
    for job in jobs:
        if search and not should_hydrate_record(
            job.title, search, company=job.company, location=job.location
        ):
            continue
        url = f"{host}/land/ad/{job.external_id}"
        try:
            resp = request_with_retry(client, "GET", url, retries=3, backoff=1.0)
            if resp.status_code != 200:
                continue
            full = description_from_adzuna_html(resp.text)
            if full and len(full) > len(job.description or ""):
                job.description = full
                # Recompute derived fields from the longer text.
                job.__post_init__()
        except httpx.RequestError:
            logger.warning("Adzuna land page failed for %s", job.external_id)


def description_from_adzuna_html(html: str) -> str:
    """Pull JobPosting.description from JSON-LD; fall back to #job-description."""
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        raw = script.string or script.get_text() or ""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        blocks = data if isinstance(data, list) else [data]
        for block in blocks:
            desc = _ld_job_description(block)
            if desc:
                return html_to_markdown(desc) if "<" in desc else desc.strip()
    node = soup.select_one("#job-description, .job-description, [itemprop=description]")
    if node:
        return html_to_markdown(str(node))
    return ""


def _ld_job_description(block: Any) -> str:
    if not isinstance(block, dict):
        return ""
    types = block.get("@type")
    type_list = types if isinstance(types, list) else [types]
    if any(str(t).lower() == "jobposting" for t in type_list if t):
        desc = block.get("description") or ""
        return desc if isinstance(desc, str) else ""
    graph = block.get("@graph")
    if isinstance(graph, list):
        for item in graph:
            found = _ld_job_description(item)
            if found:
                return found
    return ""


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
