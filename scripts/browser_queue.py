"""Queue of listings whose description has to be read in a real browser.

The scrape-time enrichment (src/enrich.py) fills snippets over plain HTTP, but
it can't open LinkedIn/Indeed/Glassdoor alert links (login-walled) or
CareerJet links, and from any other source it queues pages the plain fetch
failed on (Adzuna, BC Public Service, Job Bank, ...). This script is the hand-off for a browser session
(e.g. a scheduled Claude in Chrome task) that reads those postings in Jake's
own signed-in Chrome:

    python scripts/browser_queue.py list            # JSON: what to open
    python scripts/browser_queue.py save ID FILE    # store the text read from the page
    python scripts/browser_queue.py fail ID         # page gone / no description / bot check
    python scripts/browser_queue.py dashboard       # rebuild dashboard.html afterwards

CareerJet links block plain HTTP fetches but open in a real browser
(4/5 in testing, 2026-10-15; added at Jake's request). The browser session
must never solve or interact with a CAPTCHA or bot check; a page that still
shows one after its own short wait is marked failed.

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
BROWSER_SOURCES = ("linkedin", "indeed", "glassdoor", "careerjet", "jobright", "wellfound")
RETRY_AFTER = timedelta(days=3)
# enrich_attempts.ok: 1 = filled, 0 = plain HTTP fetch failed, -1 = the
# browser couldn't read it either (retried after RETRY_AFTER).
BROWSER_FAILED = -1

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
    """Listings still holding a snippet that a browser could fill, newest
    first, at most `limit` per source so one busy site can't crowd out the
    others.

    BROWSER_SOURCES always qualify. Any other source qualifies as soon as the
    plain HTTP fetch (src/enrich.py) has failed on it. A listing the browser
    already failed on waits RETRY_AFTER.
    """
    since = (_now() - timedelta(days=days)).isoformat(timespec="seconds")
    retry_cutoff = (_now() - RETRY_AFTER).isoformat(timespec="seconds")
    marks = ",".join("?" * len(BROWSER_SOURCES))
    rows = conn.execute(
        f"""
        SELECT id, source, title, company, location, url, chars, first_seen FROM (
            SELECT j.id, j.source, j.title, j.company, j.location, j.url,
                   length(j.description) AS chars, j.first_seen,
                   ROW_NUMBER() OVER (PARTITION BY j.source ORDER BY j.first_seen DESC) AS rank
            FROM jobs j
            LEFT JOIN enrich_attempts e
              ON e.source = j.source AND e.external_id = j.external_id
            WHERE length(j.description) < ? AND j.url != '' AND j.first_seen >= ?
              AND j.status NOT IN ('expired', 'dismissed')
              AND (
                    (j.source IN ({marks}) AND (e.attempted_at IS NULL OR e.attempted_at < ?))
                 OR (j.source NOT IN ({marks})
                     AND (e.ok = 0 OR (e.ok = ? AND e.attempted_at < ?)))
              )
        )
        WHERE rank <= ?
        ORDER BY source, first_seen DESC
        """,
        (
            SNIPPET_MAX_CHARS, since,
            *BROWSER_SOURCES, retry_cutoff,
            *BROWSER_SOURCES, BROWSER_FAILED, retry_cutoff,
            limit,
        ),
    ).fetchall()
    cols = ("id", "source", "title", "company", "location", "url", "chars", "first_seen")
    return [dict(zip(cols, r)) for r in rows]


def _record(conn: sqlite3.Connection, job_id: int, ok: int) -> tuple[str, str]:
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
        (row[0], row[1], _now().isoformat(timespec="seconds"), ok),
    )
    return row


def save(conn: sqlite3.Connection, job_id: int, text: str) -> bool:
    """Store a description read in the browser if it beats what's stored."""
    text = text.strip()
    if len(text) < MIN_FULL_CHARS:
        raise SystemExit(f"Description for {job_id} is only {len(text)} chars; use `fail` instead")
    _record(conn, job_id, 1)
    cur = conn.execute(
        "UPDATE jobs SET description = ? WHERE id = ? AND length(description) < ?",
        (text, job_id, len(text)),
    )
    conn.commit()
    return cur.rowcount == 1


def fail(conn: sqlite3.Connection, job_id: int) -> None:
    _record(conn, job_id, BROWSER_FAILED)
    conn.commit()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list", help="print pending listings as JSON")
    p_list.add_argument("--days", type=int, default=14, help="only listings first seen this recently")
    p_list.add_argument("--limit", type=int, default=15, help="max listings per source")
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
