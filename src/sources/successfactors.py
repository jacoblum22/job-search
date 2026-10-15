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
3. Newer "Unify" sites (Teck, Deloitte) render search results in the browser,
   so /search/ has no rows. Their listing comes from
   POST https://{host}/services/recruiting/v1/jobs
   `{"keywords": "", "locale": "en_US", "location": "", "pageNumber": N, "sortBy": "recent"}`
   -> `{"totalJobs": N, "jobSearchResult": [{"response": {id, unifiedStandardTitle,
   urlTitle, jobLocationShort[]}}]}`, 10 per page. Job pages are
   /job/{urlTitle}/{id}-{locale}/ and split the description over several
   itemprop="description" blocks. Classic sites answer that API with 401.
"""

from __future__ import annotations

import html
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
    join_locations,
    localize,
    location_ok,
    post_json,
    to_markdown,
)

MAX_SEARCH_PAGES = 40
UNIFY_MAX_PAGES = 60  # 10 postings per page
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

    blocks: list[str] = []
    for el in soup.find_all(attrs={"itemprop": "description"}):
        # Unify pages split the posting into header/body/footer blocks (and
        # some repeat them); classic pages have one.
        text = el.get("content") if el.get("content") else to_markdown(str(el))
        if text and text not in blocks:
            blocks.append(text)
    city, region = prop("addressLocality"), prop("addressRegion")
    return {
        "description": "\n\n".join(blocks),
        "location": ", ".join(str(p) for p in (city, region) if isinstance(p, str) and p),
    }


def parse_unify(data: dict | None, base: str, locale: str) -> tuple[list[dict], int]:
    """Rows (same shape as parse_search) from the Unify jobs API."""
    rows = []
    for item in (data or {}).get("jobSearchResult") or []:
        r = item.get("response") or {}
        if not r.get("id"):
            continue
        places = [re.sub(r"<[^>]+>", "", html.unescape(p)).strip() for p in r.get("jobLocationShort") or []]
        url_title = html.unescape(r.get("urlTitle") or r.get("unifiedUrlTitle") or "job")
        rows.append(
            {
                "id": str(r["id"]),
                "title": html.unescape(r.get("unifiedStandardTitle") or ""),
                "url": f"{base}/job/{url_title}/{r['id']}-{locale}/",
                "path": "",
                "location": join_locations(*places),
                "date": r.get("unifiedStandardStart"),
            }
        )
    return rows, int((data or {}).get("totalJobs") or 0)


def _classic_pages(client: httpx.Client, base: str):
    startrow, total, pages = 0, None, 0
    while pages < MAX_SEARCH_PAGES and (total is None or startrow < total):
        rows, total = parse_search(get_text(client, f"{base}/search/", params={"q": "", "startrow": startrow}))
        if not rows:
            return
        yield rows
        startrow += len(rows)
        pages += 1


def _unify_pages(client: httpx.Client, base: str, locale: str):
    seen = 0
    for page in range(UNIFY_MAX_PAGES):
        body = {"keywords": "", "locale": locale, "location": "", "pageNumber": page, "sortBy": "recent"}
        rows, total = parse_unify(post_json(client, f"{base}/services/recruiting/v1/jobs", body), base, locale)
        if not rows:
            return
        yield rows
        seen += len(rows)
        if seen >= total:
            return


def _fetch_one(client: httpx.Client, board: dict, search: dict | None) -> list[Job]:
    base = f"https://{board['host']}"
    params = {"locale": board.get("locale", "en_US")}
    if board.get("keywords"):
        params["keywords"] = f"({board['keywords']})"
    jobs = {j.external_id: j for j in parse_feed(get_text(client, f"{base}/services/rss/job/", params=params, headers=RSS_HEADERS), board)}

    pages = _classic_pages(client, base)
    first = next(pages, None)
    if first is None:  # no server-rendered rows: a Unify site
        pages = _unify_pages(client, base, params["locale"])
    else:
        pages = iter([first, *pages])
    for rows in pages:
        for row in rows:
            if row["id"] in jobs:
                continue
            location = localize(row["location"], board)
            multi = "more" in row["location"].lower() or ";" in row["location"]  # "Kamloops, BC +5 more…"
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
    return list(jobs.values())


def fetch_successfactors_jobs(
    boards: list, *, search: dict | None = None, client: httpx.Client | None = None
) -> list[Job]:
    return fetch_boards("SuccessFactors", boards, lambda c, b: _fetch_one(c, b, search), client=client)
