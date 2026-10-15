"""UKG Pro (UltiPro) Recruiting adapter (Vancity, Nature's Path, MDA, Indochino...).

List:   POST https://{host}/{tenant}/JobBoard/{guid}/JobBoardView/LoadSearchResults
        JSON body `{"opportunitySearch": {"Top": 50, "Skip": N, ...}}` ->
        `{"opportunities": [{Id, Title, Locations[].Address{City, State.Code}, PostedDate, BriefDescription}], "totalCount": N}`
Detail: GET https://{host}/{tenant}/JobBoard/{guid}/OpportunityDetail?opportunityId={Id}
        (page script `CandidateOpportunityDetail({...})` holds the full HTML Description)
The list call is POST-only and could not be exercised from the build sandbox;
the request shape follows what the board's own JavaScript sends.
"""

from __future__ import annotations

import json

import httpx

from src.db import Job
from src.search_match import should_hydrate_record
from src.sources.ats_common import (
    fetch_boards,
    get_text,
    join_locations,
    localize,
    location_ok,
    post_json,
    to_markdown,
)

PAGE_SIZE = 50
MAX_PAGES = 20
_DETAIL_MARKER = "CandidateOpportunityDetail("


def _base(board: dict) -> str:
    return f"https://{board.get('host', 'recruiting.ultipro.com')}/{board['tenant']}/JobBoard/{board['guid']}"


def search_body(skip: int) -> dict:
    return {
        "opportunitySearch": {
            "Top": PAGE_SIZE,
            "Skip": skip,
            "QueryString": "",
            "OrderBy": [{"Value": "postedDateDesc", "PropertyName": "PostedDate", "Ascending": False}],
            "Filters": [
                {"t": "TermsSearchFilterDto", "fieldName": 4, "extra": None, "values": []},
                {"t": "TermsSearchFilterDto", "fieldName": 5, "extra": None, "values": []},
                {"t": "TermsSearchFilterDto", "fieldName": 6, "extra": None, "values": []},
            ],
        },
        "matchCriteria": {
            "PreferredJobs": [],
            "Educations": [],
            "LicenseAndCertifications": [],
            "Skills": [],
            "hasNoLicenses": False,
            "SkippedSkills": [],
        },
    }


def location_of(opp: dict) -> str:
    places = []
    for loc in opp.get("Locations") or []:
        addr = loc.get("Address") or {}
        state = (addr.get("State") or {}).get("Code")
        place = ", ".join(p for p in (addr.get("City"), state) if p)
        places.append(place or loc.get("LocalizedName") or "")
    loc = join_locations(*places)
    if str(opp.get("JobLocationType")) == "3":  # fully remote
        loc = f"Remote - {loc}" if loc else "Remote"
    return loc


def parse_detail(page: str | None) -> dict:
    if not page or _DETAIL_MARKER not in page:
        return {}
    start = page.index(_DETAIL_MARKER) + len(_DETAIL_MARKER)
    try:
        data, _ = json.JSONDecoder().raw_decode(page[start:])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def to_job(opp: dict, detail: dict, board: dict) -> Job:
    merged = {**opp, **detail}
    return Job(
        source=f"ukg:{board['slug']}",
        external_id=str(opp["Id"]),
        title=merged.get("Title") or "",
        company=board["name"],
        location=localize(location_of(merged), board),
        description=to_markdown(detail.get("Description")) or (opp.get("BriefDescription") or ""),
        url=f"{_base(board)}/OpportunityDetail?opportunityId={opp['Id']}",
        posted_date=(merged.get("PostedDate") or "")[:10] or None,
        raw={k: merged.get(k) for k in ("RequisitionNumber", "JobCategoryName", "FullTime", "JobLocationType")},
    )


def fetch_ukg_jobs(boards: list, *, search: dict | None = None, client: httpx.Client | None = None) -> list[Job]:
    def fetch_one(client: httpx.Client, board: dict) -> list[Job]:
        opps: list[dict] = []
        for page in range(MAX_PAGES):
            data = post_json(client, f"{_base(board)}/JobBoardView/LoadSearchResults", search_body(page * PAGE_SIZE))
            batch = (data or {}).get("opportunities") or []
            opps.extend(batch)
            if len(batch) < PAGE_SIZE or len(opps) >= ((data or {}).get("totalCount") or 0):
                break
        jobs = []
        for opp in opps:
            location = localize(location_of(opp), board)
            if not location_ok(location):
                continue
            if search and not should_hydrate_record(opp.get("Title") or "", search, company=board["name"], location=location):
                continue
            detail = parse_detail(get_text(client, f"{_base(board)}/OpportunityDetail", params={"opportunityId": opp["Id"]}))
            jobs.append(to_job(opp, detail, board))
        return jobs

    return fetch_boards("UKG", boards, fetch_one, client=client)
