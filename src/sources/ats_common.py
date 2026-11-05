"""Shared helpers for the public applicant-tracking-system (ATS) job boards.

Greenhouse, Lever, Ashby, SmartRecruiters and Workable all expose an
unauthenticated JSON feed per company. Each adapter in this package turns one
company's feed into `Job` records with the full posting as markdown, so these
sources never need the snippet enrichment step in src/enrich.py.

Boards are configured in config/ats_boards.yaml as `{name, slug}` entries
(a bare string is shorthand for `slug` with the name defaulting to it).
"""

from __future__ import annotations

import html
import logging
import re
from collections.abc import Callable, Iterable
from typing import Any

import httpx

from src.concurrency import parallel_map
from src.db import Job
from src.http_retry import request_with_retry
from src.location_filter import is_remote, is_vancouver_area
from src.parser import html_to_markdown

logger = logging.getLogger(__name__)

USER_AGENT = "job-search-aggregator/1.0 (+https://jacoblum.com)"
DEFAULT_TIMEOUT = 30.0
# Boards of one platform fetched at once. Most platforms serve every company
# from one API host, so this is also the most requests that host sees at a time.
# scripts/aggregate.py overrides it from settings.yaml `concurrency.board_workers`.
BOARD_WORKERS = 6


def make_client() -> httpx.Client:
    return httpx.Client(
        timeout=DEFAULT_TIMEOUT,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        follow_redirects=True,
    )


def normalize_boards(boards: Iterable[Any] | None) -> list[dict]:
    """Accept `"slug"` or `{"slug": ..., "name": ..., "enabled": ...}` entries."""
    out = []
    for b in boards or []:
        if isinstance(b, str):
            b = {"slug": b}
        if not isinstance(b, dict) or not b.get("slug"):
            logger.warning("Ignoring malformed ATS board entry: %r", b)
            continue
        if b.get("enabled", True) is False:
            continue
        out.append({**b, "name": b.get("name") or b["slug"]})
    return out


def get_json(client: httpx.Client, url: str, **kwargs: Any) -> Any | None:
    """GET a JSON document. Returns None (and logs) on 404 or other errors."""
    resp = request_with_retry(client, "GET", url, **kwargs)
    if resp.status_code == 404:
        logger.warning("Board not found (404): %s", url)
        return None
    if resp.status_code >= 400:
        logger.warning("HTTP %d from %s", resp.status_code, url)
        return None
    try:
        return resp.json()
    except ValueError:
        logger.warning("Non-JSON response from %s", url)
        return None


def get_text(client: httpx.Client, url: str, **kwargs: Any) -> str | None:
    """GET an HTML/XML page. Returns None (and logs) on HTTP errors."""
    resp = request_with_retry(client, "GET", url, **kwargs)
    if resp.status_code >= 400:
        logger.warning("HTTP %d from %s", resp.status_code, url)
        return None
    return resp.text


def post_json(client: httpx.Client, url: str, payload: Any, **kwargs: Any) -> Any | None:
    """POST a JSON body and decode the JSON reply. None (and logs) on errors."""
    resp = request_with_retry(client, "POST", url, json=payload, **kwargs)
    if resp.status_code >= 400:
        logger.warning("HTTP %d from POST %s", resp.status_code, url)
        return None
    try:
        return resp.json()
    except ValueError:
        logger.warning("Non-JSON response from POST %s", url)
        return None


def to_markdown(fragment: str | None, *, escaped: bool = False) -> str:
    """HTML (optionally entity-escaped, as Greenhouse sends it) -> markdown."""
    if not fragment:
        return ""
    if escaped:
        fragment = html.unescape(fragment)
    return html_to_markdown(fragment)


def join_sections(*parts: str) -> str:
    return "\n\n".join(p.strip() for p in parts if p and p.strip())


def join_locations(*locs: Any) -> str:
    """Join location strings, dropping blanks and exact duplicates."""
    seen: list[str] = []
    for loc in locs:
        loc = (loc or "").strip() if isinstance(loc, str) else ""
        if loc and loc not in seen:
            seen.append(loc)
    return "; ".join(seen)


def remote_label(location: str, is_remote_flag: bool) -> str:
    """Prefix 'Remote - ' so src.location_filter.is_remote recognises it."""
    if is_remote_flag and "remote" not in location.lower():
        return f"Remote - {location}" if location else "Remote"
    return location


# Remote postings from global boards name the region they hire in. Only these
# (or no region at all) are open to someone in Canada.
_REMOTE_OK_REGIONS = ("canada", "north america", "americas", "worldwide", "anywhere", "global")
# Shorthand remote boards use for the same regions ("USA, CAN, MEX", "AMER",
# "NAMER") and Canadian provinces ("Remote - Ontario", "Remote BC").
_REMOTE_OK_WORDS = re.compile(
    r"\b(?:can|n?amer|noram|british columbia|bc|alberta|ontario|quebec|québec|manitoba|"
    r"saskatchewan|nova scotia|new brunswick|newfoundland|prince edward island)\b",
    re.IGNORECASE,
)


def location_ok(location: str) -> bool:
    """Vancouver-area, or remote and open to Canada.

    Stricter than src.location_filter.classify_location on purpose: global
    company boards list "Remote - Sydney, Australia" or "Remote - Germany",
    which is_remote() alone would accept. The company name is not consulted
    either, so a board named after a Vancouver company still drops its
    Toronto/US postings.
    """
    if is_vancouver_area(location):
        return True
    if not is_remote(location):
        return False
    loc = location.lower()
    region = re.sub(r"\bremote\b|[-–(),;:/]", " ", loc).strip()
    return not region or any(r in loc for r in _REMOTE_OK_REGIONS) or bool(_REMOTE_OK_WORDS.search(loc))


def localize(location: str, board: dict) -> str:
    """Pin region-wide postings to the employer's area.

    Local employers post some jobs as "Various Locations, BC" or just their
    own name ("Fraser Health"). A board can list such strings under
    `vague_locations`; matching postings (or ones with no location) get the
    board's `fallback_location` appended so the location filter can place them.
    """
    fallback = board.get("fallback_location")
    if not fallback:
        return location
    vague = [v.lower() for v in board.get("vague_locations") or []]
    loc = (location or "").lower()
    if not loc or any(v in loc for v in vague):
        return f"{location} ({fallback})" if location else fallback
    return location


def fetch_boards(
    platform: str,
    boards: Iterable[Any] | None,
    fetch_one: Callable[[httpx.Client, dict], list[Job]],
    *,
    client: httpx.Client | None = None,
    workers: int | None = None,
) -> list[Job]:
    """Run `fetch_one` for each board, several at a time; one bad board never
    sinks the rest. Results keep the board-list order."""
    own_client = client is None
    client = client or make_client()

    def one(board: dict) -> list[Job]:
        try:
            found = fetch_one(client, board)
        except Exception:
            logger.exception("%s board %s failed — continuing", platform, board["slug"])
            return []
        logger.info("%s %s: %d relevant job(s)", platform, board["name"], len(found))
        return found

    try:
        per_board = parallel_map(one, normalize_boards(boards), BOARD_WORKERS if workers is None else workers)
    finally:
        if own_client:
            client.close()
    return [job for found in per_board for job in found]
