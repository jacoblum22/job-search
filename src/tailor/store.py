"""The `applications` table in jobs.db: one row per tailored application folder.

app.json is the full record; the table mirrors the fields worth querying (status,
tier, outcome) so the dashboard and the queue can see them without opening folders.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from src.tailor.appdir import now

SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    job_id INTEGER PRIMARY KEY,
    folder TEXT NOT NULL,
    status TEXT NOT NULL,
    tier TEXT,
    score REAL,
    gate_flags TEXT,
    flagged INTEGER NOT NULL DEFAULT 0,
    queue_rank INTEGER,
    base_id TEXT,
    created_at TEXT,
    updated_at TEXT,
    outcome TEXT,
    outcome_at TEXT,
    review_flags TEXT
);
"""

# Columns added after the first release; ensure_table adds them to older databases.
_ADDED_COLUMNS = {"review_flags": "TEXT"}

_SETTABLE = {
    "folder", "status", "tier", "score", "gate_flags", "flagged", "queue_rank",
    "base_id", "created_at", "outcome", "outcome_at", "review_flags",
}


def connect(db_path: str | Path) -> sqlite3.Connection:
    """The jobs.db connection (via src.db) with the applications table ensured."""
    from src.db import connect as db_connect

    conn = db_connect(db_path)
    ensure_table(conn)
    return conn


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    have = {r[1] for r in conn.execute("PRAGMA table_info(applications)")}
    for col, kind in _ADDED_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE applications ADD COLUMN {col} {kind}")
    conn.commit()


def has_table(conn: sqlite3.Connection) -> bool:
    """True when jobs.db has an applications table (the dashboard and retention never create it)."""
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'applications'"
    ).fetchone() is not None


def all_apps(conn: sqlite3.Connection) -> dict[int, dict[str, Any]]:
    """Every application row by job id; empty when the table doesn't exist yet."""
    if not has_table(conn):
        return {}
    cur = conn.execute("SELECT * FROM applications")
    cols = [d[0] for d in cur.description]
    out = {}
    for r in cur.fetchall():
        row = dict(zip(cols, r, strict=True))
        row["gate_flags"] = json.loads(row.get("gate_flags") or "[]")
        row["review_flags"] = json.loads(row.get("review_flags") or "[]")
        out[row["job_id"]] = row
    return out


def mark_applied(conn: sqlite3.Connection, job_id: int) -> None:
    """Set jobs.status = 'applied' on the job and its duplicates from other sources,
    so the dashboard shows it and retention keeps it."""
    from src.db import set_job_status

    set_job_status(conn, job_id, "applied")


def upsert_app(conn: sqlite3.Connection, app: dict[str, Any], folder: Path) -> None:
    """Insert or refresh the row for `app` (an app.json dict). Keeps any recorded outcome."""
    gate = app.get("gate") or {}
    row = {
        "job_id": app["job_id"],
        "folder": str(folder),
        "status": app.get("status", "shortlisted"),
        "tier": app.get("tier"),
        "score": app.get("score"),
        "gate_flags": json.dumps(gate.get("flags") or []),
        "flagged": int(bool(gate.get("flagged"))),
        "queue_rank": gate.get("queue_rank"),
        "base_id": app.get("base_id"),
        "created_at": app.get("created"),
        "updated_at": now(),
    }
    cols = ", ".join(row)
    marks = ", ".join(f":{c}" for c in row)
    updates = ", ".join(f"{c} = excluded.{c}" for c in row if c not in ("job_id", "created_at"))
    conn.execute(
        f"INSERT INTO applications ({cols}) VALUES ({marks}) "
        f"ON CONFLICT(job_id) DO UPDATE SET {updates}",
        row,
    )
    conn.commit()


def get_app(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    if r is None:
        return None
    out = dict(r)
    out["gate_flags"] = json.loads(out["gate_flags"] or "[]")
    out["review_flags"] = json.loads(out.get("review_flags") or "[]")
    return out


def set_status(conn: sqlite3.Connection, job_id: int, status: str, **fields: Any) -> None:
    """Update status (and any other known column) for one application; no-op if absent."""
    bad = set(fields) - _SETTABLE
    if bad:
        raise ValueError(f"unknown applications columns: {sorted(bad)}")
    fields["status"] = status
    fields["updated_at"] = now()
    sets = ", ".join(f"{c} = :{c}" for c in fields)
    conn.execute(f"UPDATE applications SET {sets} WHERE job_id = :job_id", {**fields, "job_id": job_id})
    conn.commit()
