"""Workday API client for scraping job boards.

Uses the undocumented Workday CXS API directly (no browser needed):
  - POST /wday/cxs/{tenant}/{site}/jobs  → paginated job listings
  - GET  /wday/cxs/{tenant}/{site}/job/{path} → full job details

Supports both sync and async modes.  Async mode uses concurrent
requests with a configurable semaphore for speed.

The same API pattern works for *any* organisation running Workday —
just supply the appropriate tenant and site identifiers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# ── Default Workday instance (UBC) ─────────────────────────────────
DEFAULT_TENANT = "ubc"
DEFAULT_SITE = "ubcstaffjobs"
DEFAULT_WD = "wd10"


def _workday_urls(
    tenant: str = DEFAULT_TENANT,
    site: str = DEFAULT_SITE,
    wd: str = DEFAULT_WD,
) -> tuple[str, str, str]:
    """Build Workday API URLs from tenant/site identifiers.

    Returns:
        (base_url, jobs_endpoint, detail_endpoint)
    """
    base = f"https://{tenant}.{wd}.myworkdayjobs.com"
    jobs = f"{base}/wday/cxs/{tenant}/{site}/jobs"
    detail = f"{base}/wday/cxs/{tenant}/{site}"
    return base, jobs, detail


DEFAULT_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
}

PAGE_SIZE = 20  # Workday's default/max page size
MAX_RETRIES = 3
RETRY_BACKOFF = 2.0  # seconds, doubles with each retry


@dataclass
class JobSummary:
    """A single job from the listings endpoint."""

    title: str
    external_path: str
    location: str
    posted_on: str
    job_req_id: str  # e.g. "JR22878"
    source: str = ""  # human-readable source name, e.g. "UBC"
    bullet_fields: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> JobSummary | None:
        """Parse a job summary from the API. Returns None if data is invalid."""
        if "title" not in data or "externalPath" not in data:
            return None
        bullet = data.get("bulletFields", [])
        return cls(
            title=data["title"],
            external_path=data["externalPath"],
            location=data.get("locationsText", ""),
            posted_on=data.get("postedOn", ""),
            job_req_id=bullet[0] if bullet else "",
            bullet_fields=bullet,
        )


@dataclass
class JobDetail:
    """Full job posting details from the detail endpoint."""

    id: str
    title: str
    job_req_id: str
    location: str
    time_type: str  # "Full time", "Part time"
    posted_on: str
    start_date: str
    end_date: str
    description_html: str
    external_url: str
    external_path: str
    source: str = ""  # human-readable source name
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_api(cls, data: dict[str, Any], external_path: str) -> JobDetail:
        info = data.get("jobPostingInfo", {})
        return cls(
            id=info.get("id", ""),
            title=info.get("title", ""),
            job_req_id=info.get("jobReqId", ""),
            location=info.get("location", ""),
            time_type=info.get("timeType", ""),
            posted_on=info.get("postedOn", ""),
            start_date=info.get("startDate", ""),
            end_date=info.get("endDate", ""),
            description_html=info.get("jobDescription", ""),
            external_url=info.get("externalUrl", ""),
            external_path=external_path,
            raw=data,
        )


class WorkdayScraper:
    """Stateless HTTP client for a Workday job board API."""

    def __init__(
        self,
        *,
        tenant: str = DEFAULT_TENANT,
        site: str = DEFAULT_SITE,
        wd: str = DEFAULT_WD,
        source_name: str = "",
        delay: float = 2.0,
        timeout: float = 30.0,
        max_jobs: int = 0,
    ) -> None:
        """Initialise the synchronous Workday scraper.

        Args:
            tenant: Workday tenant identifier (e.g. ``"ubc"``).
            site: Workday site identifier (e.g. ``"ubcstaffjobs"``).
            wd: Workday instance number (e.g. ``"wd10"``).
            source_name: Human-readable name attached to each job.
            delay: Seconds to wait between paginated requests.
            timeout: HTTP request timeout in seconds.
            max_jobs: Stop after this many jobs (0 = unlimited).
        """
        _base, self._jobs_url, self._detail_url = _workday_urls(tenant, site, wd)
        self.source_name = source_name or tenant.upper()
        self.delay = delay
        self.timeout = timeout
        self.max_jobs = max_jobs
        self._client = httpx.Client(headers=DEFAULT_HEADERS, timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WorkdayScraper:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- Public API ----------------------------------------------------------

    def list_all_jobs(self) -> list[JobSummary]:
        """Fetch every job summary from the paginated listings endpoint."""
        all_jobs: list[JobSummary] = []
        offset = 0
        total = None

        while True:
            data = self._fetch_jobs_page(offset)
            if total is None:
                total = data.get("total", 0)
                logger.info("Total jobs on board: %d", total)

            postings = data.get("jobPostings", [])
            if not postings:
                break

            for p in postings:
                job = JobSummary.from_api(p)
                if job is not None:
                    job.source = self.source_name
                    all_jobs.append(job)
                else:
                    logger.warning("Skipping malformed job posting: %s", p)

            offset += len(postings)

            if self.max_jobs and len(all_jobs) >= self.max_jobs:
                all_jobs = all_jobs[: self.max_jobs]
                break

            if offset >= total:
                break

            time.sleep(self.delay)

        logger.info("Fetched %d job summaries", len(all_jobs))
        return all_jobs

    def get_job_detail(self, external_path: str) -> JobDetail:
        """Fetch the full details for a single job posting."""
        url = f"{self._detail_url}{external_path}"
        logger.debug("GET %s", url)
        resp = self._client.get(url)
        resp.raise_for_status()
        detail = JobDetail.from_api(resp.json(), external_path)
        detail.source = self.source_name
        return detail

    # -- Internal ------------------------------------------------------------

    def _fetch_jobs_page(self, offset: int) -> dict[str, Any]:
        payload = {
            "appliedFacets": {},
            "limit": PAGE_SIZE,
            "offset": offset,
            "searchText": "",
        }
        logger.debug("POST %s offset=%d", self._jobs_url, offset)
        resp = self._client.post(self._jobs_url, json=payload)
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Async scraper with concurrency control
# ---------------------------------------------------------------------------


class AsyncWorkdayScraper:
    """Async HTTP client with concurrent requests and retry logic."""

    def __init__(
        self,
        *,
        tenant: str = DEFAULT_TENANT,
        site: str = DEFAULT_SITE,
        wd: str = DEFAULT_WD,
        source_name: str = "",
        concurrency: int = 5,
        timeout: float = 30.0,
        max_jobs: int = 0,
    ) -> None:
        """Initialise the async Workday scraper.

        Args:
            tenant: Workday tenant identifier (e.g. ``"ubc"``).
            site: Workday site identifier (e.g. ``"ubcstaffjobs"``).
            wd: Workday instance number (e.g. ``"wd10"``).
            source_name: Human-readable name attached to each job.
            concurrency: Maximum number of simultaneous HTTP requests.
            timeout: HTTP request timeout in seconds.
            max_jobs: Stop after this many jobs (0 = unlimited).
        """
        _base, self._jobs_url, self._detail_url = _workday_urls(tenant, site, wd)
        self.source_name = source_name or tenant.upper()
        self.concurrency = concurrency
        self.timeout = timeout
        self.max_jobs = max_jobs
        self._client: httpx.AsyncClient | None = None
        self._semaphore = asyncio.Semaphore(concurrency)

    async def __aenter__(self) -> AsyncWorkdayScraper:
        self._client = httpx.AsyncClient(headers=DEFAULT_HEADERS, timeout=self.timeout)
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        assert self._client is not None, "Use 'async with' to create the client"
        return self._client

    async def list_all_jobs(self) -> list[JobSummary]:
        """Fetch every job summary (pagination is sequential — it's fast)."""
        all_jobs: list[JobSummary] = []
        offset = 0
        total = None

        while True:
            data = await self._fetch_jobs_page(offset)
            if total is None:
                total = data.get("total", 0)
                logger.info("%s: %d jobs on board", self.source_name, total)

            postings = data.get("jobPostings", [])
            if not postings:
                break

            for p in postings:
                job = JobSummary.from_api(p)
                if job is not None:
                    job.source = self.source_name
                    all_jobs.append(job)

            offset += len(postings)
            if self.max_jobs and len(all_jobs) >= self.max_jobs:
                all_jobs = all_jobs[: self.max_jobs]
                break
            if offset >= total:
                break

        logger.info("Fetched %d job summaries", len(all_jobs))
        return all_jobs

    async def get_job_detail(self, external_path: str) -> JobDetail:
        """Fetch full details with semaphore-controlled concurrency + retry."""
        async with self._semaphore:
            return await self._get_with_retry(external_path)

    async def get_job_details_batch(
        self, summaries: list[JobSummary]
    ) -> list[tuple[JobSummary, JobDetail | Exception]]:
        """Fetch details for many jobs concurrently. Returns (summary, detail_or_error) pairs."""

        async def _fetch_one(
            summary: JobSummary,
        ) -> tuple[JobSummary, JobDetail | Exception]:
            try:
                detail = await self.get_job_detail(summary.external_path)
                return (summary, detail)
            except Exception as e:
                logger.error("Failed to fetch %s: %s", summary.job_req_id, e)
                return (summary, e)

        tasks = [_fetch_one(s) for s in summaries]
        return await asyncio.gather(*tasks)

    # -- Internal ------------------------------------------------------------

    async def _fetch_jobs_page(self, offset: int) -> dict[str, Any]:
        payload = {
            "appliedFacets": {},
            "limit": PAGE_SIZE,
            "offset": offset,
            "searchText": "",
        }
        resp = await self.client.post(self._jobs_url, json=payload)
        resp.raise_for_status()
        return resp.json()

    async def _get_with_retry(
        self, external_path: str, retries: int = MAX_RETRIES
    ) -> JobDetail:
        url = f"{self._detail_url}{external_path}"
        for attempt in range(retries):
            resp = await self.client.get(url)

            if resp.status_code == 429:
                wait = RETRY_BACKOFF * (2**attempt)
                logger.warning(
                    "Rate limited (429) on %s — retrying in %.1fs (attempt %d/%d)",
                    external_path,
                    wait,
                    attempt + 1,
                    retries,
                )
                await asyncio.sleep(wait)
                continue

            resp.raise_for_status()
            detail = JobDetail.from_api(resp.json(), external_path)
            detail.source = self.source_name
            return detail

        # Final attempt — let it raise
        resp = await self.client.get(url)
        resp.raise_for_status()
        detail = JobDetail.from_api(resp.json(), external_path)
        detail.source = self.source_name
        return detail
