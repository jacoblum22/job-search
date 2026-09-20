"""Glassdoor job-alert email adapter.

Source: `noreply@glassdoor.com`. Glassdoor's plaintext alert body is
unusable — heavy nested-table HTML email markup garbles the plaintext
conversion (confirmed against a live sample in AGGREGATION_PLAN.md) — so
this parses the raw HTML body with BeautifulSoup instead.

Job ID lives in `jobListingId=<numeric>` on every job card anchor — the
stable dedup key, confirmed against a live sample email during planning.

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
from src.sources.email_common import EmailMessage, fetch_new_messages

logger = logging.getLogger(__name__)

SOURCE = "glassdoor"
SENDER = "noreply@glassdoor.com"
JOB_ID_RE = re.compile(r"jobListingId=(\d+)")


def fetch_glassdoor_jobs(
    service: Resource, conn: sqlite3.Connection, *, forward_from: str | None = None
) -> list[Job]:
    """Fetch + parse new Glassdoor job-alert emails since the last run.

    `forward_from` is the forwarding mailbox address (config/settings.yaml's
    `email_sources.forward_from`) if alerts are relayed through another
    inbox rather than landing in Gmail directly.
    """
    query = f"from:{SENDER}"
    if forward_from:
        query = f"({query}) OR (from:{forward_from} {SENDER})"
    messages = fetch_new_messages(service, conn, source=SOURCE, query=query)

    jobs: list[Job] = []
    seen_ids: set[str] = set()
    for msg in messages:
        if not msg.html:
            continue
        soup = BeautifulSoup(msg.html, "html.parser")
        for job_id in JOB_ID_RE.findall(msg.html):
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            jobs.append(_build_job(job_id, soup, msg))

    logger.info("%s: parsed %d job(s) from %d email(s)", SOURCE, len(jobs), len(messages))
    return jobs


def _build_job(job_id: str, soup: BeautifulSoup, msg: EmailMessage) -> Job:
    anchor = soup.find("a", href=re.compile(rf"jobListingId={job_id}\b"))
    title = anchor.get_text(strip=True) if anchor else ""
    url = anchor["href"] if anchor and anchor.has_attr("href") else ""
    return Job(
        source=SOURCE,
        external_id=job_id,
        title=title or msg.subject,
        company="",
        location="",
        url=url,
        raw={"gmail_message_id": msg.id, "subject": msg.subject},
    )
