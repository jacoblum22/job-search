"""Government of Canada Job Bank adapter.

List:   GET https://www.jobbank.gc.ca/jobsearch/jobsearch?searchstring=..&fprov=BC&sort=D&page=N
        (HTML, 25 results per page; `locationstring` is ignored, `fprov` works)
Detail: GET https://www.jobbank.gc.ca/jobsearch/jobposting/{id}
        (schema.org RDFa: title, datePosted, hiringOrganization, address, description)
Details are fetched only for Metro Vancouver/remote listings whose title passes
`should_hydrate_record`. Postings Job Bank copied from other boards can have a
thin description; those still go through src/enrich.py.
"""

from __future__ import annotations

import logging
import re

import httpx
from bs4 import BeautifulSoup

from src.db import Job
from src.parser import html_to_markdown
from src.search_match import should_hydrate_record
from src.sources.ats_common import get_text, location_ok, make_client

logger = logging.getLogger(__name__)

BASE = "https://www.jobbank.gc.ca"
_PROV_RE = re.compile(r"\s*\((\w{2})\)\s*$")
# The shared client asks for JSON; Job Bank's search page answers that with
# HTTP 500 (every request in the Oct 16 2026 run), while a browser-style
# request for HTML loads normally.
HTML_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
}


def clean_location(text: str) -> str:
    """'Burnaby (BC)' -> 'Burnaby, BC'."""
    text = " ".join((text or "").replace("Location", " ").split())
    return _PROV_RE.sub(r", \1", text)


def parse_list(page: str | None) -> list[dict]:
    if not page:
        return []
    soup = BeautifulSoup(page, "html.parser")
    rows = []
    for art in soup.select("article[id^=article-]"):
        job_id = art["id"].removeprefix("article-")
        title_el = art.select_one(".noctitle")
        loc_el = art.select_one("li.location")
        rows.append(
            {
                "id": job_id,
                "title": title_el.get_text(" ", strip=True) if title_el else "",
                "company": (art.select_one("li.business") or BeautifulSoup("", "html.parser")).get_text(" ", strip=True),
                "location": clean_location(loc_el.get_text(" ", strip=True) if loc_el else ""),
                "date": (art.select_one("li.date") or BeautifulSoup("", "html.parser")).get_text(" ", strip=True),
                "telework": bool(art.select_one(".telework") and "remote" in art.select_one(".telework").get_text().lower()),
            }
        )
    return rows


def parse_detail(page: str | None) -> dict:
    if not page:
        return {}
    soup = BeautifulSoup(page, "html.parser")

    def prop(name: str):
        return soup.find(attrs={"property": name})

    body = soup.select_one(".job-posting-details-body")
    if body is not None:
        for hidden in body.select(".hidden, .wb-inv, script, style"):
            hidden.decompose()
        description = html_to_markdown(str(body))
    else:
        desc = prop("description")
        description = desc.get_text(" ", strip=True) if desc else ""
    date = prop("datePosted")
    posted = None
    if date is not None:
        posted = date.get("content") or " ".join(date.get_text(" ").replace("Posted on", " ").split()) or None
    return {"description": description, "datePosted": posted}


def to_job(row: dict, detail: dict) -> Job:
    location = row["location"]
    if row.get("telework"):
        location = f"Remote - {location}" if location else "Remote - Canada"
    return Job(
        source="jobbank",
        external_id=row["id"],
        title=row["title"],
        company=row["company"],
        location=location,
        description=detail.get("description") or "",
        url=f"{BASE}/jobsearch/jobposting/{row['id']}",
        posted_date=detail.get("datePosted") or row.get("date"),
        raw={"id": row["id"], "listed_date": row.get("date")},
    )


def fetch_jobbank_jobs(
    *,
    queries: list[str],
    search: dict | None = None,
    province: str = "BC",
    max_pages: int = 3,
    client: httpx.Client | None = None,
) -> list[Job]:
    own_client = client is None
    client = client or make_client()
    jobs: dict[str, Job] = {}
    try:
        for query in queries:
            for page in range(1, max_pages + 1):
                rows = parse_list(
                    get_text(
                        client,
                        f"{BASE}/jobsearch/jobsearch",
                        params={"searchstring": query, "fprov": province, "sort": "D", "page": page},
                        headers=HTML_HEADERS,
                    )
                )
                for row in rows:
                    if row["id"] in jobs or not location_ok(row["location"]):
                        continue
                    if search and not should_hydrate_record(
                        row["title"], search, company=row["company"], location=row["location"]
                    ):
                        continue
                    detail = parse_detail(get_text(client, f"{BASE}/jobsearch/jobposting/{row['id']}", headers=HTML_HEADERS))
                    jobs[row["id"]] = to_job(row, detail)
                if len(rows) < 25:
                    break
    except Exception:
        logger.exception("Job Bank fetch failed part-way — keeping what was found")
    finally:
        if own_client:
            client.close()
    logger.info("Job Bank: %d relevant job(s)", len(jobs))
    return list(jobs.values())
