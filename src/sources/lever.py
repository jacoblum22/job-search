"""Lever job-board adapter.

API: GET https://api.lever.co/v0/postings/{slug}?mode=json returns a bare
array of postings. The full posting is spread over `description` (opening +
body), `lists[]` (titled bullet sections) and `additional`.
A missing board returns `{"ok": false, ...}` instead of an array.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from src.db import Job
from src.sources.ats_common import (
    fetch_boards,
    get_json,
    join_locations,
    join_sections,
    location_ok,
    remote_label,
    to_markdown,
)

API_URL = "https://api.lever.co/v0/postings/{slug}"


def _description(post: dict) -> str:
    parts = [to_markdown(post.get("description"))]
    for section in post.get("lists") or []:
        body = to_markdown(f"<ul>{section.get('content') or ''}</ul>")
        heading = (section.get("text") or "").strip()
        parts.append(f"## {heading}\n\n{body}" if heading else body)
    parts.append(to_markdown(post.get("additional")))
    return join_sections(*parts)


def _posted(ms: Any) -> str | None:
    if not isinstance(ms, (int, float)):
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC).date().isoformat()


def parse_board(data: Any, board: dict) -> list[Job]:
    if not isinstance(data, list):
        return []
    jobs = []
    for post in data:
        cats = post.get("categories") or {}
        location = join_locations(cats.get("location"), *(cats.get("allLocations") or []))
        location = remote_label(location, post.get("workplaceType") == "remote")
        if not location_ok(location):
            continue
        jobs.append(
            Job(
                source=f"lever:{board['slug']}",
                external_id=post["id"],
                title=post.get("text") or "",
                company=board["name"],
                location=location,
                description=_description(post),
                url=post.get("hostedUrl"),
                posted_date=_posted(post.get("createdAt")),
                raw={k: post.get(k) for k in ("id", "categories", "workplaceType", "salaryRange")},
            )
        )
    return jobs


def _fetch_one(client: httpx.Client, board: dict) -> list[Job]:
    data = get_json(client, API_URL.format(slug=board["slug"]), params={"mode": "json"})
    return parse_board(data, board)


def fetch_lever_jobs(boards: list, *, client: httpx.Client | None = None) -> list[Job]:
    return fetch_boards("Lever", boards, _fetch_one, client=client)
