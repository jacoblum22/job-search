"""LinkedIn notifications from the phone: match, read, gate, tailor."""

import json
from datetime import UTC, datetime, timedelta

from src import browser_queue, phone_notify
from src.tailor import store
from src.db import Job, connect, upsert_job

LONG = "Responsibilities and requirements. " * 60


def _conn(tmp_path, desc="snippet", tier="A"):
    conn = connect(tmp_path / "jobs.db")
    browser_queue.ensure_schema(conn)
    store.ensure_table(conn)
    upsert_job(conn, Job("linkedin", "4489687037", "BES Continuous Improvement Jr. Analyst", "Ledcor Group Inc.",
                         "Vancouver, BC", desc, url="https://www.linkedin.com/jobs/view/4489687037"))
    upsert_job(conn, Job("linkedin", "5", "Analyst", "Other Co", "Vancouver, BC", LONG))
    conn.execute("UPDATE jobs SET tier = ?", (tier,))
    conn.commit()
    return conn


def _send(tmp_path, text, title="LinkedIn"):
    return phone_notify.record({"title": title, "text": text}, tmp_path / "inbox")


def _run(conn, tmp_path, **kw):
    started = []
    kw.setdefault("fetch", lambda ext: "")
    out = phone_notify.process(conn, {}, inbox=tmp_path / "inbox", start_tailoring=started.append,
                               priority_file=tmp_path / "priority.json", score_cfg={}, **kw)
    return out, started


def test_match_ignores_accents_suffixes_and_case(tmp_path):
    conn = _conn(tmp_path)
    job = phone_notify.find_job(conn, "Ledcor is hiring: bes continuous improvement jr analyst – apply now")
    assert job and job["external_id"] == "4489687037"
    assert phone_notify.find_job(conn, "Ledcor is hiring something else") is None
    assert phone_notify.find_job(conn, "Analyst at Another Company") is None


def test_full_description_job_is_tailored_once(tmp_path):
    conn = _conn(tmp_path, desc=LONG)
    _send(tmp_path, "You're a top applicant: BES Continuous Improvement Jr. Analyst at Ledcor")
    out, started = _run(conn, tmp_path)
    assert started == [1] and list(out.values())[0]["status"] == "tailoring"
    out, started = _run(conn, tmp_path)   # settled: not started again
    assert started == [] and out == {}


def test_short_description_is_fetched_then_tailored(tmp_path, monkeypatch):
    conn = _conn(tmp_path)
    monkeypatch.setattr("src.score.rescore_all", lambda c, cfg: {})
    _send(tmp_path, "BES Continuous Improvement Jr. Analyst at Ledcor matches your profile")
    out, started = _run(conn, tmp_path, fetch=lambda ext: LONG if ext == "4489687037" else "")
    assert started == [1]
    assert conn.execute("SELECT length(description) FROM jobs WHERE id = 1").fetchone()[0] > 1000


def test_failed_fetch_goes_to_front_of_chrome_queue(tmp_path):
    conn = _conn(tmp_path)
    _send(tmp_path, "BES Continuous Improvement Jr. Analyst at Ledcor")
    out, started = _run(conn, tmp_path)
    assert started == [] and list(out.values())[0]["status"] == "needs_description"
    assert phone_notify.read_priority(tmp_path / "priority.json") == [1]
    qdir = tmp_path / "q"
    listed = browser_queue.export_queue(conn, qdir)
    assert listed[0]["id"] == 1


def test_gate_and_cap(tmp_path):
    conn = _conn(tmp_path, desc=LONG, tier="C")
    _send(tmp_path, "BES Continuous Improvement Jr. Analyst at Ledcor")
    out, started = _run(conn, tmp_path)
    assert started == [] and "tier C" in list(out.values())[0]["why"]

    conn = _conn(tmp_path / "b" if (tmp_path / "b").mkdir() is None else tmp_path, desc=LONG)
    inbox = tmp_path / "inbox2"
    for _ in range(3):
        phone_notify.record({"text": "BES Continuous Improvement Jr. Analyst at Ledcor"}, inbox)
    started = []
    state = phone_notify.process(conn, {"phone_notify": {"daily_cap": 1}}, inbox=inbox, start_tailoring=started.append,
                                 priority_file=tmp_path / "p.json", score_cfg={}, fetch=lambda e: "")
    assert len(started) == 1
    assert sorted(s["status"] for s in state.values()) == ["over_cap", "over_cap", "tailoring"]


def test_unmatched_waits_then_drops(tmp_path):
    conn = _conn(tmp_path, desc=LONG)
    _send(tmp_path, "Data Scientist at Nowhere Inc")
    out, _ = _run(conn, tmp_path)
    assert list(out.values())[0]["status"] == "waiting"
    later = datetime.now(UTC) + timedelta(hours=25)
    out, _ = _run(conn, tmp_path, now=later)
    assert list(out.values())[0]["status"] == "dropped"


def test_busy_run_waits(tmp_path):
    conn = _conn(tmp_path, desc=LONG)
    _send(tmp_path, "BES Continuous Improvement Jr. Analyst at Ledcor")
    out, started = _run(conn, tmp_path, busy=lambda: True)
    assert started == [] and list(out.values())[0]["status"] == "queued"
    out, started = _run(conn, tmp_path)
    assert started == [1]


def test_record_needs_text(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        phone_notify.record({}, tmp_path)
    line = json.loads((tmp_path / "inbox" / "inbox.jsonl").read_text()) if (tmp_path / "inbox").exists() else None
    assert line is None
