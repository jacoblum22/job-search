"""Application status on the dashboard, the local server, and check.md ticking."""

from __future__ import annotations

import json
from datetime import date

import pytest

from src.dashboard import render_dashboard
from src.db import Job, connect, upsert_job
from src.retention import delete_expired, prune
from src.server import DashboardApp
from src.tailor import TailorError, appdir, review, store
from src.tailor.paths import load_config

CHECK = """# Check

> Your review list for this application.

## Weaker fit: review before applying

- [ ] Reviewed  ATS 59.0; the best your evidence can reach is about 68.9
  - The posting asks for these and your vault doesn't show them:
    - SPSS

## Evidence set aside

- [ ] Undo  Excel: not counted from Job Application System. <!-- undo: Excel | job-search.outputs -->

## Remaining issues

- [ ] Keep  - [ ] Remove  skill_only_in_list: 'R' appears only in the skills list (skills)
"""
H = {"Host": "127.0.0.1:8765"}
POST = {**H, "Origin": "http://127.0.0.1:8765", "Content-Type": "application/json"}


@pytest.fixture
def env(tmp_path):
    cfg = load_config({"paths": {"db": str(tmp_path / "jobs.db"), "applications": str(tmp_path / "apps"),
                                 "skill_record": str(tmp_path / "skill-record.json")}})
    conn = connect(cfg["paths"]["db"])
    jid, _ = upsert_job(conn, Job("test", "a1", "Junior Analyst", "VCH", "Vancouver, BC", "SQL " * 50, "https://x/a1"))
    other, _ = upsert_job(conn, Job("test", "b1", "Data Analyst", "Acme", "Vancouver, BC", "SQL " * 50, "https://x/b1"))
    conn.execute("UPDATE jobs SET posted_date = '2026-08-01', first_seen = '2026-08-01'")
    conn.commit()
    d = tmp_path / "apps" / "2026-10-17 VCH - Junior Analyst"
    (d / "final").mkdir(parents=True)
    (d / "final" / "Jake Resume - VCH.pdf").write_bytes(b"%PDF-1.4")
    (d / "check.md").write_text(CHECK, encoding="utf-8")
    appdir.write_json(d / "app.json", {"job_id": jid, "status": "ready_for_review", "history": []})
    store.ensure_table(conn)
    store.upsert_app(conn, {"job_id": jid, "status": "ready_for_review"}, d)
    store.set_status(conn, jid, "ready_for_review", review_flags=json.dumps(["weaker_fit"]))
    conn.close()
    app = DashboardApp(cfg, cfg["paths"]["db"], tmp_path / "dashboard.html")
    return {"cfg": cfg, "jid": jid, "other": other, "dir": d, "app": app, "tmp": tmp_path}


def get(env, path):
    status, ctype, body = env["app"].handle("GET", path, H)
    return status, json.loads(body) if ctype == "application/json" else body


def post(env, path, data, headers=POST):
    status, _, body = env["app"].handle("POST", path, headers, json.dumps(data).encode())
    return status, json.loads(body)


# --- check.md -------------------------------------------------------------


def test_parse_and_open_items():
    blocks = review.parse(CHECK)
    items = [b for b in blocks if b["type"] == "item"]
    assert [b["kind"] for b in items] == ["reviewed", "undo", "keep_remove"]
    assert items[0]["details"] == [{"text": "The posting asks for these and your vault doesn't show them:", "level": 1},
                                   {"text": "SPSS", "level": 2}]
    assert items[1]["text"] == "Excel: not counted from Job Application System."  # the machine key is hidden
    assert blocks[1] == {"type": "note", "text": "Your review list for this application."}
    assert [o["name"] for o in items[2]["options"]] == ["Keep", "Remove"]
    assert review.open_items(CHECK) == 2  # Undo is optional


def test_set_aside_or_undo_is_required_and_can_only_be_swapped():
    text = "- [ ] Set aside  - [ ] Undo  Excel: not counted. <!-- undo: Excel | job-search.outputs -->\n"
    item = review.parse(text)[0]
    assert item["kind"] == "drop" and item["text"] == "Excel: not counted."
    assert review.open_items(text) == 1
    text = review.set_box(text, 0, item["raw"], "Undo", True)
    assert text.startswith("- [ ] Set aside  - [x] Undo") and review.open_items(text) == 0
    with pytest.raises(TailorError, match="instead"):
        review.set_box(text, 0, text.rstrip("\n"), "Undo", False)  # a pick can't be cleared
    text = review.set_box(text, 0, text.rstrip("\n"), "Set aside", True)
    assert text.startswith("- [x] Set aside  - [ ] Undo")


