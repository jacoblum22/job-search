"""The Chrome task's file hand-off: queue.json out, <id>.md / <id>.fail back."""

import json

from src import browser_queue
from src.db import Job, connect, upsert_job


def _conn(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    browser_queue.ensure_schema(conn)
    for n in range(1, 5):
        upsert_job(conn, Job("linkedin", str(n), f"Data Analyst {n}", "Acme", "Vancouver, BC",
                             "snippet", url=f"https://www.linkedin.com/jobs/view/{n}"))
    conn.commit()
    return conn


def test_export_then_import_round_trip(tmp_path):
    conn = _conn(tmp_path)
    qdir = tmp_path / "queue"
    listed = browser_queue.export_queue(conn, qdir)
    payload = json.loads((qdir / "queue.json").read_text(encoding="utf-8"))
    assert payload["generated_at"] and [r["id"] for r in payload["listings"]] == [r["id"] for r in listed]
    assert sorted(r["id"] for r in listed) == [1, 2, 3, 4]

    (qdir / "1.md").write_text("A full description. " * 30, encoding="utf-8")
    (qdir / "2.fail").write_text("CAPTCHA on the page\n", encoding="utf-8")
    (qdir / "3.md").write_text("too short", encoding="utf-8")
    (qdir / "99.md").write_text("A full description. " * 30, encoding="utf-8")

    # A result not imported yet isn't queued again.
    assert sorted(r["id"] for r in browser_queue.export_queue(conn, qdir)) == [4]

    results, listings = browser_queue.sync(conn, qdir)
    assert results["saved"] == [1]
    assert results["failed"] == [(2, "CAPTCHA on the page")]
    assert [p[0] for p in results["problems"]] == [3, 99]
    assert [r["id"] for r in listings] == [4]
    assert conn.execute("SELECT length(description) FROM jobs WHERE id = 1").fetchone()[0] > 300
    assert not any(qdir.glob("*.md")) and not any(qdir.glob("*.fail"))
    assert len(list((qdir / "done").glob("*/*"))) == 4

    # Nothing left to import: a second sync is a no-op.
    results, _ = browser_queue.sync(conn, qdir)
    assert not any(results.values())


def test_cli_sync(tmp_path, capsys):
    import importlib.util
    from pathlib import Path

    conn = _conn(tmp_path)
    conn.close()
    path = Path(__file__).resolve().parent.parent / "scripts" / "browser_queue.py"
    spec = importlib.util.spec_from_file_location("browser_queue_cli", path)
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    qdir = tmp_path / "q"
    qdir.mkdir()
    (qdir / "4.fail").write_text("posting closed", encoding="utf-8")
    assert cli.main(["--db", str(tmp_path / "jobs.db"), "--queue-dir", str(qdir), "sync"]) == 0
    out = capsys.readouterr().out
    assert "1 failed" in out and "3 listing(s) queued" in out and "failed 4: posting closed" in out


def test_md_beats_an_earlier_fail(tmp_path):
    conn = _conn(tmp_path)
    qdir = tmp_path / "queue"
    qdir.mkdir()
    (qdir / "1.fail").write_text("Login required", encoding="utf-8")
    (qdir / "1.md").write_text("A full description. " * 30, encoding="utf-8")
    results = browser_queue.import_results(conn, qdir)
    assert results["saved"] == [1] and results["failed"] == []
    assert conn.execute("SELECT ok FROM enrich_attempts WHERE external_id = '1'").fetchone()[0] == 1


def test_failed_http_fetch_does_not_hold_back_a_browser_source(tmp_path):
    # The scrape's plain fetch fails on Jobright pages every few days (ok = 0);
    # that mustn't keep pushing the browser's turn back.
    conn = _conn(tmp_path)
    upsert_job(conn, Job("jobright", "j1", "Data Analyst", "Acme", "Vancouver, BC",
                         "snippet", url="https://jobright.ai/jobs/info/j1"))
    conn.execute("INSERT INTO enrich_attempts (source, external_id, attempted_at, ok) "
                 "VALUES ('jobright', 'j1', ?, 0)", (browser_queue._now().isoformat(timespec="seconds"),))
    conn.commit()
    assert "jobright" in {r["source"] for r in browser_queue.pending(conn, days=14, limit=15)}


def test_queue_reaches_the_backlog_15_per_site(tmp_path):
    # Older than 14 days still qualifies; at most 15 per site a night.
    conn = _conn(tmp_path)
    for n in range(5, 25):
        upsert_job(conn, Job("linkedin", str(n), f"Data Analyst {n}", "Acme", "Vancouver, BC",
                             "snippet", url=f"https://www.linkedin.com/jobs/view/{n}"))
    conn.execute("UPDATE jobs SET first_seen = '2026-01-01T00:00:00+00:00' WHERE external_id = '1'")
    conn.commit()
    for n in range(2, 13):
        browser_queue.fail(conn, n)
    listed = browser_queue.export_queue(conn, tmp_path / "q")
    assert len(listed) == 13 and 1 in {r["id"] for r in listed}
    for n in range(5, 25):
        upsert_job(conn, Job("linkedin", str(n + 100), "Data Analyst", "Acme", "Vancouver, BC",
                             "snippet", url=f"https://www.linkedin.com/jobs/view/{n + 100}"))
    assert len(browser_queue.export_queue(conn, tmp_path / "q")) == 15
