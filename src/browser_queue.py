"""Queue of listings whose description has to be read in a real browser.

The scrape-time enrichment (src/enrich.py) fills snippets over plain HTTP, but
it can't open LinkedIn/Indeed/Glassdoor alert links (login-walled) or
CareerJet links, and from any other source it queues pages the plain fetch
failed on (Adzuna, BC Public Service, Job Bank, ...). A scheduled Claude in
Chrome task reads those postings in Jake's own signed-in Chrome.

The hand-off is files only, so the Chrome task never runs a command or opens
the database (docs/browser-description-task.md). It may run in a Linux shell
with this folder mounted, which has neither the Windows .venv nor network
access to the Postgres server:

    .browser-queue/queue.json   written here: what to open (export_queue)
    .browser-queue/<id>.md      written by the task: the description it read
    .browser-queue/<id>.fail    written by the task: one line on why it couldn't

import_results() stores those files and moves them to .browser-queue/done/.
`scripts/browser_queue.py sync` does both, on the desktop: every morning from
run_tailoring.ps1, and by hand or from Task Scheduler. Not from the scrape,
which runs in Azure where this folder doesn't exist.

CareerJet links block plain HTTP fetches but open in a real browser
(4/5 in testing, 2026-10-15; added at Jake's request). The browser session
must never solve or interact with a CAPTCHA or bot check; a page that still
shows one after its own short wait is marked failed.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
QUEUE_DIR = PROJECT_ROOT / ".browser-queue"
QUEUE_FILE = "queue.json"

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
    return datetime.now(UTC)


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
        ) ranked
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
        raise ValueError(f"No job with id {job_id}")
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
        raise ValueError(f"Description for {job_id} is only {len(text)} chars; use `fail` instead")
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


def ensure_schema(conn) -> None:
    conn.executescript(ATTEMPTS_SCHEMA)


def _result_ids(queue_dir: Path) -> set[int]:
    return {int(f.stem) for f in queue_dir.glob("*") if f.suffix in (".md", ".fail") and f.stem.isdigit()}


def export_queue(conn, queue_dir: Path = QUEUE_DIR, *, days: int = 14, limit: int = 15) -> list[dict]:
    """Write queue.json for the Chrome task: what pending() lists, less any
    listing whose result file is already waiting to be imported."""
    ensure_schema(conn)
    queue_dir.mkdir(parents=True, exist_ok=True)
    waiting = _result_ids(queue_dir)
    listings = [r for r in pending(conn, days=days, limit=limit) if r["id"] not in waiting]
    payload = {"generated_at": _now().isoformat(timespec="seconds"), "listings": listings}
    tmp = queue_dir / (QUEUE_FILE + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(queue_dir / QUEUE_FILE)
    return listings


def import_results(conn, queue_dir: Path = QUEUE_DIR) -> dict[str, list]:
    """Store every <id>.md / <id>.fail the Chrome task left, then move each
    file to done/<date>/ so it's handled once. A description too short to
    count, or for a job that's gone, is recorded as a problem, not retried."""
    ensure_schema(conn)
    out: dict[str, list] = {"saved": [], "kept": [], "failed": [], "problems": []}
    files = sorted(f for f in queue_dir.glob("*") if f.suffix in (".md", ".fail") and f.stem.isdigit())
    if not files:
        return out
    done = queue_dir / "done" / _now().strftime("%Y-%m-%d")
    done.mkdir(parents=True, exist_ok=True)
    described = {f.stem for f in files if f.suffix == ".md"}
    for f in files:
        job_id = int(f.stem)
        if f.suffix == ".fail" and f.stem in described:
            # A later retry (e.g. after signing in) read it after all.
            shutil.move(str(f), str(done / f.name))
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        try:
            if f.suffix == ".md":
                out["saved" if save(conn, job_id, text) else "kept"].append(job_id)
            else:
                fail(conn, job_id)
                out["failed"].append((job_id, text.strip().splitlines()[0][:200] if text.strip() else ""))
        except ValueError as e:
            out["problems"].append((job_id, str(e)))
            if f.suffix == ".md":
                try:
                    fail(conn, job_id)
                except ValueError:
                    pass
        shutil.move(str(f), str(done / f.name))
    return out


def sync(conn, queue_dir: Path = QUEUE_DIR) -> tuple[dict[str, list], list[dict]]:
    """Import what the Chrome task wrote, then write a fresh queue."""
    results = import_results(conn, queue_dir)
    return results, export_queue(conn, queue_dir)


def summary(results: dict[str, list], listings: list[dict] | None = None) -> str:
    parts = [f"{len(results['saved'])} saved", f"{len(results['kept'])} kept (stored one longer)",
             f"{len(results['failed'])} failed", f"{len(results['problems'])} problem(s)"]
    line = "Browser queue: imported " + ", ".join(parts)
    if listings is not None:
        line += f"; {len(listings)} listing(s) queued for the Chrome task"
    return line
