"""Age out old postings: drop them at ingest, delete them from jobs.db, and
remember what was deleted so the next scrape doesn't bring it back.

A job's age is its posted date when the source gives one, otherwise how long
ago we first saw it. Jobs marked `applied` are never deleted. Configure with
`retention: {max_age_days: N}` in settings.yaml (0 turns it off).
"""

from __future__ import annotations

import re
import sqlite3
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime

DEFAULT_MAX_AGE_DAYS = 30
KEEP_STATUSES = ("applied",)

SCHEMA = """
CREATE TABLE IF NOT EXISTS pruned_jobs (
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    pruned_at TEXT NOT NULL,
    PRIMARY KEY (source, external_id)
);
"""

_DAYS_AGO = re.compile(r"(\d+)\+?\s+days?\s+ago", re.IGNORECASE)


def parse_posted(value: object, today: date | None = None) -> date | None:
    """Best-effort posted date from the many formats sources use.

    Handles ISO dates/timestamps, RFC 822 dates, M/D/YYYY, epoch milliseconds, and Workday's
    "Posted Today" / "Posted Yesterday" / "Posted 30+ Days Ago". None when unknown.
    """
    if value is None or value == "":
        return None
    today = today or datetime.now().astimezone().date()
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10**11 else value
        return datetime.fromtimestamp(seconds, tz=UTC).date()
    text = str(value).strip()
    if m := re.match(r"(\d{4})-(\d{2})-(\d{2})", text):
        return date(int(m[1]), int(m[2]), int(m[3]))
    if m := re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})$", text):
        return date(int(m[3]), int(m[1]), int(m[2]))
    if text.isdigit():
        return parse_posted(int(text), today)
    try:  # RFC 822, e.g. "Wed, 30 Sep 2026 07:17:19 GMT" (Adzuna, RSS feeds)
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError, IndexError):
        pass
    lower = text.lower()
    if "today" in lower or "just posted" in lower:
        return today
    if "yesterday" in lower:
        return today - timedelta(days=1)
    if m := _DAYS_AGO.search(text):
        return today - timedelta(days=int(m[1]))
    return None


def max_age_days(cfg: dict) -> int:
    return int((cfg.get("retention") or {}).get("max_age_days", DEFAULT_MAX_AGE_DAYS) or 0)


def is_stale(posted_date: object, max_days: int, today: date | None = None) -> bool:
    if max_days <= 0:
        return False
    today = today or datetime.now().astimezone().date()
    posted = parse_posted(posted_date, today)
    return posted is not None and (today - posted).days > max_days


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def pruned_keys(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    ensure_schema(conn)
    return {(r[0], r[1]) for r in conn.execute("SELECT source, external_id FROM pruned_jobs")}


def prune(conn: sqlite3.Connection, max_days: int, today: date | None = None) -> int:
    """Delete jobs older than `max_days` (posted date, else first seen) and
    record them in pruned_jobs. Returns how many rows were deleted."""
    if max_days <= 0:
        return 0
    ensure_schema(conn)
    today = today or datetime.now().astimezone().date()
    placeholders = ",".join("?" for _ in KEEP_STATUSES)
    rows = conn.execute(
        f"SELECT id, source, external_id, posted_date, first_seen FROM jobs WHERE status NOT IN ({placeholders})",
        KEEP_STATUSES,
    ).fetchall()
    stale = []
    for row in rows:
        posted = parse_posted(row["posted_date"], today) or parse_posted(row["first_seen"], today)
        if posted is not None and (today - posted).days > max_days:
            stale.append(row)
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.executemany(
        "INSERT OR IGNORE INTO pruned_jobs (source, external_id, pruned_at) VALUES (?, ?, ?)",
        [(r["source"], r["external_id"], now) for r in stale],
    )
    conn.executemany("DELETE FROM jobs WHERE id = ?", [(r["id"],) for r in stale])
    return len(stale)
