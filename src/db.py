"""SQLite storage layer — the source of truth for aggregated jobs.

Per-job markdown files, the HTML dashboard, and the xlsx export are all
generated FROM this table on each run, so manual edits (e.g. marking a job
"applied") survive re-scrapes instead of being overwritten.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.experience import parse_min_years_experience
from src.location_filter import classify_location
from src.posting_status import closed_reason, due_date, seen_date
from src.reflow import reflow
from src.retention import posted_on

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
        self.description = reflow(self.description)
        self.years_experience = (
            parse_min_years_experience(self.description) if self.description else None
        )
        self.location_category = classify_location(self.location, self.company, self.description)

    @property
    def norm_key(self) -> tuple[str, str, str]:
        """Normalized (title, company, location) — used for fuzzy dedup matching."""
        return (normalize(self.title), normalize(self.company), normalize(self.location))


def normalize(s: str) -> str:
    """Lowercase + collapse whitespace, for fuzzy-matching comparisons."""
    return " ".join((s or "").lower().split())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


ROOT = Path(__file__).resolve().parent.parent
MAIN_DB = ROOT / "jobs.db"
# "postgres" in .env (or the environment) moves the main database to Postgres at
# JOBSEARCH_PG_URL (Azure plan, phase 4; docs/postgres-mirror.md). Anything else, or
# nothing, keeps it in jobs.db. scripts/pg_mirror.py cutover/rollback set and clear it.
BACKEND_ENV = "JOBSEARCH_DB"
PG_URL_ENV = "JOBSEARCH_PG_URL"
_ensured: set[str] = set()


def _env(name: str) -> str | None:
    """A setting from the environment, else from .env, read fresh each time so a running
    dashboard follows a cutover or rollback without a restart."""
    if os.environ.get(name):
        return os.environ[name]
    env = ROOT / ".env"
    if not env.exists():
        return None
    from dotenv import dotenv_values

    return dotenv_values(env).get(name) or None


def backend() -> str:
    """Where the main database lives: "postgres" or "sqlite"."""
    return "postgres" if (_env(BACKEND_ENV) or "").strip().lower() == "postgres" else "sqlite"


def is_main(db_path: str | Path) -> bool:
    """True for the project's own jobs.db path (every script's default)."""
    return Path(db_path).resolve() == MAIN_DB.resolve()


def connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the jobs database and ensure the schema exists.

    The project's jobs.db path means "the main database": with the backend set to
    postgres this opens Postgres instead (src/pgdb.py). A postgresql:// URL opens that
    database. Any other path is a SQLite file, as before (tests, backups, snapshots).
    """
    target = str(db_path)
    if target.startswith(("postgresql://", "postgres://")):
        return _connect_pg(target)
    if backend() == "postgres" and is_main(db_path):
        url = _env(PG_URL_ENV)
        if not url:
            raise RuntimeError(f"{BACKEND_ENV}=postgres but {PG_URL_ENV} is not set in .env")
        return _connect_pg(url)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _add_missing_columns(conn)
    return conn


def _connect_pg(url: str):
    import psycopg

    from src.pgdb import PgConnection

    conn = PgConnection(psycopg.connect(url, connect_timeout=20))
    # The schema is checked once per process: each statement is a round trip to Azure.
    if url not in _ensured:
        conn.executescript(SCHEMA)
        _add_missing_columns(conn)
        conn.commit()
        _ensured.add(url)
    return conn


def is_postgres(conn: Any) -> bool:
    return getattr(conn, "backend", "sqlite") == "postgres"


