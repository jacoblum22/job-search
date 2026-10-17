"""Dayforce candidate-portal adapter (Odlum Brown, Westland, LifeLabs, Kardium...).

List:   POST https://jobs.dayforcehcm.com/api/geo/{client}/jobposting/search
        JSON `{clientNamespace, jobBoardCode, cultureCode, paginationStart, ...}`
        -> `{"jobPostings": [...], "maxCount": N}`, 25 per page.
        Needs an `X-CSRF-TOKEN` header from GET /api/auth/csrf plus the
        next-auth cookie that call sets (the client keeps it); without them
        the POST is a bare 403.
Detail: GET https://jobs.dayforcehcm.com/{culture}/{client}/{board}/jobs/{jobPostingId}
        (Next.js page; `__NEXT_DATA__` holds the posting with
        jobPostingContent.{jobDescriptionHeader, jobDescription, jobDescriptionFooter}).
The request shape follows the portal's own JavaScript (verified live Oct 2026).
"""

from __future__ import annotations

import json
import re

import httpx

from src.db import Job
from src.search_match import should_hydrate_record
from src.sources.ats_common import (
    fetch_boards,
    get_json,
    get_text,
    join_locations,
    join_sections,
    localize,
    location_ok,
    post_json,
    to_markdown,
)

HOST = "https://jobs.dayforcehcm.com"
PAGE_SIZE = 25
MAX_PAGES = 20
_NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def parse_detail(page: str | None) -> dict:
    """The posting object (the dict carrying jobPostingContent) from __NEXT_DATA__."""
    m = _NEXT_RE.search(page or "")
    if not m:
        return {}
    try:
        data = json.loads(m.group(1))
    except ValueError:
        return {}
    return next((n for n in _walk(data) if "jobPostingContent" in n), {})


def location_of(posting: dict) -> str:
    places = []
    for loc in posting.get("postingLocations") or []:
        place = ", ".join(p for p in (loc.get("cityName"), loc.get("stateCode")) if p)
        places.append(place or loc.get("formattedAddress") or "")
    loc = join_locations(*places)
    if posting.get("hasVirtualLocation"):
        loc = f"Remote - {loc}" if loc else "Remote - Canada"
    return loc


def description_of(posting: dict) -> str:
    content = posting.get("jobPostingContent") or {}
    return join_sections(
        to_markdown(content.get("jobDescriptionHeader")),
        to_markdown(content.get("jobDescription")),
        to_markdown(content.get("jobDescriptionFooter")),
    )


def job_url(board: dict, posting_id) -> str:
    return f"{HOST}/{board.get('culture', 'en-US')}/{board['client']}/{board['board']}/jobs/{posting_id}"


def to_job(summary: dict, detail: dict, board: dict) -> Job:
    merged = {**summary, **detail}
    pid = merged["jobPostingId"]
    return Job(
        source=f"dayforce:{board['slug']}",
        external_id=str(pid),
        title=merged.get("jobTitle") or "",
        company=board["name"],
        location=localize(location_of(merged), board),
        description=description_of(detail) or to_markdown(summary.get("jobDescription")),
        url=job_url(board, pid),
        posted_date=(merged.get("postingStartTimestampUTC") or "")[:10] or None,
        raw={k: merged.get(k) for k in ("jobReqId", "postingExpiryTimestampUTC")},
    )


def csrf_headers(client: httpx.Client) -> dict:
    token = (get_json(client, f"{HOST}/api/auth/csrf") or {}).get("csrfToken")
    return {"X-CSRF-TOKEN": token} if token else {}


def fetch_dayforce_jobs(boards: list, *, search: dict | None = None, client: httpx.Client | None = None) -> list[Job]:
    def fetch_one(client: httpx.Client, board: dict) -> list[Job]:
        headers = csrf_headers(client)
        postings: list[dict] = []
        for page in range(MAX_PAGES):
            body = {
                "clientNamespace": board["client"],
                "jobBoardCode": board["board"],
                "cultureCode": board.get("culture", "en-US"),
                "distanceUnit": 0,
                "paginationStart": page * PAGE_SIZE,
            }
            data = post_json(client, f"{HOST}/api/geo/{board['client']}/jobposting/search", body, headers=headers)
            batch = (data or {}).get("jobPostings") or []
            postings.extend(batch)
            if len(batch) < PAGE_SIZE or len(postings) >= ((data or {}).get("maxCount") or 0):
                break
        jobs = []
        for summary in postings:
            if "jobPostingId" not in summary:
                continue
            location = localize(location_of(summary), board)
            if summary.get("postingLocations") and not location_ok(location):
                continue
            title = summary.get("jobTitle") or ""
            if search and not should_hydrate_record(title, search, company=board["name"], location=location):
                continue
            detail = parse_detail(get_text(client, job_url(board, summary["jobPostingId"])))
            job = to_job(summary, detail, board)
            if location_ok(job.location):
                jobs.append(job)
        return jobs

    # One board at a time: jobs.dayforcehcm.com answered 403 to 5 of 18 boards
    # when they were fetched in parallel (Oct 17 2026 test run).
    return fetch_boards("Dayforce", boards, fetch_one, client=client, workers=1)
