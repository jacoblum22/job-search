"""Fill in full descriptions for listings that only came with a snippet.

Adzuna's API returns ~500-char snippets and CareerJet ~300. Each listing's
own `url` (Adzuna's tracked `redirect_url`) opens the full posting, which
almost always carries a schema.org JobPosting JSON-LD block (39/40 of the
top Adzuna matches in testing, 2026-10-15). We follow that link, pull the description, and keep it if it's
longer than what we have.

Note: Adzuna's bare `/details/{id}` and `/land/ad/{id}` paths return 403 from
CloudFront; only the tracked redirect_url (with its utm params) is served.

Rate-limited per host, retried on transient errors, and every failure is
logged and skipped — enrichment never aborts a scrape. Attempts are recorded
in `enrich_attempts` so the 10-minute scheduled runs don't refetch the same
dead link over and over.
"""

from __future__ import annotations

import html
import json
import logging
import re
import sqlite3
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from src.db import Job
from src.http_retry import request_with_retry
from src.parser import html_to_markdown

logger = logging.getLogger(__name__)

# Descriptions shorter than this are treated as snippets worth expanding.
SNIPPET_MAX_CHARS = 1000
# A fetched description must be at least this long to count — guards against
# grabbing a cookie banner or "job no longer available" stub.
MIN_FULL_CHARS = 600
DEFAULT_HOST_PAUSE = 1.0
DEFAULT_MAX_FETCHES = 150
RETRY_FAILED_AFTER = timedelta(days=3)

# Pages where a plain fetch never yields the posting: login-walled boards, and
# CareerJet, whose jobviewtrack links mostly 404 and otherwise land on a
# careerjet.ca shell with no description (0/25 in testing, 2026-10-15).
SKIP_HOSTS = ("linkedin.com", "indeed.com", "glassdoor.", "jobviewtrack.com", "careerjet.")

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
) -> Counter:
    """Replace snippet descriptions in-place with the full posting text.

    `should_fetch` narrows which listings are worth a request (e.g. title
    relevance). With `conn`, listings already stored with a full description
    reuse it, and recent failed attempts are not retried.
    Returns counts: enriched / failed / reused / skipped_recent / capped.
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
    last_hit: dict[str, float] = {}
    fetches = 0
    try:
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
                if _recently_failed(conn, job):
                    stats["skipped_recent"] += 1
                    continue
            if fetches >= max_fetches:
                stats["capped"] += 1
                continue
            fetches += 1
            _throttle(job.url, last_hit, host_pause)
            full = _fetch_description(client, job)
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
    if stats:
        logger.info(
            "Description enrichment: %d enriched, %d failed, %d reused, %d skipped (recent failure), %d over cap",
            stats["enriched"],
            stats["failed"],
            stats["reused"],
            stats["skipped_recent"],
            stats["capped"],
        )
    return stats


def _apply(job: Job, description: str) -> None:
    job.description = description
    job.__post_init__()  # recompute years_experience from the full text


def _throttle(url: str, last_hit: dict[str, float], pause: float) -> None:
    host = urlparse(url).netloc.lower()
    prev = last_hit.get(host)
    if prev is not None and pause > 0:
        wait = pause - (time.monotonic() - prev)
        if wait > 0:
            time.sleep(wait)
    last_hit[host] = time.monotonic()


def _fetch_description(client: httpx.Client, job: Job) -> str:
    try:
        resp = request_with_retry(client, "GET", job.url, retries=3, backoff=2.0)
    except httpx.HTTPError as exc:
        logger.warning("Enrich %s %s: network error %s", job.source, job.external_id, type(exc).__name__)
        return ""
    if resp.status_code != 200:
        logger.warning(
            "Enrich %s %s: HTTP %s from %s",
            job.source,
            job.external_id,
            resp.status_code,
            urlparse(str(resp.url)).netloc,
        )
        return ""
    try:
        text = description_from_html(resp.text)
    except Exception:
        logger.exception("Enrich %s %s: failed to parse page", job.source, job.external_id)
        return ""
    if len(text) < MIN_FULL_CHARS:
        logger.warning(
            "Enrich %s %s: no full description on %s",
            job.source,
            job.external_id,
            urlparse(str(resp.url)).netloc,
        )
        return ""
    return text


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


def _recently_failed(conn: sqlite3.Connection, job: Job) -> bool:
    row = conn.execute(
        "SELECT attempted_at, ok FROM enrich_attempts WHERE source = ? AND external_id = ?",
        (job.source, job.external_id),
    ).fetchone()
    if not row or row[1]:
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
