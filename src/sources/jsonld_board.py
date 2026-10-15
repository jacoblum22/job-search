"""Listing page + detail pages: JazzHR, Humi and plain custom careers pages.

  list:   GET {list_url}; job links are hrefs matching the board's `link_pattern`
          (a regex; group 1, when present, is the job id). `list_url` may contain
          `{query}` (run once per search keyword) and `{page}` (pages
          `page_start`.. up to `max_pages`, stopping when a page adds no links).
  detail: GET each link. If it carries schema.org JobPosting JSON-LD, title,
          location, date and description come from that. Otherwise (`html`
          boards) the title is the page's <h1> and the description is the
          page's main text block (or `content_selector`), and the location is
          the board's `fallback_location` unless `title_separator` splits one
          off the link text ("Engineer • Victoria Office").
  Details are fetched only when the link text (the title) passes
  `should_hydrate_record`; `exclude_pattern` (regex on URL + title) skips links.
Built-in patterns: `kind: jazzhr` (https://{slug}.applytojob.com/apply) and
`kind: humi` (https://{slug}.applytojobs.ca/).
"""

from __future__ import annotations

import re
from urllib.parse import quote_plus, urljoin

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
CTA_TEXT = {"learn more", "view details", "view job details", "read more", "apply", "apply now", "details", "more"}
DEFAULT_MAX_PAGES = 5
DROP_TAGS = ("script", "style", "noscript", "header", "footer", "nav", "form", "aside", "svg", "iframe")


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
        if title.lower() in CTA_TEXT:
            title = ""
        if key not in links or len(title) > len(links[key]["title"]):
            links[key] = {"id": key, "url": url, "title": title}
    return list(links.values())[:MAX_LINKS]


def list_urls(list_url: str, board: dict, search: dict | None) -> list[list[str]]:
    """URL groups to walk: one group per query, each group one URL per page."""
    queries = [None]
    if "{query}" in list_url:
        queries = list((search or {}).get("keywords") or []) or [""]
    pages = [None]
    if "{page}" in list_url:
        start = int(board.get("page_start", 0))
        pages = list(range(start, start + int(board.get("max_pages", DEFAULT_MAX_PAGES))))
    return [
        [list_url.format(query=quote_plus(q or ""), page=p) if (q is not None or p is not None) else list_url for p in pages]
        for q in queries
    ]


def main_content(soup: BeautifulSoup):
    """The element holding the page's main text: readability-lite.

    Scores each ancestor by the text of the paragraphs, list items and
    subheadings inside it (ignoring link-heavy blocks such as menus), then
    returns the deepest element holding at least 80% of the best score.
    """
    scores: dict[int, list] = {}
    for block in soup.find_all(["p", "li", "h2", "h3", "h4"]):
        size = len(block.get_text(" ", strip=True))
        if size < 20:
            continue
        if sum(len(a.get_text(" ", strip=True)) for a in block.find_all("a")) > size * 0.5:
            continue
        for anc in block.parents:
            if anc.name in ("html", "[document]"):
                break
            scores.setdefault(id(anc), [anc, 0])[1] += size
    if not scores:
        return None
    top = max(score for _, score in scores.values())
    return max((el for el, score in scores.values() if score >= 0.8 * top), key=lambda el: len(list(el.parents)))


def clean_title(text: str, company: str) -> str:
    """'Careers -Financial Analyst - Oppy' -> 'Financial Analyst'."""
    company_words = {w for w in re.findall(r"[a-z]{4,}", company.lower())}
    parts = [p.strip() for p in re.split(r"\s*[|\u2013\u2014]\s*|\s+-\s*|\s*-\s+", text) if p.strip()]
    kept = [p for p in parts if p.lower() not in {"careers", "career", "jobs"} and not company_words & set(re.findall(r"[a-z]{4,}", p.lower()))]
    return " - ".join(kept) or text.strip()


def parse_html_posting(page: str, board: dict) -> dict:
    soup = BeautifulSoup(page, "html.parser")
    og = soup.find("meta", attrs={"property": "og:title"})
    h1 = soup.find("h1")
    if og and og.get("content"):
        title = clean_title(og["content"], board["name"])
    else:
        title = clean_title(h1.get_text(" ", strip=True) if h1 else (soup.title.string or "" if soup.title else ""), board["name"])
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()
    selector = board.get("content_selector")
    body = soup.select_one(selector) if selector else main_content(soup)
    return {
        "title": title,
        "description": to_markdown(str(body)) if body else "",
    }


def split_title(title: str, board: dict) -> tuple[str, str]:
    sep = board.get("title_separator")
    if sep and sep in title:
        head, tail = title.split(sep, 1)
        return head.strip(), tail.strip()
    return title, ""


def fetch_jsonld_board_jobs(boards: list, *, search: dict | None = None, client: httpx.Client | None = None) -> list[Job]:
    def fetch_one(client: httpx.Client, board: dict) -> list[Job]:
        list_url, pattern = _settings(board)
        exclude = re.compile(board["exclude_pattern"], re.IGNORECASE) if board.get("exclude_pattern") else None
        links: dict[str, dict] = {}
        for group in list_urls(list_url, board, search):
            for url in group:
                before = len(links)
                for link in parse_links(get_text(client, url), url, pattern):
                    links.setdefault(link["id"], link)
                if len(links) == before or len(links) >= MAX_LINKS:
                    break
        jobs = []
        for link in links.values():
            title, title_location = split_title(link["title"], board)
            if exclude and exclude.search(f"{link['url']} {title}"):
                continue
            if search and title and not should_hydrate_record(title, search, company=board["name"]):
                continue
            page = get_text(client, link["url"]) or ""
            postings = find_job_postings(page)
            if postings:
                post = postings[0]
                location = posting_location(post)
                description = to_markdown(post.get("description"), escaped="&lt;" in (post.get("description") or ""))
                posted = (post.get("datePosted") or "")[:10] or None
                raw = {"employmentType": post.get("employmentType")}
            elif board.get("kind") == "html" and page:
                post = parse_html_posting(page, board)
                location, description, posted, raw = title_location, post["description"], None, {}
            else:
                continue
            title = title or post.get("title") or ""
            if search and not link["title"] and not should_hydrate_record(title, search, company=board["name"]):
                continue  # the list only had "Learn more" links, so gate on the page's own title
            location = localize(location, board)
            if not location_ok(location):
                continue
            jobs.append(
                Job(
                    source=f"{board.get('kind') or 'jsonld'}:{board['slug']}",
                    external_id=link["id"],
                    title=title,
                    company=board["name"],
                    location=location,
                    description=description,
                    url=link["url"],
                    posted_date=posted,
                    raw=raw,
                )
            )
        return jobs

    return fetch_boards("JSON-LD board", boards, fetch_one, client=client)
