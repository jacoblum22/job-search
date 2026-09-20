"""Indeed job-alert email adapter.

Source: `donotreply@jobalert.indeed.com`. Alert emails are a multi-job
digest, mostly clean plaintext (per AGGREGATION_PLAN.md's live sample
review) — unlike Glassdoor, plaintext parsing works fine here.

If alerts are forwarded from another inbox (see `forward_from` in
config/settings.yaml), the envelope From header becomes the forwarding
mailbox instead of Indeed's — a forwarded message can't be identified by
sender alone. The search then also matches on the original sender address,
which forwarded mail still carries as plain text (Outlook's "Forward"
action quotes the original headers in the body).

Job key lives in the `jk=` URL query param — Indeed's stable per-posting
identifier, used as the dedup key here instead of the full URL (which can
carry tracking params that vary between sends of the same job).

Title/company/location extraction is a best-effort heuristic (nearest line
before the job link) rather than a fixed template parse, since it hasn't
been validated against a live sample email in this environment. It degrades
gracefully — title falls back to the email subject — rather than failing
the whole adapter.
"""

from __future__ import annotations

import logging
import re
import sqlite3

from googleapiclient.discovery import Resource

from src.db import Job
from src.sources.email_common import EmailMessage, fetch_new_messages

logger = logging.getLogger(__name__)

SOURCE = "indeed"
SENDER = "donotreply@jobalert.indeed.com"
JOB_URL_RE = re.compile(r"[?&]jk=([0-9a-f]{8,40})")
_TAG_OR_BREAK_RE = re.compile(r"<[^>]+>|[\r\n]+")


def fetch_indeed_jobs(
    service: Resource, conn: sqlite3.Connection, *, forward_from: str | None = None
) -> list[Job]:
    """Fetch + parse new Indeed job-alert emails since the last run.

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
        text = msg.plain_text or msg.html
        for match in JOB_URL_RE.finditer(text):
            job_id = match.group(1)
            if job_id in seen_ids:
                continue
            seen_ids.add(job_id)
            jobs.append(_build_job(job_id, text, match.start(), msg))

    logger.info("%s: parsed %d job(s) from %d email(s)", SOURCE, len(jobs), len(messages))
    return jobs


def _build_job(job_id: str, text: str, match_pos: int, msg: EmailMessage) -> Job:
    title, company, location = _guess_fields(text, match_pos)
    return Job(
        source=SOURCE,
        external_id=job_id,
        title=title or msg.subject,
        company=company,
        location=location,
        url=f"https://www.indeed.com/viewjob?jk={job_id}",
        raw={"gmail_message_id": msg.id, "subject": msg.subject},
    )


def _guess_fields(text: str, match_pos: int) -> tuple[str, str, str]:
    """Best-effort title/company/location from the text immediately before the job link."""
    window = text[max(0, match_pos - 400) : match_pos]
    lines = [ln.strip() for ln in _TAG_OR_BREAK_RE.split(window) if ln.strip()]
    lines = lines[-3:]
    title = lines[-1] if len(lines) >= 1 else ""
    company = lines[-2] if len(lines) >= 2 else ""
    location = lines[-3] if len(lines) >= 3 else ""
    return title, company, location
