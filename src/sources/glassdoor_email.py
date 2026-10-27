"""Glassdoor job-alert email adapter.

Source: `noreply@glassdoor.com`. Glassdoor's plaintext alert body is
unusable — heavy nested-table HTML email markup garbles the plaintext
conversion (confirmed against a live sample in docs/history/v2-aggregation-plan.md) — so
this parses the raw HTML body with BeautifulSoup instead.

Job ID lives in `jobListingId=<numeric>` on every job card anchor — the
stable dedup key, confirmed against a live sample email during planning.
The stored URL is built from it (`glassdoor.ca/job-listing/j?jl=<id>`)
rather than the email's personalized tracking link.

Each job card is one anchor whose text pieces run company, rating (absent
for some employers), title, location, salary, "(Employer Est.)", an
optional "Easy Apply", and the posting age, e.g.
`WorkSafeBC | 3.5 ★ | Co-op Student, Analytics ... | Richmond | $26 - $30 |
( | Employer Est. | ) | 2d`. Checked against real alerts on 2026-10-18;
before that the whole anchor text was stored as the title with no company
or location, so every Glassdoor job failed the location filter.

If alerts are forwarded from another inbox (see `forward_from` in
config/settings.yaml), the envelope From header becomes the forwarding
mailbox instead of Glassdoor's — a forwarded message can't be identified by
sender alone. The search then also matches on the original sender address,
which forwarded mail still carries as plain text (Outlook's "Forward"
action quotes the original headers in the body).
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

SOURCE = "glassdoor"
SENDER = "noreply@glassdoor.com"
# Cursor key in source_cursors. Renamed from "glassdoor" when the parser was
# fixed (2026-10-18) so the next run reads the last 30 days of alerts again.
CURSOR = "glassdoor-v2"
JOB_ID_RE = re.compile(r"jobListingId=(\d+)")
RATING_RE = re.compile(r"^\d(?:\.\d)?\s*★$")
AGE_RE = re.compile(r"^\d+[hd]\+?$|^24h$|^30d\+$")
SKIP = {"(", ")", "Employer Est.", "Glassdoor Est.", "Easy Apply"}


def fetch_glassdoor_jobs(
    conn: sqlite3.Connection,
    *,
    forward_from: str | None = None,
    service: Resource | None = None,
) -> list[Job]:
    """Fetch + parse new Glassdoor job-alert emails since the last run.

    `forward_from` is the forwarding mailbox address (config/settings.yaml's
    `email_sources.forward_from`) if alerts are relayed through another
    inbox rather than landing in Gmail directly.
    """
    query = f"from:{SENDER}"
    if forward_from:
        query = f"({query}) OR (from:{forward_from} {SENDER})"
    if service is not None:
        messages = fetch_new_messages(service, conn, source=CURSOR, query=query)
    else:
        messages = collect_alert_messages(conn, source=CURSOR, query=query)

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
    # A job's id shows up on several anchors (logo, card); the card anchor
    # is the one with the most text pieces.
    cards: dict[str, list[str]] = {}
    for anchor in soup.find_all("a", href=JOB_ID_RE):
        job_id = JOB_ID_RE.search(anchor["href"]).group(1)
        pieces = [" ".join(t.split()) for t in anchor.stripped_strings]
        if len(pieces) > len(cards.get(job_id, [])):
            cards[job_id] = pieces
    return [_build_job(job_id, pieces, msg) for job_id, pieces in cards.items()]


def _build_job(job_id: str, pieces: list[str], msg: EmailMessage) -> Job:
    fields = [
        p
        for p in pieces
        if p not in SKIP and not RATING_RE.match(p) and not AGE_RE.match(p)
    ]
    company = title = location = salary = ""
    if len(fields) >= 3:
        company, title, location = fields[:3]
        salary = next((f for f in fields[3:] if f.startswith("$")), "")
    elif fields:
        title = fields[0]
    return Job(
        source=SOURCE,
        external_id=job_id,
        title=title or msg.subject,
        company=company,
        location=location,
        url=f"https://www.glassdoor.ca/job-listing/j?jl={job_id}",
        description=f"Salary: {salary} (employer estimate)" if salary else "",
        posted_date=msg.internal_date.date().isoformat(),  # alerts go out within a day of posting
        raw={"gmail_message_id": msg.id, "subject": msg.subject},
    )
