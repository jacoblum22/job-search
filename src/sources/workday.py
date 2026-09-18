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
from src.parser import html_to_markdown
from src.scraper import AsyncWorkdayScraper

logger = logging.getLogger(__name__)


def _location_keywords(source: dict) -> list[str]:
    raw_filter = source.get("location_filter", "")
    if isinstance(raw_filter, str):
        return [raw_filter.lower()] if raw_filter else []
    return [kw.lower() for kw in raw_filter]


async def _fetch_source(source: dict, *, max_jobs: int, concurrency: int) -> list[Job]:
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
                s for s in summaries if any(kw in s.location.lower() for kw in location_keywords)
            ]

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


async def _fetch_all(sources: list[dict], *, max_jobs: int, concurrency: int) -> list[Job]:
    active = [s for s in sources if s.get("enabled", True)]
    results = await asyncio.gather(
        *[_fetch_source(s, max_jobs=max_jobs, concurrency=concurrency) for s in active]
    )
    jobs: list[Job] = []
    for r in results:
        jobs.extend(r)
    logger.info("Workday: fetched %d jobs across %d source(s)", len(jobs), len(active))
    return jobs


def fetch_workday_jobs(sources: list[dict], *, max_jobs: int = 0, concurrency: int = 10) -> list[Job]:
    """Fetch jobs from every enabled Workday source in settings.yaml. Sync wrapper."""
    return asyncio.run(_fetch_all(sources, max_jobs=max_jobs, concurrency=concurrency))
