"""Workday adapter — wraps the existing scraper to produce normalized Job records.

Reuses `src.scraper.AsyncWorkdayScraper` as-is (no changes to the proven scraping
logic). This adapter just maps its output into the shared `src.db.Job` shape so
Workday sources can feed the same aggregation DB as every other source, without
touching the existing markdown/tiering workflow in scripts/scrape.py.
"""

from __future__ import annotations

import asyncio
import logging

from src.db import Job
from src.location_filter import is_remote, is_vancouver_area
from src.parser import html_to_markdown
from src.scraper import AsyncWorkdayScraper
from src.search_match import should_hydrate_record

logger = logging.getLogger(__name__)


def _location_keywords(source: dict) -> list[str]:
    raw_filter = source.get("location_filter", "")
    if isinstance(raw_filter, str):
        return [raw_filter.lower()] if raw_filter else []
    return [kw.lower() for kw in raw_filter]


async def _fetch_source(
    source: dict, *, max_jobs: int, concurrency: int, search: dict | None
) -> list[Job]:
    name = source["name"]
    location_keywords = _location_keywords(source)

    async with AsyncWorkdayScraper(
        tenant=source["tenant"],
        site=source["site"],
        wd=source.get("wd", "wd10"),
        source_name=name,
        concurrency=concurrency,
        max_jobs=max_jobs,
    ) as scraper:
        summaries = await scraper.list_all_jobs()

        if location_keywords:
            summaries = [
                s
                for s in summaries
                if any(kw in (s.location or "").lower() for kw in location_keywords)
                or is_remote(s.location)
                or is_vancouver_area(name)
            ]

        if search:
            before = len(summaries)
            summaries = [
                s
                for s in summaries
                if should_hydrate_record(s.title, search, company=name, location=s.location)
            ]
            logger.info(
                "Workday %s: fetching details for %d/%d listings", name, len(summaries), before
            )

        if not summaries:
            return []

        results = await scraper.get_job_details_batch(summaries)

    jobs: list[Job] = []
    for summary, detail_or_err in results:
        if isinstance(detail_or_err, Exception):
            logger.error("Workday %s: failed to fetch %s: %s", name, summary.job_req_id, detail_or_err)
            continue
        detail = detail_or_err
        jobs.append(
            Job(
                source=f"workday:{source['tenant']}",
                external_id=detail.job_req_id or detail.id,
                title=detail.title,
                company=name,
                location=detail.location,
                description=html_to_markdown(detail.description_html),
                url=detail.external_url,
                posted_date=detail.start_date or detail.posted_on,
                raw=detail.raw,
            )
        )
    return jobs


async def _fetch_all(
    sources: list[dict], *, max_jobs: int, concurrency: int, search: dict | None
) -> list[Job]:
    active = [s for s in sources if s.get("enabled", True)]
    results = await asyncio.gather(
        *[_fetch_source(s, max_jobs=max_jobs, concurrency=concurrency, search=search) for s in active],
        return_exceptions=True,
    )
    jobs: list[Job] = []
    for source, result in zip(active, results, strict=True):
        if isinstance(result, Exception):
            logger.error("Workday %s failed: %s", source.get("name"), result)
            continue
        jobs.extend(result)
    logger.info("Workday: fetched %d jobs across %d source(s)", len(jobs), len(active))
    return jobs


def fetch_workday_jobs(
    sources: list[dict],
    *,
    max_jobs: int = 0,
    concurrency: int = 10,
    search: dict | None = None,
) -> list[Job]:
    """Fetch jobs from every enabled Workday source in settings.yaml. Sync wrapper."""
    return asyncio.run(_fetch_all(sources, max_jobs=max_jobs, concurrency=concurrency, search=search))
