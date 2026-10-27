from datetime import date

from src.db import Job, connect, upsert_job
from src.retention import is_stale, parse_posted, posted_on, prune, pruned_keys

TODAY = date(2026, 10, 15)


def test_parse_posted_formats():
    assert parse_posted("2026-09-21T00:00:00-0700", TODAY) == date(2026, 9, 21)
    assert parse_posted("10/06/2026", TODAY) == date(2026, 10, 6)
    assert parse_posted("Wed, 30 Sep 2026 07:17:19 GMT", TODAY) == date(2026, 9, 30)
    assert parse_posted(1760486400000, TODAY) == date(2025, 10, 15)
    assert parse_posted("Posted Yesterday", TODAY) == date(2026, 10, 14)
    assert parse_posted("Posted 30+ Days Ago", TODAY) == date(2026, 9, 15)
    assert parse_posted("", TODAY) is None
    assert parse_posted("soon", TODAY) is None
    assert parse_posted("September 25, 2026", TODAY) == date(2026, 9, 25)  # Job Bank
    assert parse_posted("Sept 5, 2026", TODAY) == date(2026, 9, 5)
    assert parse_posted("8/27/26", TODAY) == date(2026, 8, 27)  # SuccessFactors list


def test_posted_on_falls_back_to_the_listed_date_and_counts_from_the_scrape():
    assert posted_on("2026-10-01", '{"listed_date": "8/27/26"}') == date(2026, 10, 1)
    assert posted_on(None, '{"listed_date": "8/27/26"}') == date(2026, 8, 27)
    assert posted_on("Posted Yesterday", None, TODAY) == date(2026, 10, 14)
    assert posted_on(None, '{"subject": "x"}') is None
    assert posted_on(None, None) is None


def test_a_later_alert_email_keeps_the_first_posted_date(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    email = {"gmail_message_id": "m1"}
    upsert_job(conn, Job("linkedin", "1", "Data Analyst", "C", "Vancouver, BC", posted_date="2026-10-01", raw=email))
    upsert_job(conn, Job("linkedin", "1", "Data Analyst", "C", "Vancouver, BC", posted_date="2026-10-09", raw=email))
    upsert_job(conn, Job("greenhouse", "2", "Data Analyst", "C", "Vancouver, BC", posted_date="2026-10-01"))
    upsert_job(conn, Job("greenhouse", "2", "Data Analyst", "C", "Vancouver, BC", posted_date=None))
    dates = dict(conn.execute("SELECT source, posted_date FROM jobs").fetchall())
    assert dates == {"linkedin": "2026-10-01", "greenhouse": "2026-10-01"}


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
