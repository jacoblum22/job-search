"""Jobright.ai job-alert email adapter.

Source: `noreply@jobright.ai` — both the instant "new match" alerts and the
daily "Latest ... jobs you might like" digests. They share one card layout,
read from the HTML body: `p#job-company-name`, `p#job-title` (wrapping the
job link), one `p#job-tag` each for salary, location and referral count,
and `span#job-time-posted`. Ids repeat once per card, so each card is the
nearest ancestor of the title that also holds a company name.

The job id is the 24-hex-digit id in `jobright.ai/jobs/info/<id>`; the
stored URL is that link without the tracking query. Cards only carry a
title, company, location and salary, so the description is filled later by
the Chrome task (scripts/browser_queue.py). Checked against real alerts on
2026-10-18.
"""

from __future__ import annotations

import logging
import re
import sqlite3

from bs4 import BeautifulSoup
from googleapiclient.discovery import Resource

from src.db import Job
from src.sources.email_common import (
    EmailMessage,
    collect_alert_messages,
    fetch_new_messages,
)

logger = logging.getLogger(__name__)

SOURCE = "jobright"
SENDER = "noreply@jobright.ai"
JOB_URL_RE = re.compile(r"jobright\.ai/jobs/info/([0-9a-f]{24})")
REFERRALS_RE = re.compile(r"\breferrals?\b", re.IGNORECASE)


def fetch_jobright_jobs(
    conn: sqlite3.Connection,
    *,
    forward_from: str | None = None,
    service: Resource | None = None,
) -> list[Job]:
    """Fetch + parse new Jobright alert emails since the last run."""
    query = f"from:{SENDER}"
    if forward_from:
        query = f"({query}) OR (from:{forward_from} {SENDER})"
    if service is not None:
        messages = fetch_new_messages(service, conn, source=SOURCE, query=query)
    else:
        messages = collect_alert_messages(conn, source=SOURCE, query=query)

    jobs: list[Job] = []
    seen_ids: set[str] = set()
    for msg in messages:
        for job in parse_message(msg):
            if job.external_id in seen_ids:
                continue
            seen_ids.add(job.external_id)
            jobs.append(job)

    logger.info(
        "%s: parsed %d job(s) from %d email(s)", SOURCE, len(jobs), len(messages)
    )
    return jobs


def parse_message(msg: EmailMessage) -> list[Job]:
    if not msg.html:
        return []
    soup = BeautifulSoup(msg.html, "html.parser")
    jobs = []
    for title_el in soup.find_all(id="job-title"):
        anchor = title_el.find("a", href=JOB_URL_RE) or title_el.find_parent(
            "a", href=JOB_URL_RE
        )
        if not anchor:
            continue
        job_id = JOB_URL_RE.search(anchor["href"]).group(1)
        card = title_el.parent
        while card is not None and card.find(id="job-company-name") is None:
            card = card.parent
        company = location = salary = ""
        if card is not None:
            company = _text(card.find(id="job-company-name"))
            for tag in (_text(t) for t in card.find_all(id="job-tag")):
                if "$" in tag:
                    salary = salary or tag
                elif not REFERRALS_RE.search(tag):
                    location = location or tag
        jobs.append(
            Job(
                source=SOURCE,
                external_id=job_id,
                title=_text(title_el),
                company=company,
                location=location,
                url=f"https://jobright.ai/jobs/info/{job_id}",
                description=f"Salary: {salary}" if salary else "",
                raw={"gmail_message_id": msg.id, "subject": msg.subject},
            )
        )
    return jobs


def _text(el) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""
