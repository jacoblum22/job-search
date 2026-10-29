"""Fill in full descriptions for listings that only came with a snippet.

Adzuna's API returns ~500-char snippets and CareerJet ~300. Each listing's
own `url` (Adzuna's tracked `redirect_url`) opens the full posting, which
almost always carries a schema.org JobPosting JSON-LD block (39/40 of the
top Adzuna matches in testing, 2026-10-15). We follow that link, pull the description, and keep it if it's
longer than what we have.

Note: Adzuna's bare `/details/{id}` and `/land/ad/{id}` paths return 403 from
CloudFront; only the tracked redirect_url (with its utm params) is served.

Rate-limited per host, retried on transient errors, and every failure is
logged and skipped — enrichment never aborts a scrape. A link that answers
404/410 means the posting is gone: the job is deleted from jobs.db (unless
applied to) and tombstoned so it's never re-scraped. Attempts are recorded
in `enrich_attempts` so scheduled runs don't refetch the same dead link (or a
posting the filters dropped anyway) and the per-run cap works through the
backlog instead.
"""

from __future__ import annotations

import html
import json
import logging
import re
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from src.concurrency import RateLimiter, host_of, parallel_map
from src.db import Job
from src.http_retry import request_with_retry
from src.parser import html_to_markdown
from src.retention import delete_expired

logger = logging.getLogger(__name__)

# Descriptions shorter than this are treated as snippets worth expanding.
SNIPPET_MAX_CHARS = 1000
# A fetched description must be at least this long to count — guards against
# grabbing a cookie banner or "job no longer available" stub.
MIN_FULL_CHARS = 600
DEFAULT_HOST_PAUSE = 1.0
DEFAULT_MAX_FETCHES = 150
# Pages fetched at once. Each host is still rate-limited to one new request per
# host_pause, so this mostly overlaps slow responses and different sites.
DEFAULT_WORKERS = 6
RETRY_FAILED_AFTER = timedelta(days=3)
# Responses that mean the posting itself is gone, not that the fetch failed.
EXPIRED_STATUSES = frozenset({404, 410})

# Pages where a plain fetch never yields the posting: login-walled boards, and
# CareerJet, whose jobviewtrack links mostly 404 and otherwise land on a
# careerjet.ca shell with no description (0/25 in testing, 2026-10-15).
# Jobright's job pages render in the browser (0/35 fetched, 2026-10-29).
SKIP_HOSTS = ("linkedin.com", "indeed.com", "glassdoor.", "jobviewtrack.com", "careerjet.", "jobright.ai")

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36"
)

# Page-specific containers, tried after JSON-LD. Adzuna's is .adp-body.
_FALLBACK_SELECTORS = (
    ".adp-body",
    "#job-description",
    ".job-description",
    "[itemprop=description]",
    "#jobDescriptionText",
    ".posting-description",
)

ENRICH_SCHEMA = """
CREATE TABLE IF NOT EXISTS enrich_attempts (
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    PRIMARY KEY (source, external_id)
);
"""


def worth_keeping(job: Job, wanted: Callable[[Job], bool]) -> bool:
    """Every stored listing should have its full posting or be on its way to
    one. A listing still holding only a snippet (or nothing) is kept only if
    it's one we'd spend a fetch on (`wanted`, normally title relevance);
    anything less relevant isn't worth storing at all.
    """
    return len(job.description or "") >= SNIPPET_MAX_CHARS or wanted(job)


def needs_enrichment(job: Job) -> bool:
    if len(job.description or "") >= SNIPPET_MAX_CHARS or not job.url:
        return False
    host = urlparse(job.url).netloc.lower()
    return bool(host) and not any(s in host for s in SKIP_HOSTS)