def test_keep_and_remove_are_exclusive_and_stale_lines_refused():
    item = [b for b in review.parse(CHECK) if b["type"] == "item"][2]
    text = review.set_box(CHECK, item["line"], item["raw"], "Keep", True)
    assert "- [x] Keep  - [ ] Remove  skill_only" in text
    line = text.splitlines()[item["line"]]
    text = review.set_box(text, item["line"], line, "Remove", True)
    assert "- [ ] Keep  - [x] Remove  skill_only" in text
    with pytest.raises(TailorError, match="changed since"):
        review.set_box(text, item["line"], item["raw"], "Keep", True)


# --- dashboard ------------------------------------------------------------


def test_dashboard_shows_application_status_and_flags(env):
    conn = connect(env["cfg"]["paths"]["db"])
    html = render_dashboard(conn)
    conn.close()
    rows = json.loads(html.split('type="application/json">')[1].split("</script>")[0])
    by_title = {r["title"]: r for r in rows}
    app = by_title["Junior Analyst"]["app"]
    assert app["label"] == "Ready for review" and app["flags"] == ["Weaker fit"]
    assert app["final_href"].startswith("file:") and app["check_href"].endswith("check.md")
    assert by_title["Data Analyst"]["app"] is None
    assert by_title["Junior Analyst"]["pin"] == 1 and by_title["Data Analyst"]["pin"] == 99
    assert "const SERVER = false;" in html and "description" not in rows[0]


def test_closed_postings_are_marked_and_not_pinned(env):
    conn = connect(env["cfg"]["paths"]["db"])
    conn.execute("UPDATE jobs SET description = description || ? WHERE id = ?",
                 ("\nThis position will be filled internally.", env["jid"]))
    conn.commit()
    rows = json.loads(render_dashboard(conn).split('type="application/json">')[1].split("</script>")[0])
    conn.close()
    by_title = {r["title"]: r for r in rows}
    assert by_title["Junior Analyst"]["closed"] == "Filled internally"
    assert by_title["Junior Analyst"]["pin"] == 99  # ready for review, but it can't be sent
    assert by_title["Data Analyst"]["closed"] is None
    assert get(env, f"/api/job/{env['jid']}")[1]["closed"] == "Filled internally"
    assert get(env, f"/api/job/{env['other']}")[1]["closed"] is None


# --- retention ------------------------------------------------------------


def test_jobs_with_an_application_survive_cleanup(env):
    conn = connect(env["cfg"]["paths"]["db"])
    assert prune(conn, 30, today=date(2026, 10, 18)) == 1  # only the job without an application
    assert delete_expired(conn, {("test", "a1")}) == 0
    assert conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 1
    conn.close()


# --- server ---------------------------------------------------------------


def test_details_and_files(env):
    status, data = get(env, f"/api/job/{env['jid']}")
    assert status == 200 and data["app"]["files"] == ["Jake Resume - VCH.pdf"]
    assert data["app"]["open_items"] == 2 and data["job"]["company"] == "VCH"
    status, body = get(env, f"/job/{env['jid']}/file/Jake%20Resume%20-%20VCH.pdf")
    assert status == 200 and body == b"%PDF-1.4"
    assert get(env, f"/job/{env['jid']}/file/..%2Fcheck.md")[0] == 404
    assert get(env, f"/job/{env['jid']}/file/app.json")[0] == 404  # not in final/
    status, data = get(env, f"/api/job/{env['other']}")
    assert status == 200 and data["app"] is None


def test_tick_approve_and_apply(env):
    jid = env["jid"]
    status, data = post(env, f"/api/job/{jid}/approve", {})
    assert status == 409 and "still need a decision" in data["error"]
    for b in [b for b in review.parse(CHECK) if b["type"] == "item" and b["kind"] != "undo"]:
        opt = b["options"][0]["name"]
        assert post(env, f"/api/job/{jid}/check", {"line": b["line"], "raw": b["raw"], "option": opt,
                                                   "checked": True})[0] == 200
    assert post(env, f"/api/job/{jid}/approve", {})[0] == 200
    assert post(env, f"/api/job/{jid}/outcome", {"outcome": "applied"})[0] == 200
    conn = connect(env["cfg"]["paths"]["db"])
    assert store.get_app(conn, jid)["status"] == "applied"
    assert conn.execute("SELECT status FROM jobs WHERE id = ?", (jid,)).fetchone()[0] == "applied"
    conn.close()
    assert (env["tmp"] / "dashboard.html").exists()  # the file version is kept current


