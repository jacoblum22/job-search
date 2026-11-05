"""Indeed job-alert email adapter.

Two senders, both read here:
- `donotreply@jobalert.indeed.com`: saved-search digests. The plaintext body
  is one block per job, blocks separated by blank lines:

      Business Applications Analyst I
      LMI Technologies - Burnaby, BC
      $60,000–$75,000 a year
      Easily apply
      <one or two sentence snippet>
      2 days ago
      https://ca.indeed.com/rc/clk/dl?jk=<job key>&...

  Sponsored jobs end in a `pagead/clk` link with no `jk`; those get an id
  hashed from title/company/location instead.
- `donotreply@match.indeed.com`: single "this job could be a match" emails.
  The job block (title, company, location, "Salary: ...") sits above a
  "View job: https://cts.indeed.com/v3/<token>/..." line. The token is
  base64url-encoded gzip JSON whose "u" field is the rc/clk?jk=... link.

The job key (`jk`) is Indeed's stable per-posting id, so it's the dedup key,
and the stored URL is the plain viewjob link built from it rather than the
tracking link from the email.

If alerts are forwarded from another inbox (see `forward_from` in
config/settings.yaml), the envelope From header becomes the forwarding
mailbox instead of Indeed's — a forwarded message can't be identified by
sender alone. The search then also matches on the original sender address,
which forwarded mail still carries as plain text (Outlook's "Forward"
action quotes the original headers in the body).

Checked against real alert and match emails on 2026-10-18 (before this the
adapter guessed fields from the three lines above each link and stored
titles like "2 days ago", so every Indeed job was dropped at ingest).
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
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

SOURCE = "indeed"
SENDER = "donotreply@jobalert.indeed.com"
MATCH_SENDER = "donotreply@match.indeed.com"
# Cursor keys in source_cursors. Renamed from "indeed" when the parser was
# fixed (2026-10-18) so the next run reads the last 30 days of alerts again;
# the old parser had dropped every job in them.
CURSOR = "indeed-v2"
MATCH_CURSOR = "indeed-match"

JK_RE = re.compile(r"[?&]jk=([0-9a-f]{8,40})")
JOB_LINK_RE = re.compile(r"^https?://\S*indeed\.com/(?:rc|pagead)/clk\S*$")
CTS_RE = re.compile(r"https?://cts\.indeed\.com/v3/([A-Za-z0-9_-]+)")
AGE_RE = re.compile(
    r"^(?:just posted|today|\d+\+? days? ago|active \d+ days? ago)$", re.IGNORECASE
)
SALARY_RE = re.compile(r"\$|\ban hour\b|\ba year\b", re.IGNORECASE)
BADGES = {
    "easily apply",
    "responsive employer",
    "urgently hiring",
    "hiring multiple candidates",
}


def fetch_indeed_jobs(
    conn: sqlite3.Connection,
    *,
    forward_from: str | None = None,
    service: Resource | None = None,
) -> list[Job]:
    """Fetch + parse new Indeed alert and match emails since the last run.

    `forward_from` is the forwarding mailbox address (config/settings.yaml's
    `email_sources.forward_from`) if alerts are relayed through another
    inbox rather than landing in Gmail directly.
    """
    messages: list[EmailMessage] = []
    for sender, cursor in ((SENDER, CURSOR), (MATCH_SENDER, MATCH_CURSOR)):
        query = f"from:{sender}"
        if forward_from:
            query = f"({query}) OR (from:{forward_from} {sender})"
        if service is not None:
            messages += fetch_new_messages(service, conn, source=cursor, query=query)
        else:
            messages += collect_alert_messages(conn, source=cursor, query=query)

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
    text = msg.plain_text
    if not text.strip() and msg.html:
        text = BeautifulSoup(msg.html, "html.parser").get_text("\n")
    if CTS_RE.search(text) and "View job:" in text:
        return _parse_match(text, msg)
    return _parse_digest(text, msg)


def _blocks(text: str) -> list[list[str]]:
    blocks, current = [], []
    for line in text.replace("\r", "").split("\n"):
        line = line.strip()
        if line:
            current.append(line)
        elif current:
            blocks.append(current)
            current = []
    if current:
        blocks.append(current)
    return blocks


def _parse_digest(text: str, msg: EmailMessage) -> list[Job]:
    jobs = []
    for block in _blocks(text):
        if len(block) < 3 or not JOB_LINK_RE.match(block[-1]):
            continue
        title, company_line, *rest = block[:-1]
        link = block[-1]
        company, _, location = company_line.rpartition(" - ")
        if not company:
            company, location = company_line, ""
        salary = next((ln for ln in rest if SALARY_RE.search(ln) and len(ln) < 60), "")
        snippet = [
            ln
            for ln in rest
            if ln != salary and ln.lower() not in BADGES and not AGE_RE.match(ln)
        ]
        jk = JK_RE.search(link)
        if jk:
            job_id = jk.group(1)
            url = f"https://ca.indeed.com/viewjob?jk={job_id}"
        else:
            # Sponsored listing: no job key in the link.
            job_id = "ad-" + _hash(title, company, location)
            url = link
        jobs.append(
            _job(job_id, title, company, location, url, salary, " ".join(snippet), msg)
        )
    return jobs


def _parse_match(text: str, msg: EmailMessage) -> list[Job]:
    jobs = []
    text = text.replace("\r", "")
    for view in re.finditer(r"^\s*View job:.*$", text, re.MULTILINE):
        token = CTS_RE.search(view.group(0))
        job_id = _jk_from_cts(token.group(1)) if token else None
        if not job_id:
            logger.warning(
                "%s: couldn't read the job key in match email %s", SOURCE, msg.id
            )
            continue
        # The job block is the nearest one above the link that isn't a
        # "Benefits:" style list or the "Hi <name>," greeting.
        block = next(
            (
                b
                for b in reversed(_blocks(text[: view.start()]))
                if not b[0].endswith(":") and not b[0].startswith("Hi ") and len(b) >= 2
            ),
            None,
        )
        if not block:
            continue
        title, company = block[0], block[1]
        location = block[2] if len(block) > 2 and ":" not in block[2] else ""
        salary = next(
            (ln.split(":", 1)[1].strip() for ln in block if ln.startswith("Salary:")),
            "",
        )
        extra = [ln for ln in block[2:] if ln.startswith("Job type:")]
        jobs.append(
            _job(
                job_id,
                title,
                company,
                location,
                f"https://ca.indeed.com/viewjob?jk={job_id}",
                salary,
                " ".join(extra),
                msg,
            )
        )
    return jobs


def _jk_from_cts(token: str) -> str | None:
    try:
        data = json.loads(
            gzip.decompress(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        )
    except (ValueError, OSError, EOFError):
        return None
    match = JK_RE.search(data.get("u", "")) if isinstance(data, dict) else None
    return match.group(1) if match else None


def _hash(*parts: str) -> str:
    return hashlib.sha1("|".join(p.lower() for p in parts).encode()).hexdigest()[:16]


def _job(
    job_id, title, company, location, url, salary, snippet, msg: EmailMessage
) -> Job:
    description = "\n\n".join(
        p for p in (f"Salary: {salary}" if salary else "", snippet) if p
    )
    return Job(
        source=SOURCE,
        external_id=job_id,
        title=title,
        company=company,
        location=location,
        url=url,
        description=description,
        posted_date=msg.internal_date.date().isoformat(),  # alerts go out within a day of posting
        raw={"gmail_message_id": msg.id, "subject": msg.subject},
    )
