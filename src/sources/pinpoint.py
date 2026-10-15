"""Pinpoint careers adapter (Article, Photonic, Eventbase...).

API: GET https://{host}/postings.json -> {"data": [...]} with the full posting
split over description, key_responsibilities, skills_knowledge_expertise and
benefits (HTML, each with a *_header). `host` is {slug}.pinpointhq.com or the
company's own careers domain.
"""

from __future__ import annotations

from typing import Any

import httpx

from src.db import Job
from src.sources.ats_common import (
    fetch_boards,
    get_json,
    join_sections,
    localize,
    location_ok,
    to_markdown,
)

SECTIONS = ("key_responsibilities", "skills_knowledge_expertise", "benefits")


def _host(board: dict) -> str:
    return board.get("host") or f"{board['slug']}.pinpointhq.com"


def location_of(post: dict) -> str:
    loc = post.get("location") or {}
    text = ", ".join(p for p in (loc.get("city") or loc.get("name"), loc.get("province")) if p)
    if (post.get("workplace_type") or "") == "remote":
        text = f"Remote - {text}" if text else "Remote"
    return text


def description_of(post: dict) -> str:
    parts = [to_markdown(post.get("description"))]
    for key in SECTIONS:
        body = to_markdown(post.get(key))
        if body:
            heading = post.get(f"{key}_header")
            parts.append(f"## {heading}\n\n{body}" if heading else body)
    if post.get("compensation_visible") and post.get("compensation"):
        parts.append(f"**Compensation:** {post['compensation']}")
    return join_sections(*parts)


def parse_postings(data: Any, board: dict) -> list[Job]:
    jobs = []
    for post in (data or {}).get("data") or [] if isinstance(data, dict) else []:
        location = localize(location_of(post), board)
        if not location_ok(location):
            continue
        jobs.append(
            Job(
                source=f"pinpoint:{board['slug']}",
                external_id=str(post["id"]),
                title=post.get("title") or "",
                company=board["name"],
                location=location,
                description=description_of(post),
                url=post.get("url") or f"https://{_host(board)}{post.get('path', '')}",
                posted_date=None,
                raw={k: post.get(k) for k in ("employment_type", "workplace_type", "compensation")},
            )
        )
    return jobs


def _fetch_one(client: httpx.Client, board: dict) -> list[Job]:
    return parse_postings(get_json(client, f"https://{_host(board)}/postings.json"), board)


def fetch_pinpoint_jobs(boards: list, *, client: httpx.Client | None = None) -> list[Job]:
    return fetch_boards("Pinpoint", boards, _fetch_one, client=client)