def enrich_descriptions(
    jobs: list[Job],
    *,
    conn: sqlite3.Connection | None = None,
    should_fetch: Callable[[Job], bool] | None = None,
    client: httpx.Client | None = None,
    host_pause: float = DEFAULT_HOST_PAUSE,
    max_fetches: int = DEFAULT_MAX_FETCHES,
    workers: int = DEFAULT_WORKERS,
) -> Counter:
    """Replace snippet descriptions in-place with the full posting text.

    Listings whose link answers 404/410 are removed from `jobs` (so the caller
    doesn't store them) and, with `conn`, deleted and tombstoned in jobs.db.

    `should_fetch` narrows which listings are worth a request (e.g. title
    relevance). With `conn`, listings already stored with a full description
    reuse it, and listings attempted recently (failed, or fetched but then
    filtered out) are not refetched.
    Returns counts: enriched / failed / expired / reused / skipped_recent / capped.
    """
    stats: Counter = Counter()
    if conn is not None:
        conn.executescript(ENRICH_SCHEMA)
    owns_client = client is None
    client = client or httpx.Client(
        timeout=httpx.Timeout(20.0, connect=10.0),
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-CA,en;q=0.9",
        },
    )
    to_fetch: list[Job] = []
    expired: list[Job] = []
    try:
        # Decide what to fetch first (this reads jobs.db, so it stays on this thread)...
        for job in jobs:
            if not needs_enrichment(job):
                continue
            if should_fetch is not None and not should_fetch(job):
                continue
            if conn is not None:
                stored = _stored_description(conn, job)
                if len(stored) >= SNIPPET_MAX_CHARS:
                    _apply(job, stored)
                    stats["reused"] += 1
                    continue
                if _recently_attempted(conn, job):
                    stats["skipped_recent"] += 1
                    continue
            if len(to_fetch) >= max_fetches:
                stats["capped"] += 1
                continue
            to_fetch.append(job)

        # ...then fetch several pages at once, each site still getting at most
        # one new request per `host_pause` seconds...
        limiter = RateLimiter(host_pause)
        to_fetch = _interleave_hosts(to_fetch)

        def fetch(job: Job) -> tuple[str, bool]:
            limiter.wait(host_of(job.url))
            try:
                return _fetch_description(client, job)
            except Exception:
                logger.exception("Enrich %s %s: fetch failed", job.source, job.external_id)
                return "", False

        pages = parallel_map(fetch, to_fetch, workers)

        # ...and write the results back here.
        for job, (full, gone) in zip(to_fetch, pages, strict=True):
            if gone:
                expired.append(job)
                continue
            ok = bool(full) and len(full) > len(job.description or "")
            if ok:
                _apply(job, full)
                stats["enriched"] += 1
            else:
                stats["failed"] += 1
            if conn is not None:
                _record_attempt(conn, job, ok)
    finally:
        if owns_client:
            client.close()
    if expired:
        stats["expired"] = len(expired)
        gone_keys = {(j.source, j.external_id) for j in expired}
        jobs[:] = [j for j in jobs if (j.source, j.external_id) not in gone_keys]
        if conn is not None:
            deleted = delete_expired(conn, gone_keys)
            logger.info("Deleted %d expired posting(s) from jobs.db (404/410)", deleted)
    if stats:
        logger.info(
            "Description enrichment: %d enriched, %d failed, %d expired, %d reused, %d skipped (recently attempted), %d over cap",
            stats["enriched"],
            stats["failed"],
            stats["expired"],
            stats["reused"],
            stats["skipped_recent"],
            stats["capped"],
        )
    return stats


def _apply(job: Job, description: str) -> None:
    job.description = description
    job.__post_init__()  # recompute years_experience from the full text


def _interleave_hosts(jobs: list[Job]) -> list[Job]:
    """Round-robin by host, so a long run of one site's links doesn't tie up
    every worker waiting on that site's rate limit while other sites sit idle."""
    by_host: dict[str, list[Job]] = {}
    for job in jobs:
        by_host.setdefault(host_of(job.url), []).append(job)
    queues = list(by_host.values())
    out: list[Job] = []
    for i in range(max((len(q) for q in queues), default=0)):
        out.extend(q[i] for q in queues if i < len(q))
    return out


