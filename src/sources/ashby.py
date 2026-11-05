"""Ashby job-board adapter.

API: GET https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true
returns every listed posting with `descriptionHtml` in one request.
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

API_URL = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def _location(post: dict) -> str:
    secondary = [s.get("location") for s in post.get("secondaryLocations") or [] if isinstance(s, dict)]
    location = join_locations(post.get("location"), *secondary)
    return remote_label(location, bool(post.get("isRemote")) or post.get("workplaceType") == "Remote")


def parse_board(data: Any, board: dict) -> list[Job]:
    if not isinstance(data, dict):
        return []
    jobs = []
    for post in data.get("jobs") or []:
        if post.get("isListed") is False:
            continue
        location = _location(post)
        if not location_ok(location):
            continue
        comp = (post.get("compensation") or {}).get("compensationTierSummary")
        description = to_markdown(post.get("descriptionHtml")) or (post.get("descriptionPlain") or "")
        if comp:
            description = f"{description}\n\n**Compensation:** {comp}"
        jobs.append(
            Job(
                source=f"ashby:{board['slug']}",
                external_id=post["id"],
                title=post.get("title") or "",
                company=board["name"],
                location=location,
                description=description,
                url=post.get("jobUrl"),
                posted_date=post.get("publishedAt"),
                raw={k: post.get(k) for k in ("id", "department", "team", "employmentType", "workplaceType")},
            )
        )
    return jobs


def _fetch_one(client: httpx.Client, board: dict) -> list[Job]:
    data = get_json(
        client, API_URL.format(slug=board["slug"]), params={"includeCompensation": "true"}
    )
    return parse_board(data, board)


def fetch_ashby_jobs(boards: list, *, client: httpx.Client | None = None) -> list[Job]:
    return fetch_boards("Ashby", boards, _fetch_one, client=client)
