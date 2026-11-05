"""Workable job-board adapter.

API: GET https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true
returns every posting with its full HTML description (overview, requirements
and benefits together). The widget repeats a posting once per location, so
rows are merged by shortcode.
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
    remote_label,
    to_markdown,
)

API_URL = "https://apply.workable.com/api/v1/widget/accounts/{slug}"


def _place(d: dict) -> str:
    return ", ".join(p for p in (d.get("city"), d.get("state") or d.get("region"), d.get("country")) if p)


def parse_board(data: Any, board: dict) -> list[Job]:
    if not isinstance(data, dict):
        return []
    by_code: dict[str, dict] = {}
    places: dict[str, list[str]] = {}
    for post in data.get("jobs") or []:
        code = post.get("shortcode")
        if not code:
            continue
        by_code.setdefault(code, post)
        places.setdefault(code, []).extend(
            [_place(post)] + [_place(loc) for loc in post.get("locations") or [] if not loc.get("hidden")]
        )

    jobs = []
    for code, post in by_code.items():
        location = remote_label(join_locations(*places[code]), bool(post.get("telecommuting")))
        if not location_ok(location):
            continue
        jobs.append(
            Job(
                source=f"workable:{board['slug']}",
                external_id=code,
                title=post.get("title") or "",
                company=board["name"],
                location=location,
                description=to_markdown(post.get("description")),
                url=post.get("url") or post.get("shortlink"),
                posted_date=post.get("published_on") or post.get("created_at"),
                raw={k: post.get(k) for k in ("shortcode", "department", "employment_type", "telecommuting")},
            )
        )
    return jobs


def _fetch_one(client: httpx.Client, board: dict) -> list[Job]:
    data = get_json(client, API_URL.format(slug=board["slug"]), params={"details": "true"})
    return parse_board(data, board)


def fetch_workable_jobs(boards: list, *, client: httpx.Client | None = None) -> list[Job]:
    return fetch_boards("Workable", boards, _fetch_one, client=client)
