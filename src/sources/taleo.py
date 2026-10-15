"""Taleo Business Edition adapter (City of Burnaby, City of Richmond, KPU, Grant Thornton...).

The RSS servlet returns every open requisition with the full HTML description:
  GET https://{host}/{dc}/ats/servlet/Rss?org={org}&cws={cws}&WebPage=SRCHR&WebVersion=0&_rss_version=2
Items carry taleo:reqId, taleo:locationCity/State/Country and taleo:html-description.
pubDate is the feed's build time, not the posting date, so posted_date is left empty.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import httpx

from src.db import Job
from src.sources.ats_common import (
    fetch_boards,
    get_text,
    localize,
    location_ok,
    to_markdown,
)

NS = "{urn:TBERss}"


def _root(xml_text: str):
    start = xml_text.find("<rss")
    if start < 0:
        return None
    try:
        return ET.fromstring(xml_text[start:])
    except ET.ParseError:
        return None


def parse_feed(xml_text: str | None, board: dict) -> list[Job]:
    root = _root(xml_text or "")
    if root is None:
        return []
    jobs = []
    for item in root.iter("item"):
        city = item.findtext(f"{NS}locationCity") or ""
        state = item.findtext(f"{NS}locationState") or ""
        location = localize(", ".join(p for p in (city.strip(), state.strip()) if p), board)
        if not location_ok(location):
            continue
        req_id = (item.findtext(f"{NS}reqId") or "").strip()
        link = (item.findtext("link") or "").strip()
        html_desc = item.findtext(f"{NS}html-description")
        jobs.append(
            Job(
                source=f"taleo:{board['slug']}",
                external_id=req_id or link,
                title=(item.findtext("title") or "").strip(),
                company=board["name"],
                location=location,
                description=to_markdown(html_desc) if html_desc else (item.findtext("description") or "").strip(),
                url=link,
                posted_date=None,
                raw={"department": item.findtext(f"{NS}department"), "location": item.findtext(f"{NS}location")},
            )
        )
    return jobs


def _fetch_one(client: httpx.Client, board: dict) -> list[Job]:
    url = f"https://{board['host']}/{board['dc']}/ats/servlet/Rss"
    params = {"org": board["org"], "cws": str(board["cws"]), "WebPage": "SRCHR", "WebVersion": "0", "_rss_version": "2"}
    return parse_feed(get_text(client, url, params=params), board)


def fetch_taleo_jobs(boards: list, *, client: httpx.Client | None = None) -> list[Job]:
    return fetch_boards("Taleo", boards, _fetch_one, client=client)
