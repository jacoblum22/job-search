"""LinkedIn job-alert email adapter.

Source: `jobalerts-noreply@linkedin.com` only. LinkedIn also sends "industry
trends"/newsletter mail from `messages-noreply@linkedin.com` — that's not a
job alert and is excluded by construction (the Gmail search is scoped to
the exact sender).

If alerts are forwarded from another inbox (see `forward_from` in
config/settings.yaml), the envelope From header becomes the forwarding
mailbox instead of LinkedIn's — a forwarded message can't be identified by
sender alone. The search then also matches on the original sender address,
which forwarded mail still carries as plain text (Outlook's "Forward"
action quotes the original headers in the body).

A single alert email can contain multiple saved-search sections, each
listing several jobs. The job ID lives in the `linkedin.com/comm/jobs/view/{id}`
URL path (LinkedIn's email-tracking links add a `/comm` prefix not present
in the plain web URL) — that's the stable dedup key.

Title/company/location parsing is structural (BeautifulSoup, not regex over
raw text), verified against a real forwarded digest email on 2026-09-18:
each job card is a small table where the job-title anchor is the only
non-empty-text `<a>` among the (repeated) links to that job's URL, and the
next table row's `<p>` holds "Company · Location". Both the exact markup
and the "·" separator could change if LinkedIn revises their email
template — this degrades gracefully (title falls back to the email
subject, company/location fall back to empty) rather than failing the
whole adapter.
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

SOURCE = "linkedin"
SENDER = "jobalerts-noreply@linkedin.com"
JOB_URL_RE = re.compile(r"linkedin\.com/(?:comm/)?jobs/view/(\d+)")


def fetch_linkedin_jobs(
    service: Resource, conn: sqlite3.Connection, *, forward_from: str | None = None
) -> list[Job]:
    """Fetch + parse new LinkedIn job-alert emails since the last run.

    `forward_from` is the forwarding mailbox address (config/settings.yaml's
    `email_sources.forward_from`) if alerts are relayed through another
    inbox rather than landing in Gmail directly.
    """
    query = f"from:{SENDER}"
    if forward_from:
        query = f"({query}) OR (from:{forward_from} {SENDER})"
    messages = fetch_new_messages(service, conn, source=SOURCE, query=query)

    jobs: list[Job] = []
    for msg in messages:
        if msg.html:
            jobs.extend(_parse_html(msg))
        else:
            jobs.extend(_parse_plaintext(msg))

    logger.info("%s: parsed %d job(s) from %d email(s)", SOURCE, len(jobs), len(messages))
    return jobs


def _parse_html(msg: EmailMessage) -> list[Job]:
    soup = BeautifulSoup(msg.html, "html.parser")

    # Each job's URL appears in multiple anchors per card (logo image link,
    # an outer link wrapping the whole card, and the title-only link). Only
    # the title-only one is useful for the title text — it's the leaf anchor
    # with no nested <table>/<img> (those mark the logo/container wrappers).
    candidates_by_id: dict[str, list] = {}
    for anchor in soup.find_all("a", href=JOB_URL_RE.search):
        match = JOB_URL_RE.search(anchor["href"])
        if not match:
            continue
        if anchor.find("table") is not None or anchor.find("img") is not None:
            continue
        if not anchor.get_text(strip=True):
            continue
        candidates_by_id.setdefault(match.group(1), []).append(anchor)

    jobs: list[Job] = []
    for job_id, anchors in candidates_by_id.items():
        title_anchor = min(anchors, key=lambda a: len(a.get_text(strip=True)))
        jobs.append(_build_job(job_id, title_anchor, msg))

    return jobs


def _build_job(job_id: str, title_anchor, msg: EmailMessage) -> Job:
    title = " ".join(title_anchor.get_text(strip=True).split())
    company, location = _company_location(title_anchor)
    return Job(
        source=SOURCE,
        external_id=job_id,
        title=title or msg.subject,
        company=company,
        location=location,
        url=f"https://www.linkedin.com/jobs/view/{job_id}/",
        raw={"gmail_message_id": msg.id, "subject": msg.subject},
    )


def _company_location(title_anchor) -> tuple[str, str]:
    """Company/location live in a `<p>` in the row right after the title's row."""
    title_row = title_anchor.find_parent("tr")
    if not title_row:
        return "", ""
    next_row = title_row.find_next_sibling("tr")
    if not next_row:
        return "", ""
    p = next_row.find("p")
    if not p:
        return "", ""
    parts = [" ".join(part.split()) for part in p.get_text(strip=True).split("·")]
    company = parts[0] if parts else ""
    location = parts[1] if len(parts) > 1 else ""
    return company, location


def _parse_plaintext(msg: EmailMessage) -> list[Job]:
    """Fallback for plaintext-only messages: job ID only, no field extraction."""
    jobs: list[Job] = []
    seen_ids: set[str] = set()
    for match in JOB_URL_RE.finditer(msg.plain_text):
        job_id = match.group(1)
        if job_id in seen_ids:
            continue
        seen_ids.add(job_id)
        jobs.append(
            Job(
                source=SOURCE,
                external_id=job_id,
                title=msg.subject,
                company="",
                location="",
                url=f"https://www.linkedin.com/jobs/view/{job_id}/",
                raw={"gmail_message_id": msg.id, "subject": msg.subject},
            )
        )
    return jobs
