"""Greenhouse job-board adapter.

API: GET https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true
returns every open posting with its full description in one request.
`content` is entity-escaped HTML (`&lt;p&gt;`), so it is unescaped first.
"""

from __future__ import annotations

from typing import Any

import httpx

from src.db import Job
from src.sources.ats_common import (
    fetch_boards,
    get_json,
    join_locations,
    location_ok,
    to_markdown,
)

API_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


def _location(post: dict) -> str:
    name = (post.get("location") or {}).get("name")
    if name:
        return name.strip()
    return join_locations(*(o.get("location") or o.get("name") for o in post.get("offices") or []))


def parse_board(data: Any, board: dict) -> list[Job]:
    if not isinstance(data, dict) or "jobs" not in data:
        return []
    jobs = []
    for post in data["jobs"]:
        location = _location(post)
        if not location_ok(location):
            continue
        jobs.append(
            Job(
                source=f"greenhouse:{board['slug']}",
                external_id=str(post["id"]),
                title=post.get("title") or "",
                company=board.get("name") or post.get("company_name") or board["slug"],
                location=location,
                description=to_markdown(post.get("content"), escaped=True),
                url=post.get("absolute_url"),
                posted_date=post.get("first_published") or post.get("updated_at"),
                raw={k: post.get(k) for k in ("id", "requisition_id", "departments", "offices", "updated_at")},
            )
        )
    return jobs


def _fetch_one(client: httpx.Client, board: dict) -> list[Job]:
    data = get_json(client, API_URL.format(slug=board["slug"]), params={"content": "true"})
    return parse_board(data, board)


def fetch_greenhouse_jobs(boards: list, *, client: httpx.Client | None = None) -> list[Job]:
    return fetch_boards("Greenhouse", boards, _fetch_one, client=client)
