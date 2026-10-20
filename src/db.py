"""SQLite storage layer — the source of truth for aggregated jobs.

Per-job markdown files, the HTML dashboard, and the xlsx export are all
generated FROM this table on each run, so manual edits (e.g. marking a job
"applied") survive re-scrapes instead of being overwritten.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.experience import parse_min_years_experience
from src.location_filter import classify_location
from src.posting_status import closed_reason, seen_date

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_group_id TEXT NOT NULL,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    location TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    posted_date TEXT,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'new',
    tier TEXT,
    years_experience INTEGER,
    location_category TEXT,
    raw TEXT,
    score INTEGER,
    score_reasons TEXT,
    UNIQUE(source, external_id)
);

CREATE INDEX IF NOT EXISTS idx_jobs_dedup_group ON jobs(dedup_group_id);
CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS source_cursors (
    source TEXT PRIMARY KEY,
    cursor_value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


@dataclass
class Job:
    """A normalized job record produced by any source adapter."""

    source: str
    external_id: str
    title: str
    company: str
    location: str
    description: str = ""
    url: str = ""
    posted_date: str | None = None
    raw: dict[str, Any] | None = None
    dedup_group_id: str | None = None  # assigned on first insert if not set
    years_experience: int | None = field(init=False, default=None)
    location_category: str = field(init=False, default="other")

    def __post_init__(self) -> None:
        # Derived fields, not settable by adapters directly — every source's
        # location/description text is parsed the same way.
        self.years_experience = (
            parse_min_years_experience(self.description) if self.description else None
        )
        self.location_category = classify_location(self.location, self.company)

    @property
    def norm_key(self) -> tuple[str, str, str]:
        """Normalized (title, company, location) — used for fuzzy dedup matching."""
        return (normalize(self.title), normalize(self.company), normalize(self.location))


def normalize(s: str) -> str:
    """Lowercase + collapse whitespace, for fuzzy-matching comparisons."""
    return " ".join((s or "").lower().split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the jobs database and ensure the schema exists."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _add_missing_columns(conn)
    return conn


# Columns added after the first release; CREATE TABLE IF NOT EXISTS won't add
# them to an existing jobs.db, so ALTER them in.
_LATER_COLUMNS = {"score": "INTEGER", "score_reasons": "TEXT"}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    existing = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    for col, typ in _LATER_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")


def upsert_job(conn: sqlite3.Connection, job: Job) -> tuple[int, bool]:
    """Insert a new job, or refresh last_seen if (source, external_id) already exists.

    Returns (row_id, was_new).
    """
    now = _now()
    existing = conn.execute(
        "SELECT id FROM jobs WHERE source = ? AND external_id = ?",
        (job.source, job.external_id),
    ).fetchone()

    if existing:
        existing_row = conn.execute(
            "SELECT description FROM jobs WHERE id = ?", (existing["id"],)
        ).fetchone()
        old_desc = (existing_row["description"] if existing_row else "") or ""
        new_desc = job.description or ""
        description = new_desc if len(new_desc) >= len(old_desc) else old_desc
        conn.execute(
            """
            UPDATE jobs SET
                last_seen = ?,
                title = ?,
                company = ?,
                location = ?,
                description = ?,
                url = ?,
                posted_date = ?,
                years_experience = ?,
                location_category = ?,
                raw = ?
            WHERE id = ?
            """,
            (
                now,
                job.title,
                job.company,
                job.location,
                description,
                job.url,
                job.posted_date,
                job.years_experience,
                job.location_category,
                json.dumps(job.raw) if job.raw is not None else None,
                existing["id"],
            ),
        )
        return existing["id"], False

    dedup_group_id = job.dedup_group_id or f"{job.source}:{job.external_id}"
    cur = conn.execute(
        """
        INSERT INTO jobs (
            dedup_group_id, source, external_id, title, company, location,
            description, url, posted_date, first_seen, last_seen, status,
            years_experience, location_category, raw
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?, ?)
        """,
        (
            dedup_group_id,
            job.source,
            job.external_id,
            job.title,
            job.company,
            job.location,
            job.description,
            job.url,
            job.posted_date,
            now,
            now,
            job.years_experience,
            job.location_category,
            json.dumps(job.raw) if job.raw is not None else None,
        ),
    )
    assert cur.lastrowid is not None
    return cur.lastrowid, True


def get_cursor(conn: sqlite3.Connection, source: str) -> str | None:
    """Return the last-processed cursor value for a source (e.g. an email adapter)."""
    row = conn.execute(
        "SELECT cursor_value FROM source_cursors WHERE source = ?", (source,)
    ).fetchone()
    return row["cursor_value"] if row else None


def set_cursor(conn: sqlite3.Connection, source: str, value: str) -> None:
    """Persist the last-processed cursor value for a source."""
    conn.execute(
        """
        INSERT INTO source_cursors (source, cursor_value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(source) DO UPDATE SET
            cursor_value = excluded.cursor_value,
            updated_at = excluded.updated_at
        """,
        (source, value, _now()),
    )


def all_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Return every job row, newest first."""
    return conn.execute("SELECT * FROM jobs ORDER BY first_seen DESC").fetchall()


def jobs_for_dedup(conn: sqlite3.Connection, since_days: int = 45) -> list[sqlite3.Row]:
    """Return jobs first seen within the last `since_days` — the dedup candidate pool."""
    cutoff = datetime.now(timezone.utc).timestamp() - since_days * 86400
    cutoff_iso = datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat(timespec="seconds")
    return conn.execute(
        "SELECT * FROM jobs WHERE first_seen >= ? ORDER BY first_seen ASC", (cutoff_iso,)
    ).fetchall()


def set_dedup_group(conn: sqlite3.Connection, job_id: int, dedup_group_id: str) -> None:
    conn.execute("UPDATE jobs SET dedup_group_id = ? WHERE id = ?", (dedup_group_id, job_id))


_STATUS_RANK = {"new": 0, "expired": 1, "dismissed": 2, "applied": 3}


JOB_STATUSES = ("new", "applied", "dismissed", "expired")


def set_job_status(conn: sqlite3.Connection, job_id: int, status: str) -> int:
    """Set the status of a job and its duplicates from other sources; returns rows changed."""
    if status not in JOB_STATUSES:
        raise ValueError(f"status must be one of {', '.join(JOB_STATUSES)}")
    n = conn.execute(
        "UPDATE jobs SET status = ? WHERE id = ? OR dedup_group_id = "
        "(SELECT dedup_group_id FROM jobs WHERE id = ?)",
        (status, job_id, job_id),
    ).rowcount
    conn.commit()
    return n


def grouped_jobs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    """Group raw job rows by dedup_group_id for display (dashboard/export).

    The same real-world posting can have multiple raw rows (one per source
    that reported it). This picks the row with the longest description as
    the primary display record per group, and aggregates which sources/URLs
    saw it. Sorted newest-first by first_seen.
    """
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in all_jobs(conn):
        groups.setdefault(row["dedup_group_id"], []).append(row)

    result: list[dict[str, Any]] = []
    for group_id, members in groups.items():
        primary = max(members, key=lambda r: len(r["description"] or ""))
        status = max(members, key=lambda r: _STATUS_RANK.get(r["status"], 0))["status"]
        # Prefer the primary row's years_experience, but fall back to any other
        # group member's — one source's description may state it when another doesn't.
        years_experience = primary["years_experience"]
        if years_experience is None:
            years_experience = next(
                (m["years_experience"] for m in members if m["years_experience"] is not None),
                None,
            )
        closed = next((c for m in members if (c := closed_reason(
            m["description"] or "", seen=seen_date(m["first_seen"])))), None)
        result.append(
            {
                "dedup_group_id": group_id,
                "id": primary["id"],
                "ids": [m["id"] for m in members],
                "title": primary["title"],
                "company": primary["company"],
                "location": primary["location"],
                "location_category": primary["location_category"],
                "description": primary["description"],
                "sources": sorted({m["source"] for m in members}),
                "urls": sorted({(m["source"], m["url"]) for m in members if m["url"]}),
                "status": status,
                "closed": closed,
                "years_experience": years_experience,
                "tier": primary["tier"],
                "score": primary["score"],
                "score_reasons": primary["score_reasons"],
                "posted_date": primary["posted_date"],
                "first_seen": min(m["first_seen"] for m in members),
                "last_seen": max(m["last_seen"] for m in members),
            }
        )

    result.sort(key=lambda r: r["first_seen"], reverse=True)
    return result
