"""iCIMS careers-portal adapter (Vancouver Coastal Health, Providence, KPMG, ...).

List:   GET https://{host}/jobs/search?ss=1&in_iframe=1&pr={page}   (HTML job cards,
        no description; "Page 1 of N" header)
Detail: GET https://{host}/jobs/{id}/{slug}/job?in_iframe=1         (schema.org
        JobPosting JSON-LD with the full description and location)
Details are fetched only for cards whose title passes `should_hydrate_record`
(and whose city, when the card shows one, is in the right area). The JSON-LD
datePosted is unreliable on iCIMS (often stale), so posted_date is left empty.
"""

from __future__ import annotations

import re

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
from src.sources.jsonld import find_job_postings, posting_location

_JOB_HREF_RE = re.compile(r"/jobs/(\d+)/[^/?#]+/job")
_PAGES_RE = re.compile(r"Page\s+\d+\s+of\s+(\d+)", re.IGNORECASE)
MAX_PAGES = 20
_LOCATION_LABELS = ("city", "location", "job location", "work location")


def _card_fields(card) -> dict[str, str]:
    fields: dict[str, str] = {}
    for label in card.select(".field-label"):
        value = label.find_next_sibling("span")
        if value is not None:
            fields[label.get_text(" ", strip=True).lower()] = value.get_text(" ", strip=True)
    for tag in card.select(".iCIMS_JobHeaderTag"):
        dt, dd = tag.find("dt"), tag.find("dd")
        if dt and dd:
            fields[dt.get_text(" ", strip=True).lower()] = dd.get_text(" ", strip=True)
    return fields


def parse_list(page: str | None) -> tuple[list[dict], int]:
    """Cards as {id, title, url, city}, plus the page count."""
    if not page:
        return [], 0
    soup = BeautifulSoup(page, "html.parser")
    cards, seen = [], set()
    for a in soup.find_all("a", href=True):
        m = _JOB_HREF_RE.search(a["href"])
        if not m or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        card = a.find_parent(["li", "tr"]) or a.parent
        fields = _card_fields(card)
        heading = a.find(["h3", "h2"])
        title = (heading or a).get_text(" ", strip=True)
        title = re.sub(r"^(Job )?Title\s+", "", title)
        city = next((fields[k] for k in _LOCATION_LABELS if fields.get(k)), "")
        url = a["href"] if "in_iframe=1" in a["href"] else f"{a['href'].split('?')[0]}?in_iframe=1"
        cards.append({"id": m.group(1), "title": title, "url": url, "city": city})
    m = _PAGES_RE.search(soup.get_text(" "))
    return cards, int(m.group(1)) if m else 1


def parse_detail(page: str | None) -> dict:
    postings = find_job_postings(page or "")
    return postings[0] if postings else {}


def to_job(card: dict, posting: dict, board: dict) -> Job:
    location = posting_location(posting) if posting else ""
    location = localize(location or card.get("city", ""), board)
    return Job(
        source=f"icims:{board['slug']}",
        external_id=card["id"],
        title=posting.get("title") or card["title"],
        company=board["name"],
        location=location,
        description=to_markdown(posting.get("description")),
        url=card["url"].replace("?in_iframe=1", "").replace("&in_iframe=1", ""),
        posted_date=None,
        raw={"id": card["id"], "city": card.get("city"), "employmentType": posting.get("employmentType")},
    )


def fetch_icims_jobs(
    boards: list, *, search: dict | None = None, client: httpx.Client | None = None
) -> list[Job]:
    def fetch_one(client: httpx.Client, board: dict) -> list[Job]:
        jobs: list[Job] = []
        pages = 1
        page = 0
        while page < min(pages, MAX_PAGES):
            params = {"ss": "1", "in_iframe": "1", "pr": str(page)}
            if board.get("search_keyword"):
                params["searchKeyword"] = board["search_keyword"]
            cards, pages = parse_list(get_text(client, f"https://{board['host']}/jobs/search", params=params))
            if not cards:
                break
            for card in cards:
                city = localize(card["city"], board)
                if card["city"] and not location_ok(city):
                    continue
                if search and not should_hydrate_record(card["title"], search, company=board["name"], location=city):
                    continue
                job = to_job(card, parse_detail(get_text(client, card["url"])), board)
                if location_ok(job.location):
                    jobs.append(job)
            page += 1
        return jobs

    return fetch_boards("iCIMS", boards, fetch_one, client=client)
