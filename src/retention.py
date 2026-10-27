"""Age out old postings: drop them at ingest, delete them from jobs.db, and
remember what was deleted so the next scrape doesn't bring it back.

A job's age is its posted date when the source gives one, otherwise how long
ago we first saw it. Postings whose link answers 404/410 are deleted the same
way as soon as src/enrich.py sees it. Jobs marked `applied`, and jobs with a tailoring
application, are never deleted. Configure with
`retention: {max_age_days: N}` in settings.yaml (0 turns it off).
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import UTC, date, datetime, timedelta
from email.utils import parsedate_to_datetime

DEFAULT_MAX_AGE_DAYS = 30
KEEP_STATUSES = ("applied",)


def kept_clause(conn: sqlite3.Connection) -> str:
    """SQL to add to a `WHERE` on jobs so jobs with a tailoring application
    (src/tailor/store.py) are never deleted, whatever their status."""
    has_apps = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'applications'"
    ).fetchone()
    return " AND id NOT IN (SELECT job_id FROM applications)" if has_apps else ""

SCHEMA = """
CREATE TABLE IF NOT EXISTS pruned_jobs (
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    pruned_at TEXT NOT NULL,
    PRIMARY KEY (source, external_id)
);
"""

_DAYS_AGO = re.compile(r"(\d+)\+?\s+days?\s+ago", re.IGNORECASE)
_MONTH_NAME_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y")


def parse_posted(value: object, today: date | None = None) -> date | None:
    """Best-effort posted date from the many formats sources use.

    Handles ISO dates/timestamps, RFC 822 dates, M/D/YYYY and M/D/YY, "September 25, 2026",
    epoch milliseconds, and Workday's "Posted Today" / "Posted Yesterday" /
    "Posted 30+ Days Ago". None when unknown.
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
    if m := re.match(r"(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})$", text):
        year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)  # SuccessFactors lists "8/27/26"
        return date(year, int(m[1]), int(m[2]))
    if text.isdigit():
        return parse_posted(int(text), today)
    try:  # RFC 822, e.g. "Wed, 30 Sep 2026 07:17:19 GMT" (Adzuna, RSS feeds)
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError, IndexError):
        pass
    for fmt in _MONTH_NAME_FORMATS:  # Job Bank: "September 25, 2026"
        try:
            return datetime.strptime(text.replace("Sept ", "Sep "), fmt).date()
        except ValueError:
            pass
    lower = text.lower()
    if "today" in lower or "just posted" in lower:
        return today
    if "yesterday" in lower:
        return today - timedelta(days=1)
    if m := _DAYS_AGO.search(text):
        return today - timedelta(days=int(m[1]))
    return None


def posted_on(posted_date: object, raw: object = None, seen: date | None = None) -> date | None:
    """The day a posting says it went up: its posted date, else the listed date some
    sources keep in raw (SuccessFactors list pages). Relative wordings ("Posted
    Yesterday") count back from `seen`, the day that wording was scraped. None when
    the posting gives no date.
    """
    if (day := parse_posted(posted_date, seen)) is not None:
        return day
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return None
    if isinstance(raw, dict):
        return parse_posted(raw.get("listed_date"), seen)
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
        f"SELECT id, source, external_id, posted_date, first_seen FROM jobs WHERE status NOT IN ({placeholders})"
        + kept_clause(conn),
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


def delete_expired(conn: sqlite3.Connection, keys: set[tuple[str, str]]) -> int:
    """Delete jobs whose posting is confirmed gone (404/410) and tombstone them
    so no later scrape brings them back. Applied jobs are kept (and not
    tombstoned). Keys not in jobs.db yet are still tombstoned. Returns how
    many rows were deleted."""
    if not keys:
        return 0
    ensure_schema(conn)
    placeholders = ",".join("?" for _ in KEEP_STATUSES)
    keep = {
        (r[0], r[1])
        for r in conn.execute(
            f"SELECT source, external_id FROM jobs WHERE NOT (status NOT IN ({placeholders}){kept_clause(conn)})",
            KEEP_STATUSES,
        )
    }
    gone = [k for k in keys if k not in keep]
    now = datetime.now(UTC).isoformat(timespec="seconds")
    conn.executemany(
        "INSERT OR IGNORE INTO pruned_jobs (source, external_id, pruned_at) VALUES (?, ?, ?)",
        [(s, e, now) for s, e in gone],
    )
    deleted = 0
    for source, external_id in gone:
        deleted += conn.execute(
            "DELETE FROM jobs WHERE source = ? AND external_id = ?", (source, external_id)
        ).rowcount
    return deleted