def test_status_for_a_job_without_application(env):
    assert post(env, f"/api/job/{env['other']}/status", {"status": "dismissed"})[0] == 200
    conn = connect(env["cfg"]["paths"]["db"])
    assert conn.execute("SELECT status FROM jobs WHERE id = ?", (env["other"],)).fetchone()[0] == "dismissed"
    conn.close()
    assert post(env, f"/api/job/{env['other']}/status", {"status": "bogus"})[0] == 409


def test_needs_fixes_cannot_be_approved(env):
    appdir.log(env["dir"], "packet", status="needs_fixes")
    text = CHECK.replace("[ ]", "[x]")
    (env["dir"] / "check.md").write_text(text.replace("[x] Remove", "[ ] Remove"), encoding="utf-8")
    status, data = post(env, f"/api/job/{env['jid']}/approve", {})
    assert status == 409 and "critical" in data["error"]


def test_other_sites_cannot_change_anything(env):
    url = f"/api/job/{env['other']}/status"
    assert post(env, url, {"status": "dismissed"}, {**POST, "Origin": "https://evil.example"})[0] == 403
    assert post(env, url, {"status": "dismissed"}, {**POST, "Content-Type": "text/plain"})[0] == 415
    assert post(env, url, {"status": "dismissed"}, {**POST, "Host": "evil.example:8765"})[0] == 403
    no_origin = {k: v for k, v in POST.items() if k != "Origin"}
    assert post(env, url, {"status": "dismissed"}, no_origin)[0] == 403


PICKS = """# Check

## Evidence set aside

- [x] Set aside  - [ ] Undo  Excel: not counted from Job Application System. <!-- undo: Excel | job-search.outputs -->

## Evidence the plan added

- [ ] Doesn't show it  - [ ] This shows it  ETL/ELT: counted from AlgaeCal. <!-- confirm: etl/elt | algaecal.apps-script -->
"""


def test_evidence_picks_are_saved_when_pressed_not_only_on_approve(env):
    from src.tailor import rejects
    cfg, jid = env["cfg"], env["jid"]
    path = env["tmp"] / "skill-record.json"
    path.write_text(json.dumps({"has": [], "lacks": [], "not_shown": [
        {"term": "Excel", "passage": "job-search.outputs", "reason": "names the tool only"}]}), encoding="utf-8")
    (env["dir"] / "check.md").write_text(PICKS, encoding="utf-8")

    def press(kind, option):
        b = next(b for b in review.parse((env["dir"] / "check.md").read_text(encoding="utf-8"))
                 if b["type"] == "item" and b["kind"] == kind)
        assert post(env, f"/api/job/{jid}/check", {"line": b["line"], "raw": b["raw"], "option": option,
                                                   "checked": True})[0] == 200

    def record():
        return json.loads(path.read_text(encoding="utf-8"))

    press("drop", "Undo")
    assert record()["not_shown"][0].get("undone") is True
    assert ("excel", "job-search.outputs") in rejects.confirmed(cfg)
    press("drop", "Set aside")  # changed my mind: the reject is back, the confirm gone
    assert not record()["not_shown"][0].get("undone")
    assert ("excel", "job-search.outputs") not in rejects.confirmed(cfg)

    press("confirm", "This shows it")
    assert ("etl/elt", "algaecal.apps-script") in rejects.confirmed(cfg)
    press("confirm", "Doesn't show it")
    assert ("etl/elt", "algaecal.apps-script") not in rejects.confirmed(cfg)
    assert ("etl/elt", "algaecal.apps-script") in rejects.pairs(cfg)


def test_a_dismissed_application_is_not_pinned(env):
    assert post(env, f"/api/job/{env['jid']}/status", {"status": "dismissed"})[0] == 200
    conn = connect(env["cfg"]["paths"]["db"])
    rows = json.loads(render_dashboard(conn).split('type="application/json">')[1].split("</script>")[0])
    conn.close()
    assert {r["title"]: r for r in rows}["Junior Analyst"]["pin"] == 99
