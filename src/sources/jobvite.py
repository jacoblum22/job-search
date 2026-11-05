"""Jobvite adapter (Absolute Software, DNEG, Taseko/Trekor...).

Feed: GET https://app.jobvite.com/CompanyJobs/Xml.aspx?c={company_id} — every
posting with the full HTML description, location and date. `company_id` (the
"companyEId") is found once in the script of https://jobs.jobvite.com/{slug}/jobs.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx

from src.db import Job
from src.sources.ats_common import (
    fetch_boards,
    get_text,
    localize,
    location_ok,
    to_markdown,
)

FEED = "https://app.jobvite.com/CompanyJobs/Xml.aspx"


def _date(text: str | None) -> str | None:
    try:
        return datetime.strptime((text or "").strip(), "%m/%d/%Y").date().isoformat()  # noqa: DTZ007
    except ValueError:
        return None


def parse_feed(xml_text: str | None, board: dict) -> list[Job]:
    start = (xml_text or "").find("<result")
    if start < 0:
        return []
    try:
        root = ET.fromstring(xml_text[start:])
    except ET.ParseError:
        return []
    jobs = []
    for job in root.iter("job"):
        location = localize((job.findtext("location") or "").strip(), board)
        if not location_ok(location):
            continue
        job_id = (job.findtext("id") or "").strip()
        slug = board.get("board_slug") or board["slug"]
        jobs.append(
            Job(
                source=f"jobvite:{board['slug']}",
                external_id=job_id,
                title=(job.findtext("title") or "").strip(),
                company=board["name"],
                location=location,
                description=to_markdown(job.findtext("description")),
                url=f"https://jobs.jobvite.com/{slug}/job/{job_id}",
                posted_date=_date(job.findtext("date")),
                raw={k: job.findtext(k) for k in ("requisitionid", "category", "jobtype")},
            )
        )
    return jobs


def _fetch_one(client: httpx.Client, board: dict) -> list[Job]:
    return parse_feed(get_text(client, FEED, params={"c": board["company_id"]}), board)


BOARD_PAUSE = 5  # seconds; app.jobvite.com answers 429 to back-to-back boards


def fetch_jobvite_jobs(boards: list, *, client: httpx.Client | None = None, pause: float = BOARD_PAUSE) -> list[Job]:
    seen = 0

    def fetch_one(client: httpx.Client, board: dict) -> list[Job]:
        nonlocal seen
        if seen and pause:
            time.sleep(pause)
        seen += 1
        return _fetch_one(client, board)

    # One at a time: the pause between boards is what keeps Jobvite from 429ing.
    return fetch_boards("Jobvite", boards, fetch_one, client=client, workers=1)
