"""ADP Workforce Now career-center adapter.

List:   GET https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/
            job-requisitions?cid={cid}&ccId={ccId}&lang=en_CA&$top=100&$skip=N
Detail: GET .../job-requisitions/{itemID}?cid=...   (`requisitionDescription`, full HTML)
Boards are configured by `cid` (from the careers URL), optional `ccId` and `lang`.
"""

from __future__ import annotations

import httpx

from src.db import Job
from src.search_match import should_hydrate_record
from src.sources.ats_common import (
    fetch_boards,
    get_json,
    join_locations,
    localize,
    location_ok,
    to_markdown,
)

API = "https://workforcenow.adp.com/mascsr/default/careercenter/public/events/staffing/v1/job-requisitions"
PUBLIC = "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html"
PAGE_SIZE = 100
MAX_PAGES = 10


def _params(board: dict, **extra) -> dict:
    params = {"cid": board["cid"], "lang": board.get("lang", "en_CA"), **extra}
    if board.get("ccId"):
        params["ccId"] = board["ccId"]
    return params


def _location(req: dict) -> str:
    places = []
    for loc in req.get("requisitionLocations") or []:
        addr = loc.get("address") or {}
        city = addr.get("cityName")
        region = (addr.get("countrySubdivisionLevel1") or {}).get("codeValue")
        place = ", ".join(p for p in (city, region) if p) or ((loc.get("nameCode") or {}).get("shortName") or "").strip()
        places.append(place)
    return join_locations(*places)


def _external_id(req: dict) -> str | None:
    for field in (req.get("customFieldGroup") or {}).get("stringFields") or []:
        if (field.get("nameCode") or {}).get("codeValue") == "ExternalJobID":
            return field.get("stringValue")
    return None


def to_job(req: dict, detail: dict | None, board: dict) -> Job:
    params = _params(board)
    ext = _external_id(req)
    url = str(httpx.URL(PUBLIC, params={**params, **({"jobId": ext} if ext else {})}))
    return Job(
        source=f"adp:{board['slug']}",
        external_id=str(req["itemID"]),
        title=req.get("requisitionTitle") or "",
        company=board["name"],
        location=localize(_location(req), board),
        description=to_markdown((detail or {}).get("requisitionDescription")),
        url=url,
        posted_date=(req.get("postDate") or "")[:10] or None,
        raw={"itemID": req["itemID"], "clientRequisitionID": req.get("clientRequisitionID"), "payGradeRange": req.get("payGradeRange")},
    )


def fetch_adp_jobs(boards: list, *, search: dict | None = None, client: httpx.Client | None = None) -> list[Job]:
    def fetch_one(client: httpx.Client, board: dict) -> list[Job]:
        reqs: list[dict] = []
        for page in range(MAX_PAGES):
            data = get_json(client, API, params=_params(board, **{"$top": PAGE_SIZE, "$skip": page * PAGE_SIZE}))
            batch = (data or {}).get("jobRequisitions") or []
            reqs.extend(batch)
            total = ((data or {}).get("meta") or {}).get("totalNumber") or 0
            if len(batch) < PAGE_SIZE or len(reqs) >= total:
                break
        jobs = []
        for req in reqs:
            location = localize(_location(req), board)
            if not location_ok(location):
                continue
            title = req.get("requisitionTitle") or ""
            if search and not should_hydrate_record(title, search, company=board["name"], location=location):
                continue
            detail = get_json(client, f"{API}/{req['itemID']}", params=_params(board))
            jobs.append(to_job(req, detail, board))
        return jobs

    return fetch_boards("ADP", boards, fetch_one, client=client)
