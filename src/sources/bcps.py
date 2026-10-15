"""BC Public Service job board (hrsmart) adapter.

List:   GET https://bcpublicservice.hua.hrsmart.com/hr/ats/JobSearch/viewAll/
            jobSearchPaginationExternal_pageSize:100/jobSearchPaginationExternal_page:{n}
        (HTML table: ministry, req #, title link, union, work options, location(s),
        date opened M/D/YYYY, close date)
Detail: GET .../hr/ats/Posting/view/{id}  (#job_details_ats_requisition_description)
Details are fetched only for Metro Vancouver/remote rows whose title passes
`should_hydrate_record`. The site sits behind bot protection that may refuse
plain HTTP clients; failures are logged and the run continues.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

from src.db import Job
from src.parser import html_to_markdown
from src.search_match import should_hydrate_record
from src.sources.ats_common import get_text, location_ok, make_client

logger = logging.getLogger(__name__)

BASE = "https://bcpublicservice.hua.hrsmart.com"
LIST_PATH = "/hr/ats/JobSearch/viewAll/jobSearchPaginationExternal_pageSize:100/jobSearchPaginationExternal_page:{n}"
PAGE_SIZE = 100
MAX_PAGES = 15


def _date(text: str) -> str | None:
    try:
        return datetime.strptime(text.strip(), "%m/%d/%Y").date().isoformat()  # noqa: DTZ007
    except ValueError:
        return None


def parse_list(page: str | None) -> list[dict]:
    if not page:
        return []
    soup = BeautifulSoup(page, "html.parser")
    rows = []
    for tr in soup.select("table tbody tr"):
        cells = tr.find_all("td")
        link = tr.find("a", href=True)
        if len(cells) < 8 or link is None or "/Posting/view/" not in link["href"]:
            continue
        locations = [s.strip() for s in cells[5].get_text("\n").split("\n") if s.strip()]
        rows.append(
            {
                "id": link["href"].rstrip("/").rsplit("/", 1)[-1],
                "ministry": cells[0].get_text(" ", strip=True),
                "title": link.get_text(" ", strip=True),
                "work_options": cells[4].get_text(" ", strip=True),
                "location": "; ".join(locations),
                "opened": _date(cells[6].get_text()),
                "closes": _date(cells[7].get_text()),
            }
        )
    return rows


def parse_detail(page: str | None) -> str:
    if not page:
        return ""
    el = BeautifulSoup(page, "html.parser").find(id="job_details_ats_requisition_description")
    return html_to_markdown(str(el)) if el else ""


def _location(row: dict) -> str:
    loc = row["location"]
    if "remote" in row.get("work_options", "").lower():
        loc = f"Remote - {loc}" if loc else "Remote - British Columbia"
    return loc


def to_job(row: dict, description: str) -> Job:
    return Job(
        source="bcps",
        external_id=row["id"],
        title=row["title"],
        company=f"BC Public Service — {row['ministry']}" if row["ministry"] else "BC Public Service",
        location=_location(row),
        description=description,
        url=f"{BASE}/hr/ats/Posting/view/{row['id']}",
        posted_date=row.get("opened"),
        raw={k: row.get(k) for k in ("ministry", "work_options", "closes")},
    )


def fetch_bcps_jobs(*, search: dict | None = None, client: httpx.Client | None = None) -> list[Job]:
    own_client = client is None
    client = client or make_client()
    jobs = []
    try:
        for n in range(1, MAX_PAGES + 1):
            rows = parse_list(get_text(client, BASE + LIST_PATH.format(n=n)))
            for row in rows:
                location = _location(row)
                if not location_ok(location):
                    continue
                if search and not should_hydrate_record(row["title"], search, location=location):
                    continue
                jobs.append(to_job(row, parse_detail(get_text(client, f"{BASE}/hr/ats/Posting/view/{row['id']}"))))
            if len(rows) < PAGE_SIZE:
                break
    except Exception:
        logger.exception("BC Public Service fetch failed part-way — keeping what was found")
    finally:
        if own_client:
            client.close()
    logger.info("BC Public Service: %d relevant job(s)", len(jobs))
    return jobs
