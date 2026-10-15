"""Teamtailor careers adapter (Uptempo, Owl.co, Klohn Crippen Berger...).

Feed: GET https://{host}/jobs.rss — every posting with the full HTML
description, pubDate, link, remoteStatus and tt:locations. `host` is
{slug}.teamtailor.com, a regional host ({slug}.na.teamtailor.com) or the
company's own careers domain.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

import httpx

from src.db import Job
from src.sources.ats_common import (
    fetch_boards,
    get_text,
    join_locations,
    localize,
    location_ok,
    to_markdown,
)

TT = "{https://teamtailor.com/locations}"


def _date(value: str | None) -> str | None:
    try:
        return parsedate_to_datetime(value).date().isoformat() if value else None
    except (TypeError, ValueError):
        return None


def parse_feed(xml_text: str | None, board: dict) -> list[Job]:
    start = (xml_text or "").find("<rss")
    if start < 0:
        return []
    try:
        root = ET.fromstring(xml_text[start:])
    except ET.ParseError:
        return []
    jobs = []
    for item in root.iter("item"):
        places = []
        for loc in item.iter(f"{TT}location"):
            city = (loc.findtext(f"{TT}city") or "").strip()
            country = (loc.findtext(f"{TT}country") or "").strip()
            places.append(", ".join(p for p in (city, country) if p) or (loc.findtext(f"{TT}name") or "").strip())
        location = join_locations(*places)
        if (item.findtext("remoteStatus") or "none").strip().lower() in ("fully", "remote", "temporary"):
            location = f"Remote - {location}" if location else "Remote"
        location = localize(location, board)
        if not location_ok(location):
            continue
        link = (item.findtext("link") or "").strip()
        jobs.append(
            Job(
                source=f"teamtailor:{board['slug']}",
                external_id=(item.findtext("guid") or link).strip(),
                title=(item.findtext("title") or "").strip(),
                company=board["name"],
                location=location,
                description=to_markdown(item.findtext("description")),
                url=link,
                posted_date=_date(item.findtext("pubDate")),
                raw={"remoteStatus": item.findtext("remoteStatus")},
            )
        )
    return jobs


def _fetch_one(client: httpx.Client, board: dict) -> list[Job]:
    host = board.get("host") or f"{board['slug']}.teamtailor.com"
    return parse_feed(get_text(client, f"https://{host}/jobs.rss"), board)


def fetch_teamtailor_jobs(boards: list, *, client: httpx.Client | None = None) -> list[Job]:
    return fetch_boards("Teamtailor", boards, _fetch_one, client=client)
