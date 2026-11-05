"""Jibe (iCIMS Attract) careers-site adapter — Fraser Health and similar.

API: GET https://{host}/api/jobs?page=N&limit=100 returns
`{"jobs": [{"data": {...}}], "totalCount": N}` with the full posting as plain
text split over `description`, `responsibilities` and `qualifications` (some
tenants, e.g. KPMG, send those fields as HTML).
"""

from __future__ import annotations

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

PAGE_SIZE = 100
MAX_PAGES = 30


def _location(data: dict, board: dict) -> str:
    parts = [data.get("city"), data.get("state")]
    loc = ", ".join(p for p in parts if p) or (data.get("full_location") or "")
    return localize(loc, board)


def _text(value: str | None) -> str:
    """Fraser Health sends plain text, KPMG sends HTML."""
    value = value or ""
    return to_markdown(value) if "<" in value else value.strip()


def to_job(data: dict, board: dict) -> Job:
    meta = data.get("meta_data") or {}
    return Job(
        source=f"jibe:{board['slug']}",
        external_id=str(data.get("req_id") or data["slug"]),
        title=data.get("title") or "",
        company=board["name"],
        location=_location(data, board),
        description=join_sections(
            _text(data.get("description")),
            f"Responsibilities\n\n{_text(data['responsibilities'])}" if data.get("responsibilities") else "",
            f"Qualifications\n\n{_text(data['qualifications'])}" if data.get("qualifications") else "",
        ),
        url=meta.get("canonical_url") or f"https://{board['host']}/jobs/{data['slug']}",
        posted_date=data.get("posted_date") or data.get("create_date"),
        raw={k: data.get(k) for k in ("req_id", "employment_type", "categories", "city")},
    )


def parse_page(payload: dict | None, board: dict) -> list[Job]:
    jobs = []
    for row in (payload or {}).get("jobs") or []:
        data = row.get("data") or {}
        if not data.get("slug") and not data.get("req_id"):
            continue
        job = to_job(data, board)
        if location_ok(job.location):
            jobs.append(job)
    return jobs


def _fetch_one(client: httpx.Client, board: dict) -> list[Job]:
    jobs: list[Job] = []
    seen = 0
    for page in range(1, MAX_PAGES + 1):
        payload = get_json(client, f"https://{board['host']}/api/jobs", params={"page": page, "limit": PAGE_SIZE})
        rows = (payload or {}).get("jobs") or []
        jobs.extend(parse_page(payload, board))
        seen += len(rows)
        if len(rows) < PAGE_SIZE or seen >= ((payload or {}).get("totalCount") or 0):
            break
    return jobs


def fetch_jibe_jobs(boards: list, *, client: httpx.Client | None = None) -> list[Job]:
    return fetch_boards("Jibe", boards, _fetch_one, client=client)
