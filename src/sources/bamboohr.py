"""BambooHR careers adapter.

List:   GET https://{slug}.bamboohr.com/careers/list    -> {"result": [{id, jobOpeningName, location{city,state}, isRemote, ...}]}
Detail: GET https://{slug}.bamboohr.com/careers/{id}/detail -> {"result": {"jobOpening": {description (HTML), datePosted, ...}}}
"""

from __future__ import annotations

import httpx

from src.db import Job
from src.search_match import should_hydrate_record
from src.sources.ats_common import (
    fetch_boards,
    get_json,
    localize,
    location_ok,
    to_markdown,
)


def _place(loc: dict | None) -> str:
    loc = loc or {}
    return ", ".join(p for p in (loc.get("city"), loc.get("state") or loc.get("province"), loc.get("addressCountry")) if p)


def location_of(row: dict) -> str:
    loc = _place(row.get("location")) or _place(row.get("atsLocation"))
    if row.get("isRemote") or str(row.get("locationType")) == "1":
        loc = f"Remote - {loc}" if loc else "Remote"
    return loc


def to_job(row: dict, detail: dict, board: dict) -> Job:
    opening = ((detail or {}).get("result") or {}).get("jobOpening") or {}
    return Job(
        source=f"bamboohr:{board['slug']}",
        external_id=str(row["id"]),
        title=row.get("jobOpeningName") or opening.get("jobOpeningName") or "",
        company=board["name"],
        location=localize(location_of({**row, **{k: v for k, v in opening.items() if k == "location" and v}}), board),
        description=to_markdown(opening.get("description")),
        url=opening.get("jobOpeningShareUrl") or f"https://{board['slug']}.bamboohr.com/careers/{row['id']}",
        posted_date=opening.get("datePosted"),
        raw={k: row.get(k) for k in ("departmentLabel", "employmentStatusLabel", "locationType")},
    )


def fetch_bamboohr_jobs(boards: list, *, search: dict | None = None, client: httpx.Client | None = None) -> list[Job]:
    def fetch_one(client: httpx.Client, board: dict) -> list[Job]:
        base = f"https://{board['slug']}.bamboohr.com/careers"
        jobs = []
        for row in (get_json(client, f"{base}/list") or {}).get("result") or []:
            location = localize(location_of(row), board)
            if not location_ok(location):
                continue
            title = row.get("jobOpeningName") or ""
            if search and not should_hydrate_record(title, search, company=board["name"], location=location):
                continue
            jobs.append(to_job(row, get_json(client, f"{base}/{row['id']}/detail"), board))
        return jobs

    return fetch_boards("BambooHR", boards, fetch_one, client=client)
