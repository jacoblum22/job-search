"""Rippling ATS adapter (D-Wave, Zymeworks, Piranha Games...).

List:   GET https://ats.rippling.com/api/v2/board/{slug}/jobs?page=N&pageSize=100
        -> {items: [{id, name, url, locations[{city, stateCode, country, workplaceType}]}], totalPages}
        (one row per job per location, so rows are merged by id)
Detail: GET https://ats.rippling.com/api/v2/board/{slug}/jobs/{id}
        -> {description: {company, role} (HTML), createdOn, workLocations}
"""

from __future__ import annotations

import httpx

from src.db import Job
from src.search_match import should_hydrate_record
from src.sources.ats_common import (
    fetch_boards,
    get_json,
    join_locations,
    join_sections,
    localize,
    location_ok,
    to_markdown,
)

API = "https://ats.rippling.com/api/v2/board/{slug}/jobs"
PAGE_SIZE = 100
MAX_PAGES = 10


def _place(loc: dict) -> str:
    text = ", ".join(p for p in (loc.get("city"), loc.get("stateCode") or loc.get("state")) if p) or loc.get("name") or ""
    if (loc.get("workplaceType") or "").upper() == "REMOTE":
        text = f"Remote - {loc.get('country') or text}".rstrip(" -")
    return text


def merge_rows(items: list[dict]) -> dict[str, dict]:
    jobs: dict[str, dict] = {}
    for item in items:
        job = jobs.setdefault(item["id"], {**item, "places": []})
        job["places"].extend(_place(loc) for loc in item.get("locations") or [])
    return jobs


def fetch_rippling_jobs(boards: list, *, search: dict | None = None, client: httpx.Client | None = None) -> list[Job]:
    def fetch_one(client: httpx.Client, board: dict) -> list[Job]:
        url = API.format(slug=board["slug"])
        items: list[dict] = []
        for page in range(MAX_PAGES):
            data = get_json(client, url, params={"page": page, "pageSize": PAGE_SIZE}) or {}
            items.extend(data.get("items") or [])
            if page + 1 >= (data.get("totalPages") or 0):
                break
        jobs = []
        for job_id, row in merge_rows(items).items():
            location = localize(join_locations(*row["places"]), board)
            if not location_ok(location):
                continue
            if search and not should_hydrate_record(row.get("name") or "", search, company=board["name"], location=location):
                continue
            detail = get_json(client, f"{url}/{job_id}") or {}
            desc = detail.get("description") or {}
            jobs.append(
                Job(
                    source=f"rippling:{board['slug']}",
                    external_id=job_id,
                    title=row.get("name") or "",
                    company=board["name"],
                    location=location,
                    description=join_sections(to_markdown(desc.get("role")), to_markdown(desc.get("company"))),
                    url=row.get("url") or f"https://ats.rippling.com/{board['slug']}/jobs/{job_id}",
                    posted_date=(detail.get("createdOn") or "")[:10] or None,
                    raw={"department": (row.get("department") or {}).get("name")},
                )
            )
        return jobs

    return fetch_boards("Rippling", boards, fetch_one, client=client)
