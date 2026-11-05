"""SmartRecruiters job-board adapter.

List: GET https://api.smartrecruiters.com/v1/companies/{id}/postings (paged,
no description). Detail: GET .../postings/{postingId} carries the full posting
in `jobAd.sections`. Detail calls are spent only on listings in the right
place whose title passes `should_hydrate_record`.
"""

from __future__ import annotations

import logging

import httpx

from src.db import Job
from src.search_match import should_hydrate_record
from src.sources.ats_common import (
    fetch_boards,
    get_json,
    join_sections,
    location_ok,
    remote_label,
    to_markdown,
)

logger = logging.getLogger(__name__)

API_URL = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
PAGE_SIZE = 100
MAX_PAGES = 20
SECTION_ORDER = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")


def location_of(post: dict) -> str:
    loc = post.get("location") or {}
    text = loc.get("fullLocation") or ", ".join(
        p for p in (loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()) if p
    )
    return remote_label(text, bool(loc.get("remote")))


def description_of(detail: dict) -> str:
    sections = ((detail.get("jobAd") or {}).get("sections")) or {}
    parts = []
    for key in SECTION_ORDER:
        sec = sections.get(key) or {}
        body = to_markdown(sec.get("text"))
        if body:
            title = (sec.get("title") or "").strip()
            parts.append(f"## {title}\n\n{body}" if title else body)
    return join_sections(*parts)


def to_job(post: dict, detail: dict | None, board: dict) -> Job:
    detail = detail or {}
    return Job(
        source=f"smartrecruiters:{board['slug']}",
        external_id=str(post["id"]),
        title=post.get("name") or "",
        company=board["name"],
        location=location_of(post),
        description=description_of(detail),
        url=detail.get("postingUrl")
        or f"https://jobs.smartrecruiters.com/{board['slug']}/{post['id']}",
        posted_date=post.get("releasedDate"),
        raw={k: post.get(k) for k in ("id", "refNumber", "function", "experienceLevel", "typeOfEmployment")},
    )


def _list_postings(client: httpx.Client, slug: str) -> list[dict]:
    postings: list[dict] = []
    for page in range(MAX_PAGES):
        data = get_json(
            client, API_URL.format(slug=slug), params={"limit": PAGE_SIZE, "offset": page * PAGE_SIZE}
        )
        if not isinstance(data, dict):
            break
        content = data.get("content") or []
        postings.extend(content)
        if len(content) < PAGE_SIZE or len(postings) >= (data.get("totalFound") or 0):
            break
    return postings


def fetch_smartrecruiters_jobs(
    boards: list, *, search: dict | None = None, client: httpx.Client | None = None
) -> list[Job]:
    def fetch_one(client: httpx.Client, board: dict) -> list[Job]:
        jobs = []
        for post in _list_postings(client, board["slug"]):
            location = location_of(post)
            if not location_ok(location):
                continue
            if search and not should_hydrate_record(
                post.get("name") or "", search, company=board["name"], location=location
            ):
                continue
            detail = get_json(client, f"{API_URL.format(slug=board['slug'])}/{post['id']}")
            jobs.append(to_job(post, detail, board))
        return jobs

    return fetch_boards("SmartRecruiters", boards, fetch_one, client=client)