def table_columns(conn: Any, table: str) -> list[str]:
    """Column names of a table, in order (empty when it doesn't exist), on either backend."""
    if is_postgres(conn):
        return [r[0] for r in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ? ORDER BY ordinal_position",
            (table,))]
    return [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')]


def has_table(conn: Any, table: str) -> bool:
    if is_postgres(conn):
        sql = ("SELECT 1 FROM information_schema.tables "
               "WHERE table_schema = current_schema() AND table_name = ?")
    else:
        sql = "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?"
    return conn.execute(sql, (table,)).fetchone() is not None


# Columns added after the first release; CREATE TABLE IF NOT EXISTS won't add
# them to an existing jobs.db, so ALTER them in.
_LATER_COLUMNS = {"score": "INTEGER", "score_reasons": "TEXT"}


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    existing = set(table_columns(conn, "jobs"))
    for col, typ in _LATER_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typ}")


def upsert_job(conn: sqlite3.Connection, job: Job) -> tuple[int, bool]:
    """Insert a new job, or refresh last_seen if (source, external_id) already exists.

    Returns (row_id, was_new).
    """
    now = _now()
    existing = conn.execute(
        "SELECT id, description, posted_date FROM jobs WHERE source = ? AND external_id = ?",
        (job.source, job.external_id),
    ).fetchone()

    if existing:
        old_desc = existing["description"] or ""
        new_desc = job.description or ""
        description = new_desc if len(new_desc) >= len(old_desc) else old_desc
        # An alert email's date stands in for the posted date; a later alert for the
        # same job isn't a new posting, so it keeps the first email's date.
        posted_date = job.posted_date
        if existing["posted_date"] and (
            not posted_date or (job.raw or {}).get("gmail_message_id")
        ):
            posted_date = existing["posted_date"]
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
                posted_date,
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
        RETURNING id
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
    return cur.fetchone()[0], True


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


def grouped_jobs(conn: sqlite3.Connection, only_ids: set[int] | None = None) -> list[dict[str, Any]]:
    """Group raw job rows by dedup_group_id for display (dashboard/export).

    The same real-world posting can have multiple raw rows (one per source
    that reported it). This picks the row with the longest description as
    the primary display record per group, and aggregates which sources/URLs
    saw it. Sorted newest-first by first_seen. With `only_ids`, only the groups
    holding one of those job ids are built (the dashboard refreshing a few rows).
    """
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in all_jobs(conn):
        groups.setdefault(row["dedup_group_id"], []).append(row)
    if only_ids is not None:
        groups = {g: ms for g, ms in groups.items() if any(m["id"] in only_ids for m in ms)}

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
            m["description"] or "", seen=seen_date(m["first_seen"]), raw=m["raw"]))), None)
        # Sources can disagree; the later deadline is the safe read, as in deadline().
        due = max((d for m in members if (d := due_date(
            m["description"] or "", seen_date(m["first_seen"]), m["raw"]))), default=None)
        # When it was first posted: the earliest date any source gives, else the day we first saw it.
        posted = min((p for m in members if (p := posted_on(
            m["posted_date"], m["raw"], seen_date(m["last_seen"])))), default=None)
        first_seen = min(m["first_seen"] for m in members)
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
                "deadline": due.isoformat() if due else None,
                "years_experience": years_experience,
                "tier": primary["tier"],
                "score": primary["score"],
                "score_reasons": primary["score_reasons"],
                "posted_date": primary["posted_date"],
                "posted": posted.isoformat() if posted else first_seen[:10],
                "posted_given": posted is not None,
                "first_seen": first_seen,
                "last_seen": max(m["last_seen"] for m in members),
            }
        )

    result.sort(key=lambda r: r["first_seen"], reverse=True)
    return result


def reflow_stored(conn: sqlite3.Connection) -> int:
    """Give stored descriptions that arrived flattened onto one line their lines back
    (src/reflow.py). New rows are reflowed on the way in; this catches older ones."""
    rows = conn.execute(
        "SELECT id, description FROM jobs WHERE length(description) >= 800 "
        "AND length(description) - length(replace(description, char(10), '')) < 3"
    ).fetchall()
    changed = [(new, r[0]) for r in rows if (new := reflow(r[1])) != r[1]]
    if changed:
        conn.executemany("UPDATE jobs SET description = ? WHERE id = ?", changed)
        conn.commit()
    return len(changed)
