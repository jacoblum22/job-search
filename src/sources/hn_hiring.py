"""Hacker News "Ask HN: Who is hiring?" adapter (Algolia HN Search API).

1. GET https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring
   finds the newest monthly thread.
2. GET https://hn.algolia.com/api/v1/search?tags=comment,story_{id}&hitsPerPage=1000
   returns its comments; a job post is a top-level comment (parent_id == story id).
Posts are free text whose first line is usually "Company | Role | Location | ...".
Only posts mentioning Metro Vancouver, or remote work open to Canada, are kept.
"""

from __future__ import annotations

import html
import logging
import re

import httpx

from src.db import Job
from src.location_filter import is_vancouver_area
from src.parser import html_to_markdown
from src.sources.ats_common import get_json, location_ok, make_client

logger = logging.getLogger(__name__)

API = "https://hn.algolia.com/api/v1"
_TAG_RE = re.compile(r"<[^>]+>")
_NOT_TITLE_RE = re.compile(
    r"remote|onsite|on-site|hybrid|full[- ]?time|part[- ]?time|contract|intern|visa|\$|€|£|https?:|www\.|\.com\b"
    r"|\b(?:usa?|uk|eu|canada|europe|worldwide|anywhere)\b",
    re.IGNORECASE,
)


def header_line(comment_html: str) -> str:
    first = re.split(r"<p>|\n", comment_html or "", maxsplit=1)[0]
    return " ".join(html.unescape(_TAG_RE.sub(" ", first)).split())


def split_header(header: str) -> tuple[str, str]:
    """(company, role) from 'Company | Role | Location | ...'."""
    parts = [p.strip() for p in header.split("|") if p.strip()]
    if not parts:
        return "", ""
    company = parts[0]
    role = next((p for p in parts[1:] if not _NOT_TITLE_RE.search(p) and not is_vancouver_area(p)), "")
    return company[:120], role[:200]


def post_location(header: str) -> str:
    """The header minus the company is the best location hint
    ('Acme | Data Engineer | Vancouver, BC | Remote (Canada)')."""
    parts = [p.strip() for p in header.split("|") if p.strip()]
    text = "; ".join(parts[1:]) if len(parts) > 1 else header
    if is_vancouver_area(text):
        return text
    if re.search(r"\bremote\b", text, re.IGNORECASE):
        return text if text.lower().startswith("remote") else f"Remote - {text}"
    return text


def latest_story_id(client: httpx.Client) -> str | None:
    data = get_json(
        client,
        f"{API}/search_by_date",
        params={"tags": "story,author_whoishiring", "query": '"who is hiring"', "hitsPerPage": 3},
    )
    for hit in (data or {}).get("hits") or []:
        if "who is hiring" in (hit.get("title") or "").lower():
            return str(hit["objectID"])
    return None


def parse_comments(data: dict | None, story_id: str) -> list[Job]:
    jobs = []
    for hit in (data or {}).get("hits") or []:
        if str(hit.get("parent_id")) != str(story_id) or not hit.get("comment_text"):
            continue
        header = header_line(hit["comment_text"])
        location = post_location(header)
        if not location_ok(location):
            continue
        company, role = split_header(header)
        jobs.append(
            Job(
                source="hn_hiring",
                external_id=str(hit["objectID"]),
                title=role or f"{company} (see post)",
                company=company,
                location=location[:300],
                description=html_to_markdown(html.unescape(hit["comment_text"])),
                url=f"https://news.ycombinator.com/item?id={hit['objectID']}",
                posted_date=(hit.get("created_at") or "")[:10] or None,
                raw={"header": header, "story_id": story_id, "author": hit.get("author")},
            )
        )
    return jobs


def fetch_hn_jobs(*, client: httpx.Client | None = None) -> list[Job]:
    own_client = client is None
    client = client or make_client()
    try:
        story_id = latest_story_id(client)
        if not story_id:
            logger.warning("HN: no 'Who is hiring?' thread found")
            return []
        data = get_json(
            client, f"{API}/search", params={"tags": f"comment,story_{story_id}", "hitsPerPage": 1000}
        )
        jobs = parse_comments(data, story_id)
        logger.info("HN Who is hiring (%s): %d relevant post(s)", story_id, len(jobs))
        return jobs
    finally:
        if own_client:
            client.close()
