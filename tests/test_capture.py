"""Job links captured from web pages by the Job Autofill extension (src/capture.py)."""

from __future__ import annotations

import json

import pytest

from src import capture
from src.db import Job, connect, upsert_job
from src.retention import ensure_schema
from src.server import DashboardApp
from src.tailor.paths import load_config

H = {"Host": "127.0.0.1:8765", "Origin": "chrome-extension://abcdef", "Content-Type": "application/json"}


@pytest.fixture
def env(tmp_path, monkeypatch):
    cfg = load_config({"paths": {"db": str(tmp_path / "jobs.db"), "applications": str(tmp_path / "apps")}})
    conn = connect(cfg["paths"]["db"])
    upsert_job(conn, Job("linkedin", "3912345678", "Data Analyst", "Acme Corp", "Vancouver, BC", "", "https://www.linkedin.com/jobs/view/3912345678/"))
    upsert_job(conn, Job("greenhouse:acme", "555", "Junior Data Scientist", "Acme Corp", "Vancouver, BC", "SQL " * 400, "https://boards.greenhouse.io/acme/jobs/555"))
    ensure_schema(conn)
    conn.commit()
    conn.close()
    # Nothing here may touch the network or the real settings' scoring inputs.
    monkeypatch.setattr(capture, "enrich_descriptions", lambda jobs, **kw: None)
    app = DashboardApp(cfg, cfg["paths"]["db"], tmp_path / "dashboard.html")
    app.capture_inline = True
    return {"app": app, "db": cfg["paths"]["db"]}


def post(env, jobs, page="https://www.linkedin.com/jobs/"):
    status, _, body = env["app"].handle("POST", "/api/autofill/capture", H, json.dumps({"page": page, "jobs": jobs}).encode())
    return status, json.loads(body)


def test_classify_keeps_each_boards_own_id():
    assert capture.classify("https://www.linkedin.com/jobs/view/data-analyst-at-acme-3912345678?trk=x").external_id == "3912345678"
    t = capture.classify("https://www.linkedin.com/jobs/collections/recommended/?currentJobId=3999999999")
    assert (t.source, t.external_id, t.url) == ("linkedin", "3999999999", "https://www.linkedin.com/jobs/view/3999999999/")
    assert capture.classify("https://ca.indeed.com/rc/clk?jk=0123456789abcdef&fccid=1").external_id == "0123456789abcdef"
    assert capture.classify("https://www.glassdoor.ca/Job/x-JV.htm?jl=1009876543210").external_id == "1009876543210"
    t = capture.classify("https://job-boards.greenhouse.io/acme/jobs/777?gh_src=abc")
    assert (t.source, t.external_id) == ("greenhouse:acme", "777")
    t = capture.classify("https://jobs.lever.co/acme/123e4567-e89b-12d3-a456-426614174000/apply")
    assert t.source == "lever:acme"
    assert capture.classify("javascript:void(0)") is None
    assert capture.classify("https://www.linkedin.com/company/acme/") is None


def test_unknown_sites_are_web_and_tracking_params_do_not_make_a_new_job():
    a = capture.classify("https://careers.example.com/jobs/data-analyst-12?utm_source=x&gclid=1")
    b = capture.classify("https://www.careers.example.com/jobs/data-analyst-12/")
    assert a.source == "web" and a.external_id == b.external_id
    assert capture.classify("https://careers.example.com/jobs?jobId=1").external_id != capture.classify("https://careers.example.com/jobs?jobId=2").external_id


def test_stored_new_and_skipped_are_told_apart(env):
    status, data = post(env, [
        {"url": "https://www.linkedin.com/jobs/view/3912345678/", "title": "Data Analyst", "company": "Acme Corp"},  # same source id
        {"url": "https://jobs.lever.co/zeta/123e4567-e89b-12d3-a456-426614174000", "title": "Junior Data Analyst", "company": "Zeta", "location": "Vancouver, BC"},
        {"url": "https://boards.greenhouse.io/acme/jobs/999", "title": "Junior Data Scientist", "company": "Acme Corp"},  # same posting, other id
        {"url": "https://www.linkedin.com/jobs/view/4000000001/", "title": "Dental Hygienist", "company": "Smile Co", "location": "Vancouver, BC"},
        {"url": "https://www.linkedin.com/company/acme/", "title": "Acme"},
    ])
    assert status == 200
    s = [r["status"] for r in data["results"]]
    assert s == ["in_dashboard", "added", "in_dashboard", "skipped", "skipped"]
    assert data["results"][3]["reason"] == "title not relevant"
    assert data["counts"] == {"in_dashboard": 2, "added": 1, "skipped": 2}
    conn = connect(env["db"])
    row = conn.execute("SELECT source, company, status FROM jobs WHERE title = 'Junior Data Analyst'").fetchone()
    assert (row[0], row[1]) == ("lever:zeta", "Zeta")
    assert conn.execute("SELECT count(*) FROM jobs").fetchone()[0] == 3


def test_second_capture_of_the_same_links_adds_nothing(env):
    link = {"url": "https://careers.example.com/jobs/data-analyst-12", "title": "Data Analyst", "company": "Example", "location": "Vancouver, BC"}
    assert post(env, [link])[1]["counts"] == {"added": 1}
    assert post(env, [dict(link, url=link["url"] + "?utm_source=x")])[1]["counts"] == {"in_dashboard": 1}


def test_closed_earlier_is_not_readded(env):
    conn = connect(env["db"])
    conn.execute("INSERT INTO pruned_jobs (source, external_id, pruned_at) VALUES ('linkedin', '4000000002', '2026-01-01')")
    conn.commit()
    conn.close()
    _, data = post(env, [{"url": "https://www.linkedin.com/jobs/view/4000000002/", "title": "Data Analyst", "company": "Beta", "location": "Vancouver, BC"}])
    assert data["results"][0]["status"] == "skipped" and "removed earlier" in data["results"][0]["reason"]


def test_a_page_description_is_kept_and_new_rows_are_scored(env):
    desc = "Build dashboards in SQL and Python. " * 40
    _, data = post(env, [{"url": "https://careers.example.com/jobs/ds-1", "title": "Data Scientist", "company": "Example", "location": "Vancouver, BC", "description": desc}])
    jid = data["results"][0]["job_id"]
    conn = connect(env["db"])
    row = conn.execute("SELECT description, score, tier FROM jobs WHERE id = ?", (jid,)).fetchone()
    assert row[0].startswith("Build dashboards") and row[1] is not None and row[2]


def test_only_the_extension_or_the_dashboard_may_post(env):
    status, _, _ = env["app"].handle("POST", "/api/autofill/capture", {**H, "Origin": "https://evil.example"}, b'{"jobs": []}')
    assert status == 403
    assert post(env, "nope")[0] == 400
