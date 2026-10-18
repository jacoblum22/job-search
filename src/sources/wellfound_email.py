"""Wellfound (formerly AngelList Talent) job-alert email adapter.

Source: `team@hi.wellfound.com` daily "New job: ... and N more matches"
digests. Each job card's text runs title, company, "/ <size> Employees",
an optional salary, location, "<N> years of exp", badges, an optional
"Our take" summary, and "Learn more". The company name is the one span in
the card styled with Wellfound's brand colour (#541142), which is how
cards are found.

The HTML links all go through a links.wellfound.com redirect, but the
plaintext body carries the real `wellfound.com/jobs/<id>-<slug>` links, one
"Learn more" per card in the same order, so the two are paired by position.
If the counts don't match, the job gets an id hashed from title/company and
the redirect link. Checked against a real digest on 2026-10-18.

Cards list office cities only (no remote flag). When the "Our take" summary
says the role is remote in Canada, "Remote, Canada" is added to the
location so the location filter keeps it.
"""

from __future__ import annotations

import hashlib
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

SOURCE = "wellfound"
SENDER = "team@hi.wellfound.com"
JOB_URL_RE = re.compile(r"https://wellfound\.com/jobs/(\d+)-[\w-]*")
COMPANY_STYLE_RE = re.compile(r"#541142", re.IGNORECASE)
EXP_RE = re.compile(r"^\d+\+? years? of exp$", re.IGNORECASE)
SIZE_RE = re.compile(r"^/\s*[\d,+-]+\s+Employees$", re.IGNORECASE)
REMOTE_CANADA_RE = re.compile(r"\bremote\b[^.]{0,60}\bCanada\b", re.IGNORECASE)
BADGES = {
    "Actively Hiring",
    "Growing fast",
    "B2B",
    "Growth Stage",
    "Early Stage",
    "Late Stage",
}


def fetch_wellfound_jobs(
    conn: sqlite3.Connection,
    *,
    forward_from: str | None = None,
    service: Resource | None = None,
) -> list[Job]:
    """Fetch + parse new Wellfound alert emails since the last run."""
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
    cards = []
    for company_el in soup.find_all("span", style=COMPANY_STYLE_RE):
        card = company_el
        while (
            card is not None
            and card.find("a", string=re.compile(r"Learn more")) is None
        ):
            card = card.parent
        if card is not None:
            cards.append(card)

    links: list[tuple[str, str]] = []
    for match in JOB_URL_RE.finditer(msg.plain_text or ""):
        if match.group(1) not in {job_id for job_id, _ in links}:
            links.append((match.group(1), match.group(0)))
    paired = len(links) == len(cards)
    if cards and not paired:
        logger.warning(
            "%s: %d cards but %d job links in email %s; using fallback ids",
            SOURCE,
            len(cards),
            len(links),
            msg.id,
        )

    jobs = []
    for i, card in enumerate(cards):
        pieces = [" ".join(t.split()) for t in card.stripped_strings]
        if len(pieces) < 2:
            continue
        title, company, *rest = pieces
        rest = [p for p in rest if p not in ("|", "Learn more") and p not in BADGES]
        salary = next((p for p in rest if "$" in p or "equity" in p.lower()), "")
        exp = next((p for p in rest if EXP_RE.match(p)), "")
        take = ""
        if "Our take" in rest:
            take = " ".join(rest[rest.index("Our take") + 1 :])
            rest = rest[: rest.index("Our take")]
        location = next(
            (p for p in rest if p not in (salary, exp) and not SIZE_RE.match(p)), ""
        )
        if REMOTE_CANADA_RE.search(take):
            # Cards carry no remote flag; Wellfound's own summary sometimes
            # says the role is remote in Canada.
            location = f"{location}; Remote, Canada" if location else "Remote, Canada"
        if paired:
            job_id, url = links[i]
        else:
            job_id = (
                "h-"
                + hashlib.sha1(f"{title}|{company}".lower().encode()).hexdigest()[:16]
            )
            learn_more = card.find("a", string=re.compile(r"Learn more"))
            url = learn_more.get("href", "") if learn_more else ""
        details = [f"Salary: {salary}" if salary else "", exp, take]
        jobs.append(
            Job(
                source=SOURCE,
                external_id=job_id,
                title=title,
                company=company,
                location=location,
                url=url,
                description="\n\n".join(d for d in details if d),
                raw={"gmail_message_id": msg.id, "subject": msg.subject},
            )
        )
    return jobs
