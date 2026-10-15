"""SAP SuccessFactors Recruiting Marketing (career site builder) adapter.

ICBC, TELUS, Rogers, Teck, Canfor, PCL, Coast Capital, FortisBC, Deloitte...

1. RSS: GET https://{host}/services/rss/job/?locale=en_US — full HTML
   description, link and pubDate, city in the title ("Analyst (Burnaby,
   British Columbia, Canada)"). Capped at the 20 newest postings.
2. Search pages: GET https://{host}/search/?q=&startrow=N — every posting as
   tr.data-row (a.jobTitle-link, span.jobLocation, span.jobDate) with
   "Results 1 – 25 of N". Postings beyond the RSS get their description from
   the job page's schema.org microdata (itemprop="description"), fetched only
   when the title passes `should_hydrate_record`.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import httpx
from bs4 import BeautifulSoup

from src.db import Job
from src.search_match import should_hydrate_record
from src.sources.ats_common import (
    fetch_boards,
    get_text,
    localize,
    location_ok,
    to_markdown,
)

MAX_SEARCH_PAGES = 40
_TOTAL_RE = re.compile(r"of\s+([\d,]+)")

_TITLE_RE = re.compile(r"^(?P<title>.*?)\s*\((?P<loc>[^()]*)\)\s*$")
_ID_RE = re.compile(r"/(\d+)/?$")
# The shared client asks for JSON; the RSS endpoint answers that with 406.
RSS_HEADERS = {"Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"}


def split_title(raw: str) -> tuple[str, str]:
    m = _TITLE_RE.match(raw or "")
    if not m:
        return (raw or "").strip(), ""
    return m.group("title").strip(), m.group("loc").strip()


def _date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError):
        return None


def parse_feed(xml_text: str | None, board: dict) -> list[Job]:
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        return []
    jobs = []
    for item in root.iter("item"):
        link = (item.findtext("link") or item.findtext("guid") or "").strip()
        title, location = split_title(item.findtext("title") or "")
        location = localize(location, board)
        if not link or not location_ok(location):
            continue
        link = link.split("?", 1)[0]
        m = _ID_RE.search(link)
        jobs.append(
            Job(
                source=f"successfactors:{board['slug']}",
                external_id=m.group(1) if m else link,
                title=title,
                company=board["name"],
                location=location,
                description=to_markdown(item.findtext("description")),
                url=link,
                posted_date=_date(item.findtext("pubDate")),
                raw={"link": link},
            )
        )
    return jobs


def parse_search(page: str | None) -> tuple[list[dict], int]:
    """Rows as {id, title, url, location, date} plus the total result count."""
    if not page:
        return [], 0
    soup = BeautifulSoup(page, "html.parser")
    rows = []
    for tr in soup.select("tr.data-row"):
        a = tr.select_one("a.jobTitle-link") or tr.find("a", href=True)
        if a is None:
            continue
        href = a["href"].split("?", 1)[0]
        m = _ID_RE.search(href)
        loc = tr.select_one("span.jobLocation")
        date = tr.select_one("span.jobDate")
        rows.append(
            {
                "id": m.group(1) if m else href,
                "title": a.get_text(" ", strip=True),
                "url": href if href.startswith("http") else None,
                "path": href,
                "location": loc.get_text(" ", strip=True) if loc else "",
                "date": date.get_text(" ", strip=True) if date else None,
            }
        )
    label = soup.select_one(".paginationLabel")
    m = _TOTAL_RE.search(label.get_text(" ") if label else "")
    return rows, int(m.group(1).replace(",", "")) if m else len(rows)


def parse_detail(page: str | None) -> dict:
    """schema.org microdata from a job page: description, datePosted, location."""
    if not page:
        return {}
    soup = BeautifulSoup(page, "html.parser")

    def prop(name: str):
        el = soup.find(attrs={"itemprop": name})
        if el is None:
            return None
        return el.get("content") or el

    desc = prop("description")
    city, region = prop("addressLocality"), prop("addressRegion")
    return {
        "description": to_markdown(str(desc)) if desc is not None and not isinstance(desc, str) else (desc or ""),
        "location": ", ".join(str(p) for p in (city, region) if isinstance(p, str) and p),
    }


def _fetch_one(client: httpx.Client, board: dict, search: dict | None) -> list[Job]:
    base = f"https://{board['host']}"
    params = {"locale": board.get("locale", "en_US")}
    if board.get("keywords"):
        params["keywords"] = f"({board['keywords']})"
    jobs = {j.external_id: j for j in parse_feed(get_text(client, f"{base}/services/rss/job/", params=params, headers=RSS_HEADERS), board)}

    startrow, total, pages = 0, None, 0
    while pages < MAX_SEARCH_PAGES and (total is None or startrow < total):
        rows, total = parse_search(get_text(client, f"{base}/search/", params={"q": "", "startrow": startrow}))
        if not rows:
            break
        for row in rows:
            if row["id"] in jobs:
                continue
            location = localize(row["location"], board)
            multi = "more" in row["location"].lower()  # "Kamloops, BC +5 more…"
            if row["location"] and not multi and not location_ok(location):
                continue
            if search and not should_hydrate_record(row["title"], search, company=board["name"], location=location):
                continue
            url = row["url"] or f"{base}{row['path']}"
            detail = parse_detail(get_text(client, url))
            location = localize(
                (detail.get("location") if multi else row["location"]) or detail.get("location", ""), board
            )
            if not location_ok(location):
                continue
            jobs[row["id"]] = Job(
                source=f"successfactors:{board['slug']}",
                external_id=row["id"],
                title=row["title"],
                company=board["name"],
                location=location,
                description=detail.get("description", ""),
                url=url,
                posted_date=None,
                raw={"listed_date": row["date"]},
            )
        startrow += len(rows)
        pages += 1
    return list(jobs.values())


def fetch_successfactors_jobs(
    boards: list, *, search: dict | None = None, client: httpx.Client | None = None
) -> list[Job]:
    return fetch_boards("SuccessFactors", boards, lambda c, b: _fetch_one(c, b, search), client=client)