def _fetch_description(client: httpx.Client, job: Job) -> tuple[str, bool]:
    """Return (description, expired). Description is "" when the fetch failed;
    expired is True only when the link answered 404/410."""
    try:
        resp = request_with_retry(client, "GET", job.url, retries=3, backoff=2.0)
    except httpx.HTTPError as exc:
        logger.warning("Enrich %s %s: network error %s", job.source, job.external_id, type(exc).__name__)
        return "", False
    if resp.status_code in EXPIRED_STATUSES:
        logger.info(
            "Enrich %s %s: posting expired (HTTP %s from %s)",
            job.source,
            job.external_id,
            resp.status_code,
            urlparse(str(resp.url)).netloc,
        )
        return "", True
    if resp.status_code != 200:
        logger.warning(
            "Enrich %s %s: HTTP %s from %s",
            job.source,
            job.external_id,
            resp.status_code,
            urlparse(str(resp.url)).netloc,
        )
        return "", False
    try:
        text = description_from_html(resp.text)
    except Exception:
        logger.exception("Enrich %s %s: failed to parse page", job.source, job.external_id)
        return "", False
    if len(text) < MIN_FULL_CHARS:
        logger.warning(
            "Enrich %s %s: no full description on %s",
            job.source,
            job.external_id,
            urlparse(str(resp.url)).netloc,
        )
        return "", False
    return text, False


def description_from_html(html: str) -> str:
    """Pull JobPosting.description from JSON-LD; fall back to known containers."""
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
                return _clean(desc)
    for selector in _FALLBACK_SELECTORS:
        node = soup.select_one(selector)
        if node:
            text = _clean(str(node))
            if text:
                return text
    return ""


def _clean(desc: str) -> str:
    if "<" not in desc and "&lt;" in desc:
        # JSON-LD descriptions are sometimes HTML-escaped HTML.
        desc = html.unescape(desc)
    if "<" in desc:
        return html_to_markdown(desc).strip()
    return desc.strip()


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


def _stored_description(conn: sqlite3.Connection, job: Job) -> str:
    row = conn.execute(
        "SELECT description FROM jobs WHERE source = ? AND external_id = ?",
        (job.source, job.external_id),
    ).fetchone()
    return (row[0] or "") if row else ""


def _recently_attempted(conn: sqlite3.Connection, job: Job) -> bool:
    """True for a recent dead link, or a recent success that wasn't stored
    because the full text still failed the filters. Either way a refetch would
    burn the per-run cap that the backlog behind it needs.
    """
    row = conn.execute(
        "SELECT attempted_at FROM enrich_attempts WHERE source = ? AND external_id = ?",
        (job.source, job.external_id),
    ).fetchone()
    if not row:
        return False
    attempted = datetime.fromisoformat(row[0])
    return datetime.now(timezone.utc) - attempted < RETRY_FAILED_AFTER


def _record_attempt(conn: sqlite3.Connection, job: Job, ok: bool) -> None:
    conn.execute(
        """
        INSERT INTO enrich_attempts (source, external_id, attempted_at, ok)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(source, external_id) DO UPDATE SET
            attempted_at = excluded.attempted_at, ok = excluded.ok
        """,
        (job.source, job.external_id, datetime.now(timezone.utc).isoformat(timespec="seconds"), int(ok)),
    )


def backfill_stored(
    conn: sqlite3.Connection,
    *,
    should_fetch: Callable[[Job], bool] | None = None,
    limit: int | None = None,
    **kwargs: Any,
) -> Counter:
    """Enrich jobs already in the DB that still hold only a snippet.

    The scrape-time step only sees listings the APIs return that run; this
    catches up rows stored before enrichment existed, and listings the
    per-run cap pushed back. Newest first. Attempts are recorded, so a dead
    link is retried only after RETRY_FAILED_AFTER.
    """
    rows = conn.execute(
        """
        SELECT source, external_id, title, company, location, description, url
        FROM jobs WHERE length(description) < ? AND url != ''
        ORDER BY last_seen DESC
        """,
        (SNIPPET_MAX_CHARS,),
    ).fetchall()
    jobs = [Job(*row) for row in rows]
    jobs = [j for j in jobs if needs_enrichment(j)]
    if limit is not None:
        jobs = jobs[:limit]
    stats = enrich_descriptions(jobs, conn=conn, should_fetch=should_fetch, **kwargs)
    for job in jobs:
        if len(job.description) >= SNIPPET_MAX_CHARS:
            conn.execute(
                """
                UPDATE jobs SET description = ?, years_experience = ?
                WHERE source = ? AND external_id = ? AND length(description) < length(?)
                """,
                (job.description, job.years_experience, job.source, job.external_id, job.description),
            )
    conn.commit()
    return stats
