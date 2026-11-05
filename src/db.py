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

from src.tier import parse_min_years_experience

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
    raw TEXT,
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

    def __post_init__(self) -> None:
        # Derived from the description, not settable by adapters directly —
        # every source's description text is parsed the same way.
        self.years_experience = (
            parse_min_years_experience(self.description) if self.description else None
        )

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
    return conn


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
        conn.execute("UPDATE jobs SET last_seen = ? WHERE id = ?", (now, existing["id"]))
        return existing["id"], False

    dedup_group_id = job.dedup_group_id or f"{job.source}:{job.external_id}"
    cur = conn.execute(
        """
        INSERT INTO jobs (
            dedup_group_id, source, external_id, title, company, location,
            description, url, posted_date, first_seen, last_seen, status,
            years_experience, raw
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)
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
        result.append(
            {
                "dedup_group_id": group_id,
                "title": primary["title"],
                "company": primary["company"],
                "location": primary["location"],
                "description": primary["description"],
                "sources": sorted({m["source"] for m in members}),
                "urls": sorted({(m["source"], m["url"]) for m in members if m["url"]}),
                "status": status,
                "years_experience": years_experience,
                "tier": primary["tier"],
                "posted_date": primary["posted_date"],
                "first_seen": min(m["first_seen"] for m in members),
                "last_seen": max(m["last_seen"] for m in members),
            }
        )

    result.sort(key=lambda r: r["first_seen"], reverse=True)
    return result
