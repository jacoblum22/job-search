"""Listing page + schema.org JobPosting detail pages (JazzHR, Humi, ...).

For boards with no JSON feed but whose job pages carry JobPosting JSON-LD:
  list:   GET {list_url}; job links are hrefs matching the board's `link_pattern`
          (a regex; group 1, when present, is the job id)
  detail: GET each link; title, location, date and full description come from
          the JSON-LD. Details are fetched only when the link text (the title)
          passes `should_hydrate_record`.
Built-in patterns: `kind: jazzhr` (https://{slug}.applytojob.com/apply) and
`kind: humi` (https://{slug}.applytojobs.ca/).
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

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

KINDS = {
    "jazzhr": ("https://{host}/apply", r"/apply/([A-Za-z0-9]{8,12})/[^/?#]+"),
    "humi": ("https://{host}/", r"^/[a-z0-9-]+/(\d+)/?$"),
}
MAX_LINKS = 200


def _settings(board: dict) -> tuple[str, re.Pattern]:
    kind = board.get("kind")
    host = board.get("host") or {
        "jazzhr": f"{board['slug']}.applytojob.com",
        "humi": f"{board['slug']}.applytojobs.ca",
    }.get(kind, "")
    url_tpl, pattern = KINDS.get(kind, (board.get("list_url", ""), board.get("link_pattern", "")))
    return board.get("list_url") or url_tpl.format(host=host), re.compile(board.get("link_pattern") or pattern)


def parse_links(page: str | None, base_url: str, pattern: re.Pattern) -> list[dict]:
    if not page:
        return []
    soup = BeautifulSoup(page, "html.parser")
    links: dict[str, dict] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        m = pattern.search(href)
        if not m:
            continue
        url = urljoin(base_url, href)
        key = m.group(1) if m.groups() else url
        title = a.get_text(" ", strip=True)
        if key not in links or (title and len(title) > len(links[key]["title"]) and title.lower() != "learn more"):
            links[key] = {"id": key, "url": url, "title": "" if title.lower() == "learn more" else title}
    return list(links.values())[:MAX_LINKS]


def fetch_jsonld_board_jobs(boards: list, *, search: dict | None = None, client: httpx.Client | None = None) -> list[Job]:
    def fetch_one(client: httpx.Client, board: dict) -> list[Job]:
        list_url, pattern = _settings(board)
        jobs = []
        for link in parse_links(get_text(client, list_url), list_url, pattern):
            if search and link["title"] and not should_hydrate_record(link["title"], search, company=board["name"]):
                continue
            postings = find_job_postings(get_text(client, link["url"]) or "")
            if not postings:
                continue
            post = postings[0]
            location = localize(posting_location(post), board)
            if not location_ok(location):
                continue
            jobs.append(
                Job(
                    source=f"{board.get('kind') or 'jsonld'}:{board['slug']}",
                    external_id=link["id"],
                    title=post.get("title") or link["title"],
                    company=board["name"],
                    location=location,
                    description=to_markdown(post.get("description"), escaped="&lt;" in (post.get("description") or "")),
                    url=link["url"],
                    posted_date=(post.get("datePosted") or "")[:10] or None,
                    raw={"employmentType": post.get("employmentType")},
                )
            )
        return jobs

    return fetch_boards("JSON-LD board", boards, fetch_one, client=client)
