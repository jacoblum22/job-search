"""Oracle Cloud HCM (Recruiting Candidate Experience) adapter.

The candidate site is a SPA over a public REST API on the tenant's pod host:
  list:   GET https://{host}/hcmRestApi/resources/latest/recruitingCEJobRequisitions
          ?onlyData=true&finder=findReqs;siteNumber={site},limit=25,offset=N,sortBy=POSTING_DATES_DESC
  detail: GET .../recruitingCEJobRequisitionDetails?expand=all&onlyData=true
          &finder=ById;Id="{id}",siteNumber={site}
The detail carries the description, responsibilities and qualifications as HTML.
The pod host is in the careers page's `data-apibaseurl` attribute.
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

LIST_PATH = "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
DETAIL_PATH = "/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails"
PAGE_SIZE = 25
MAX_PAGES = 40


def _location(req: dict, board: dict) -> str:
    secondary = [s.get("Name") for s in req.get("secondaryLocations") or [] if isinstance(s, dict)]
    loc = join_locations(req.get("PrimaryLocation"), *secondary)
    if "remote" in str(req.get("WorkplaceTypeCode") or req.get("WorkplaceType") or "").lower():
        loc = f"Remote - {loc}" if loc else "Remote"
    return localize(loc, board)


def description_of(detail: dict) -> str:
    return join_sections(
        to_markdown(detail.get("ExternalDescriptionStr")),
        to_markdown(detail.get("ExternalResponsibilitiesStr")),
        to_markdown(detail.get("ExternalQualificationsStr")),
        to_markdown(detail.get("CorporateDescriptionStr")),
    )


def job_url(board: dict, req_id: str) -> str:
    template = board.get("job_url") or "https://{host}/hcmUI/CandidateExperience/en/sites/{site}/job/{id}"
    return template.format(host=board["host"], site=board["site"], id=req_id)


def to_job(req: dict, detail: dict | None, board: dict) -> Job:
    detail = detail or {}
    return Job(
        source=f"oracle:{board['slug']}",
        external_id=str(req["Id"]),
        title=req.get("Title") or "",
        company=board["name"],
        location=_location(req, board),
        description=description_of(detail) or (req.get("ShortDescriptionStr") or ""),
        url=job_url(board, str(req["Id"])),
        posted_date=req.get("PostedDate"),
        raw={k: req.get(k) for k in ("Id", "PrimaryLocation", "WorkplaceType", "JobFamily")},
    )


def _list(client: httpx.Client, board: dict) -> list[dict]:
    reqs: list[dict] = []
    for page in range(MAX_PAGES):
        finder = (
            f"findReqs;siteNumber={board['site']},limit={PAGE_SIZE},"
            f"offset={page * PAGE_SIZE},sortBy=POSTING_DATES_DESC"
        )
        data = get_json(
            client,
            f"https://{board['host']}{LIST_PATH}",
            params={"onlyData": "true", "expand": "requisitionList.secondaryLocations", "finder": finder},
        )
        items = (data or {}).get("items") or []
        if not items:
            break
        batch = items[0].get("requisitionList") or []
        reqs.extend(batch)
        if len(batch) < PAGE_SIZE or len(reqs) >= (items[0].get("TotalJobsCount") or 0):
            break
    return reqs


def _detail(client: httpx.Client, board: dict, req_id: str) -> dict | None:
    data = get_json(
        client,
        f"https://{board['host']}{DETAIL_PATH}",
        params={
            "expand": "all",
            "onlyData": "true",
            "finder": f'ById;Id="{req_id}",siteNumber={board["site"]}',
        },
    )
    items = (data or {}).get("items") or []
    return items[0] if items else None


def fetch_oracle_jobs(
    boards: list, *, search: dict | None = None, client: httpx.Client | None = None
) -> list[Job]:
    def fetch_one(client: httpx.Client, board: dict) -> list[Job]:
        jobs = []
        for req in _list(client, board):
            location = _location(req, board)
            if not location_ok(location):
                continue
            if search and not should_hydrate_record(
                req.get("Title") or "", search, company=board["name"], location=location
            ):
                continue
            jobs.append(to_job(req, _detail(client, board, str(req["Id"])), board))
        return jobs

    return fetch_boards("Oracle HCM", boards, fetch_one, client=client)
