from datetime import date

from src.db import Job, connect, upsert_job
from src.retention import is_stale, parse_posted, prune, pruned_keys

TODAY = date(2026, 10, 15)


def test_parse_posted_formats():
    assert parse_posted("2026-09-21T00:00:00-0700", TODAY) == date(2026, 9, 21)
    assert parse_posted("10/06/2026", TODAY) == date(2026, 10, 6)
    assert parse_posted(1760486400000, TODAY) == date(2025, 10, 15)
    assert parse_posted("Posted Yesterday", TODAY) == date(2026, 10, 14)
    assert parse_posted("Posted 30+ Days Ago", TODAY) == date(2026, 9, 15)
    assert parse_posted("", TODAY) is None
    assert parse_posted("soon", TODAY) is None


def test_is_stale():
    assert is_stale("2026-08-01", 30, TODAY)
    assert not is_stale("2026-10-01", 30, TODAY)
    assert not is_stale(None, 30, TODAY)  # unknown date: keep for now
    assert not is_stale("2020-01-01", 0, TODAY)  # 0 turns it off


def test_prune_deletes_old_rows_keeps_applied_and_remembers(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    for ext, posted in [("old", "2026-07-01"), ("new", "2026-10-10"), ("applied", "2026-07-01"), ("nodate", None)]:
        upsert_job(conn, Job(source="t", external_id=ext, title="Data Analyst", company="C", location="Vancouver, BC", posted_date=posted))
    conn.execute("UPDATE jobs SET status = 'applied' WHERE external_id = 'applied'")
    conn.execute("UPDATE jobs SET first_seen = '2026-08-01T00:00:00+00:00' WHERE external_id = 'nodate'")

    assert prune(conn, 30, TODAY) == 2
    left = {r["external_id"] for r in conn.execute("SELECT external_id FROM jobs")}
    assert left == {"new", "applied"}
    assert pruned_keys(conn) == {("t", "old"), ("t", "nodate")}
