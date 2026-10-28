"""Hand-off for the Claude in Chrome task that reads descriptions the scrape
couldn't get (see src/browser_queue.py and docs/browser-description-task.md).

    python scripts/browser_queue.py sync            # import the task's files, write a fresh queue.json
    python scripts/browser_queue.py export          # write .browser-queue/queue.json only
    python scripts/browser_queue.py import          # store .browser-queue/<id>.md / <id>.fail only
    python scripts/browser_queue.py list            # JSON: what to open
    python scripts/browser_queue.py save ID FILE    # store the text read from the page
    python scripts/browser_queue.py fail ID         # page gone / no description / bot check
    python scripts/browser_queue.py dashboard       # rebuild dashboard.html afterwards

The Chrome task itself only reads queue.json and writes files; it never runs
these commands. They need this folder's Windows .venv and the database (on
the desktop, Postgres only answers from its own IP).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.browser_queue import (  # noqa: F401  (re-exported for tests)
    BROWSER_SOURCES,
    QUEUE_DIR,
    ensure_schema,
    export_queue,
    fail,
    import_results,
    pending,
    save,
    summary,
    sync,
)
from src.db import connect

DEFAULT_DB = PROJECT_ROOT / "jobs.db"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB)
    ap.add_argument("--queue-dir", type=Path, default=QUEUE_DIR)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="import the Chrome task's files, then write a fresh queue.json")
    sub.add_parser("export", help="write .browser-queue/queue.json")
    sub.add_parser("import", help="store the Chrome task's <id>.md / <id>.fail files")
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

    conn = connect(args.db)
    try:
        if args.cmd == "dashboard":
            from src.dashboard import generate_dashboard

            print(generate_dashboard(conn, PROJECT_ROOT / "dashboard.html"))
            return 0
        ensure_schema(conn)
        if args.cmd in ("sync", "import"):
            results = import_results(conn, args.queue_dir)
            listings = export_queue(conn, args.queue_dir) if args.cmd == "sync" else None
            print(summary(results, listings))
            for job_id, why in results["failed"]:
                print(f"  failed {job_id}: {why}")
            for job_id, why in results["problems"]:
                print(f"  problem {job_id}: {why}")
        elif args.cmd == "export":
            print(f"{len(export_queue(conn, args.queue_dir))} listing(s) written to {args.queue_dir / 'queue.json'}")
        elif args.cmd == "list":
            json.dump(pending(conn, days=args.days, limit=args.limit), sys.stdout, indent=2)
            print()
        elif args.cmd == "save":
            text = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
            try:
                print("saved" if save(conn, args.id, text) else "kept existing (it was longer)")
            except ValueError as e:
                raise SystemExit(str(e)) from e
        elif args.cmd == "fail":
            try:
                fail(conn, args.id)
            except ValueError as e:
                raise SystemExit(str(e)) from e
            print("marked failed")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
