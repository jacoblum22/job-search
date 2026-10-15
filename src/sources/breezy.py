"""Breezy HR careers adapter.

List:   GET https://{slug}.breezy.hr/json -> [{id, friendly_id, name, url, published_date, location{city, name, is_remote, country}}]
Detail: GET {url} (job page with schema.org JobPosting JSON-LD holding the full description)
"""

from __future__ import annotations

import httpx

from src.db import Job
from src.search_match import should_hydrate_record
from src.sources.ats_common import (
    fetch_boards,
    get_json,
    get_text,
    localize,
    location_ok,
    to_markdown,
)
from src.sources.jsonld import find_job_postings


def location_of(post: dict) -> str:
    loc = post.get("location") or {}
    country = (loc.get("country") or {}).get("name") if isinstance(loc.get("country"), dict) else loc.get("country")
    text = loc.get("name") or ", ".join(p for p in (loc.get("city"), country) if p)
    if loc.get("is_remote"):
        text = f"Remote - {text}" if text else "Remote"
    return text


def fetch_breezy_jobs(boards: list, *, search: dict | None = None, client: httpx.Client | None = None) -> list[Job]:
    def fetch_one(client: httpx.Client, board: dict) -> list[Job]:
        posts = get_json(client, f"https://{board['slug']}.breezy.hr/json")
        jobs = []
        for post in posts if isinstance(posts, list) else []:
            location = localize(location_of(post), board)
            if not location_ok(location):
                continue
            if search and not should_hydrate_record(post.get("name") or "", search, company=board["name"], location=location):
                continue
            postings = find_job_postings(get_text(client, post["url"]) or "")
            jobs.append(
                Job(
                    source=f"breezy:{board['slug']}",
                    external_id=str(post["id"]),
                    title=post.get("name") or "",
                    company=board["name"],
                    location=location,
                    description=to_markdown(postings[0].get("description")) if postings else "",
                    url=post["url"],
                    posted_date=(post.get("published_date") or "")[:10] or None,
                    raw={"friendly_id": post.get("friendly_id"), "type": post.get("type")},
                )
            )
        return jobs

    return fetch_boards("Breezy", boards, fetch_one, client=client)
