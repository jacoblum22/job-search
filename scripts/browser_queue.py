"""Queue of listings whose description has to be read in a real browser.

The scrape-time enrichment (src/enrich.py) fills snippets over plain HTTP, but
it can't open LinkedIn/Indeed/Glassdoor alert links (login-walled) and gives
up on dead Adzuna links. This script is the hand-off for a browser session
(e.g. a scheduled Claude in Chrome task) that reads those postings in Jake's
own signed-in Chrome:

    python scripts/browser_queue.py list            # JSON: what to open
    python scripts/browser_queue.py save ID FILE    # store the text read from the page
    python scripts/browser_queue.py fail ID         # page gone / no description / bot check
    python scripts/browser_queue.py dashboard       # rebuild dashboard.html afterwards

CareerJet is deliberately excluded: its links sit behind a Cloudflare bot
check, and the browser session must not be used to get past one.

Standard library only, so it runs from any Python that can see the folder.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = PROJECT_ROOT / "jobs.db"

SNIPPET_MAX_CHARS = 1000  # same threshold as src/enrich.py
MIN_FULL_CHARS = 300
BROWSER_SOURCES = ("linkedin", "indeed", "glassdoor")
RETRY_AFTER = timedelta(days=3)

ATTEMPTS_SCHEMA = """
CREATE TABLE IF NOT EXISTS enrich_attempts (
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    PRIMARY KEY (source, external_id)
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def pending(conn: sqlite3.Connection, *, days: int, limit: int) -> list[dict]:
    """Newest-first listings still holding a snippet that a browser could fill.

    Email-alert sources always qualify; Adzuna only once HTTP enrichment has
    tried and failed. Anything attempted in the last RETRY_AFTER is skipped.
    """
    since = (_now() - timedelta(days=days)).isoformat(timespec="seconds")
    retry_cutoff = (_now() - RETRY_AFTER).isoformat(timespec="seconds")
    marks = ",".join("?" * len(BROWSER_SOURCES))
    rows = conn.execute(
        f"""
        SELECT j.id, j.source, j.title, j.company, j.location, j.url,
               length(j.description) AS chars, j.first_seen
        FROM jobs j
        LEFT JOIN enrich_attempts e
          ON e.source = j.source AND e.external_id = j.external_id
        WHERE length(j.description) < ? AND j.url != '' AND j.first_seen >= ?
          AND j.status NOT IN ('expired', 'dismissed')
          AND (
                (j.source IN ({marks}) AND (e.attempted_at IS NULL OR e.attempted_at < ?))
             OR (j.source = 'adzuna' AND e.ok = 0 AND e.attempted_at < ?)
          )
        ORDER BY j.first_seen DESC
        LIMIT ?
        """,
        (SNIPPET_MAX_CHARS, since, *BROWSER_SOURCES, retry_cutoff, retry_cutoff, limit),
    ).fetchall()
    cols = ("id", "source", "title", "company", "location", "url", "chars", "first_seen")
    return [dict(zip(cols, r)) for r in rows]


def _record(conn: sqlite3.Connection, job_id: int, ok: bool) -> tuple[str, str]:
    row = conn.execute("SELECT source, external_id FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if not row:
        raise SystemExit(f"No job with id {job_id}")
    conn.execute(
        """
        INSERT INTO enrich_attempts (source, external_id, attempted_at, ok)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(source, external_id) DO UPDATE SET
            attempted_at = excluded.attempted_at, ok = excluded.ok
        """,
        (row[0], row[1], _now().isoformat(timespec="seconds"), int(ok)),
    )
    return row


def save(conn: sqlite3.Connection, job_id: int, text: str) -> bool:
    """Store a description read in the browser if it beats what's stored."""
    text = text.strip()
    if len(text) < MIN_FULL_CHARS:
        raise SystemExit(f"Description for {job_id} is only {len(text)} chars; use `fail` instead")
    _record(conn, job_id, True)
    cur = conn.execute(
        "UPDATE jobs SET description = ? WHERE id = ? AND length(description) < ?",
        (text, job_id, len(text)),
    )
    conn.commit()
    return cur.rowcount == 1


def fail(conn: sqlite3.Connection, job_id: int) -> None:
    _record(conn, job_id, False)
    conn.commit()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list", help="print pending listings as JSON")
    p_list.add_argument("--days", type=int, default=14, help="only listings first seen this recently")
    p_list.add_argument("--limit", type=int, default=15)
    p_save = sub.add_parser("save", help="store a description read from the page")
    p_save.add_argument("id", type=int)
    p_save.add_argument("file", help="text/markdown file with the description, or - for stdin")
    p_fail = sub.add_parser("fail", help="mark a listing as unreadable so it isn't retried for 3 days")
    p_fail.add_argument("id", type=int)
    sub.add_parser("dashboard", help="regenerate dashboard.html")
    args = ap.parse_args(argv)

    if args.cmd == "dashboard":
        sys.path.insert(0, str(PROJECT_ROOT))
        from src.dashboard import generate_dashboard

        conn = sqlite3.connect(args.db)
        conn.row_factory = sqlite3.Row
        try:
            print(generate_dashboard(conn, PROJECT_ROOT / "dashboard.html"))
        finally:
            conn.close()
        return 0

    conn = sqlite3.connect(args.db, timeout=30)
    conn.executescript(ATTEMPTS_SCHEMA)
    try:
        if args.cmd == "list":
            json.dump(pending(conn, days=args.days, limit=args.limit), sys.stdout, indent=2)
            print()
        elif args.cmd == "save":
            text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
            print("saved" if save(conn, args.id, text) else "kept existing (it was longer)")
        elif args.cmd == "fail":
            fail(conn, args.id)
            print("marked failed")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
