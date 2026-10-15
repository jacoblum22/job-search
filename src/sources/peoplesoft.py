"""Oracle PeopleSoft Candidate Gateway adapter (TransLink and similar).

List:   GET {base}?Page=HRS_APP_SCHJOB_FL&Action=U&FOCUS=Applicant&SiteId={site}
        (HTML; row fields by element id: SCH_JOB_TITLE$N,
        HRS_APP_JBSCH_I_HRS_JOB_OPENING_ID$N, LOCATION$N, SCH_OPENED$N)
Detail: GET {base}?Page=HRS_APP_JBPST_FL&Action=U&FOCUS=Applicant&SiteId={site}
            &JobOpeningId={id}&PostingSeq=1
        (sections HRS_SCH_WRK_DESCR100$N headings + HRS_SCH_PSTDSC_DESCRLONG$N bodies)
        Postings from another company on the same gateway (TransLink's
        Coast Mountain Bus, BC Rapid Transit) only open under that company's
        SiteId; the board's `company_site_ids` maps COMPANY_DESCR -> SiteId.
Limitation: a plain GET returns only the first page (about 50 postings); later
pages need PeopleSoft's stateful POST round-trips, which this adapter skips.
"""

from __future__ import annotations

import re

import httpx
from bs4 import BeautifulSoup

from src.db import Job
from src.parser import html_to_markdown
from src.search_match import should_hydrate_record
from src.sources.ats_common import (
    fetch_boards,
    get_text,
    join_sections,
    localize,
    location_ok,
)

_ROW_RE = re.compile(r"^SCH_JOB_TITLE\$(\d+)$")


def _text(soup, el_id: str) -> str:
    el = soup.find(id=el_id)
    return el.get_text(" ", strip=True) if el else ""


def parse_list(page: str | None) -> list[dict]:
    if not page:
        return []
    soup = BeautifulSoup(page, "html.parser")
    rows = []
    for el in soup.find_all(id=_ROW_RE):
        n = _ROW_RE.match(el["id"]).group(1)
        job_id = _text(soup, f"HRS_APP_JBSCH_I_HRS_JOB_OPENING_ID${n}")
        if not job_id:
            continue
        rows.append(
            {
                "id": job_id,
                "title": el.get_text(" ", strip=True),
                "location": _text(soup, f"LOCATION${n}"),
                "department": _text(soup, f"HRS_APP_JBSCH_I_HRS_DEPT_DESCR${n}"),
                "company": _text(soup, f"COMPANY_DESCR${n}"),
                "opened": _text(soup, f"SCH_OPENED${n}").replace("/", "-") or None,
            }
        )
    return rows


def parse_detail(page: str | None) -> str:
    if not page:
        return ""
    soup = BeautifulSoup(page, "html.parser")
    parts = []
    for body in soup.find_all(id=re.compile(r"^HRS_SCH_PSTDSC_DESCRLONG\$\d+$")):
        n = body["id"].rsplit("$", 1)[1]
        heading = _text(soup, f"HRS_SCH_WRK_DESCR100${n}")
        text = html_to_markdown(str(body))
        parts.append(f"## {heading}\n\n{text}" if heading else text)
    return join_sections(*parts)


def _url(board: dict, page: str, *, company: str = "", **extra: str) -> tuple[str, dict]:
    site = (board.get("company_site_ids") or {}).get(company, board.get("site_id", 1))
    params = {"Page": page, "Action": "U", "FOCUS": "Applicant", "SiteId": str(site), **extra}
    return board["base_url"], params


def fetch_peoplesoft_jobs(
    boards: list, *, search: dict | None = None, client: httpx.Client | None = None
) -> list[Job]:
    def fetch_one(client: httpx.Client, board: dict) -> list[Job]:
        url, params = _url(board, "HRS_APP_SCHJOB_FL")
        jobs = []
        for row in parse_list(get_text(client, url, params=params)):
            location = localize(row["location"], board)
            if not location_ok(location):
                continue
            if search and not should_hydrate_record(row["title"], search, company=board["name"], location=location):
                continue
            durl, dparams = _url(
                board, "HRS_APP_JBPST_FL", company=row["company"], JobOpeningId=row["id"], PostingSeq="1"
            )
            jobs.append(
                Job(
                    source=f"peoplesoft:{board['slug']}",
                    external_id=row["id"],
                    title=row["title"],
                    company=board["name"],
                    location=location,
                    description=parse_detail(get_text(client, durl, params=dparams)),
                    url=str(httpx.URL(durl, params=dparams)),
                    posted_date=row["opened"],
                    raw={k: row.get(k) for k in ("department", "company", "location")},
                )
            )
        return jobs

    return fetch_boards("PeopleSoft", boards, fetch_one, client=client)
