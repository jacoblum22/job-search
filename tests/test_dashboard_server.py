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
from src.tailor_runner import TailoringRunner

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


def test_rows_and_details_carry_the_deadline(env):
    conn = connect(env["cfg"]["paths"]["db"])
    conn.execute("UPDATE jobs SET description = description || ? WHERE id = ?",
                 ("\nApplication deadline: December 31, 2099.", env["jid"]))
    conn.commit()
    rows = json.loads(render_dashboard(conn).split('type="application/json">')[1].split("</script>")[0])
    conn.close()
    by_title = {r["title"]: r for r in rows}
    assert by_title["Junior Analyst"]["deadline"] == "2099-12-31"
    assert by_title["Junior Analyst"]["deadline_sort"] == "2099-12-31"
    assert by_title["Data Analyst"]["deadline"] is None
    assert by_title["Data Analyst"]["deadline_sort"] > "2099-12-31"  # no deadline sorts last
    assert get(env, f"/api/job/{env['jid']}")[1]["deadline"] == "2099-12-31"
    assert get(env, f"/api/job/{env['other']}")[1]["deadline"] is None


def test_rows_carry_when_first_posted(env):
    conn = connect(env["cfg"]["paths"]["db"])
    conn.execute("UPDATE jobs SET posted_date = 'September 25, 2026' WHERE id = ?", (env["jid"],))
    conn.execute("UPDATE jobs SET posted_date = NULL, first_seen = '2026-10-20T10:00:00+00:00' WHERE id = ?",
                 (env["other"],))
    conn.commit()
    rows = json.loads(render_dashboard(conn).split('type="application/json">')[1].split("</script>")[0])
    conn.close()
    by_title = {r["title"]: r for r in rows}
    assert (by_title["Junior Analyst"]["posted"], by_title["Junior Analyst"]["posted_given"]) == ("2026-09-25", True)
    # No date in the posting: the day it was first seen, marked as such.
    assert (by_title["Data Analyst"]["posted"], by_title["Data Analyst"]["posted_given"]) == ("2026-10-20", False)
    assert get(env, f"/api/job/{env['jid']}")[1]["posted"] == "2026-09-25"
    assert get(env, f"/api/job/{env['other']}")[1]["posted"] is None


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


def test_tick_answers_with_the_new_checklist(env):
    b = next(b for b in review.parse(CHECK) if b["type"] == "item" and b["kind"] != "undo")
    before = review.open_items(CHECK)
    status, body = post(env, f"/api/job/{env['jid']}/check", {"line": b["line"], "raw": b["raw"],
                                                               "option": b["options"][0]["name"], "checked": True})
    assert status == 200
    # The page redraws from this answer alone, so it carries the whole list and the count left.
    assert body["result"]["open_items"] == before - 1
    assert any(o["checked"] for x in body["result"]["check"] if x.get("line") == b["line"] for o in x["options"])


def test_dashboard_file_rebuilt_after_the_answer(env):
    env["app"].refresh_delay = 60  # as serve.py runs it: rebuilt later, not inside the request
    out = env["tmp"] / "dashboard.html"
    assert post(env, f"/api/job/{env['other']}/status", {"status": "dismissed"})[0] == 200
    assert not out.exists()
    env["app"].flush_refresh()  # the timer (or shutdown) writes it
    assert out.exists()
    env["app"].flush_refresh()  # nothing pending: no-op
    assert env["app"]._refresh_timer is None


def test_status_for_a_job_without_application(env):
    assert post(env, f"/api/job/{env['other']}/status", {"status": "dismissed"})[0] == 200
    conn = connect(env["cfg"]["paths"]["db"])
    assert conn.execute("SELECT status FROM jobs WHERE id = ?", (env["other"],)).fetchone()[0] == "dismissed"
    conn.close()
    assert post(env, f"/api/job/{env['other']}/status", {"status": "bogus"})[0] == 409


def test_rows_endpoint_returns_only_the_changed_rows_fresh(env):
    jid, other = env["jid"], env["other"]
    assert post(env, f"/api/job/{other}/status", {"status": "dismissed"})[0] == 200
    status, data = get(env, f"/api/rows?ids={other}")
    assert status == 200 and [r["id"] for r in data["rows"]] == [other]
    assert data["rows"][0]["status"] == "dismissed" and "description" not in data["rows"][0]
    # Same shape as the rows the page was built with.
    full = json.loads(render_dashboard(connect(env["cfg"]["paths"]["db"]), server=True)
                      .split('<script id="jobs-data" type="application/json">')[1].split("</script>")[0])
    assert data["rows"][0] == next(r for r in full if r["id"] == other)
    status, data = get(env, f"/api/rows?ids={jid},{other}")
    assert sorted(r["id"] for r in data["rows"]) == sorted([jid, other])
    assert next(r for r in data["rows"] if r["id"] == jid)["app"]["status"] == "ready_for_review"
    assert get(env, "/api/rows")[0] == 400
    assert get(env, "/api/rows?ids=abc")[0] == 400
    assert get(env, "/api/rows?ids=99999")[1] == {"rows": []}


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


def test_allowed_proxy_host_works_and_others_still_refused(env):
    ts = "desktop.tail1234.ts.net"
    app = DashboardApp(env["cfg"], env["cfg"]["paths"]["db"], env["tmp"] / "dashboard.html",
                       extra_hosts=(f"https://{ts}/",))
    assert app.handle("GET", "/", {"Host": ts})[0] == 200
    proxied = {"Host": ts, "Origin": f"https://{ts}", "Content-Type": "application/json"}
    url = f"/api/job/{env['other']}/status"
    assert app.handle("POST", url, proxied, json.dumps({"status": "dismissed"}).encode())[0] == 200
    # Without --allow-host the same request is refused, and other hosts stay refused with it.
    assert env["app"].handle("GET", "/", {"Host": ts})[0] == 403
    assert app.handle("GET", "/", {"Host": "evil.ts.net"})[0] == 403
    evil = {**proxied, "Origin": "https://evil.ts.net"}
    assert app.handle("POST", url, evil, json.dumps({"status": "dismissed"}).encode())[0] == 403


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


def test_rebuilt_check_md_keeps_decisions_already_made():
    old = CHECK.replace("- [ ] Reviewed  ATS 59.0", "- [x] Reviewed  ATS 59.0").replace(
        "- [ ] Keep  - [ ] Remove  skill_only", "- [ ] Keep  - [x] Remove  skill_only")
    new = CHECK.replace("## Remaining issues", "## Remaining issues\n\n- [ ] Keep  - [ ] Remove  a new issue")
    out = review.carry_over(old, new)
    assert "- [x] Reviewed  ATS 59.0" in out
    assert "- [ ] Keep  - [x] Remove  skill_only_in_list" in out
    assert "- [ ] Keep  - [ ] Remove  a new issue" in out  # new lines start undecided


class FakeProc:
    def __init__(self):
        self.done = False

    def poll(self):
        return 0 if self.done else None


def test_run_tailoring_button_starts_one_run_at_a_time(env):
    launched = []

    def launch(root, limit):
        launched.append(limit)
        return FakeProc()

    task = {"running": False}
    (env["tmp"] / "logs").mkdir()
    (env["tmp"] / "logs" / "tailoring.log").write_text("[2026-10-27 09:40:00] Done\n", encoding="utf-8")
    runner = TailoringRunner(env["tmp"], launch=launch, task_running=lambda: task["running"])
    app = DashboardApp(env["cfg"], env["cfg"]["paths"]["db"], env["tmp"] / "dashboard.html", runner=runner)
    env = {**env, "app": app}

    assert 'id="runBox"' in get(env, "/")[1].decode()
    status, data = get(env, "/api/tailoring")
    assert status == 200 and data["running"] is False and data["last_log"] == "[2026-10-27 09:40:00] Done"
    assert post(env, "/api/tailoring", {"limit": 0})[0] == 409
    assert post(env, "/api/tailoring", {"limit": "three"})[0] == 409
    status, data = post(env, "/api/tailoring", {"limit": 3})
    assert status == 200 and data["result"]["running"] is True and data["result"]["limit"] == 3
    # A second press while it runs starts nothing.
    assert post(env, "/api/tailoring", {"limit": 2})[0] == 409
    runner._proc.done = True
    # Nor while the scheduled 9:00 task is running.
    task["running"] = True
    assert get(env, "/api/tailoring")[1]["by"] == "scheduled task"
    assert post(env, "/api/tailoring", {"limit": 2})[0] == 409
    assert launched == [3]
    # Another site can't press it.
    assert post(env, "/api/tailoring", {"limit": 1}, {**POST, "Origin": "https://evil.example"})[0] == 403


# --- folders after the repo moves -------------------------------------------


def test_folder_stored_relative_to_repo_root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    inside = tmp_path / "materials" / "applications" / "2026-10-27 VCH - Advisor"
    assert store.stored_folder(inside) == "materials/applications/2026-10-27 VCH - Advisor"
    assert store.folder_path("materials/applications/2026-10-27 VCH - Advisor") == inside
    outside = tmp_path.parent / "elsewhere"
    assert store.stored_folder(outside) == str(outside)


def test_folder_from_another_computer_is_found_under_this_root(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "ROOT", tmp_path)
    name = "2026-10-27 VCH - Advisor"
    moved = tmp_path / "materials" / "applications" / name
    moved.mkdir(parents=True)
    old = "C:\\Users\\jacob\\job-search\\materials\\applications\\" + name
    assert store.folder_path(old) == moved
    assert store.folder_path("/home/jacob/job-search/materials/applications/" + name) == moved
    # Nothing here by that name: the stored path is returned as it was.
    gone = "C:\\Users\\jacob\\job-search\\materials\\applications\\2026-01-01 Gone - Job"
    assert str(store.folder_path(gone)).endswith("2026-01-01 Gone - Job")
    assert not store.folder_path(gone).exists()


def test_details_page_reads_check_md_after_the_repo_moved(env, monkeypatch):
    """Rows written on the laptop hold C:\\Users\\jacob\\... paths; on the desktop the review page
    must still find check.md and the final files."""
    monkeypatch.setattr(store, "ROOT", env["tmp"])
    name = env["dir"].name
    moved = env["tmp"] / "materials" / "applications" / name
    moved.parent.mkdir(parents=True)
    env["dir"].rename(moved)
    conn = connect(env["cfg"]["paths"]["db"])
    store.set_status(conn, env["jid"], "ready_for_review",
                     folder="C:\\Users\\jacob\\job-search\\materials\\applications\\" + name)
    conn.close()
    status, data = get(env, f"/api/job/{env['jid']}")
    assert status == 200
    assert data["app"]["check"] is not None
    assert data["app"]["open_items"] > 0
    assert data["app"]["files"] == ["Jake Resume - VCH.pdf"]
    assert data["app"]["folder"] == str(moved)


def test_run_started_before_a_server_restart_still_counts(env):
    """The dashboard server forgets the run it started when it restarts; run_tailoring.ps1's
    run file keeps the button from starting a second run alongside it."""
    alive = {41: True}
    (env["tmp"] / "logs").mkdir()
    run_file = env["tmp"] / "logs" / "tailoring.run.json"
    run_file.write_text('﻿{"pid":41,"started":"2026-10-27T15:38:56-07:00","limit":3,"mode":"limit 3"}',
                        encoding="utf-8")
    launched = []
    runner = TailoringRunner(env["tmp"], launch=lambda root, n: launched.append(n),
                             task_running=lambda: False, pid_alive=lambda pid: alive.get(pid, False))
    app = DashboardApp(env["cfg"], env["cfg"]["paths"]["db"], env["tmp"] / "dashboard.html", runner=runner)
    env = {**env, "app": app}
    data = get(env, "/api/tailoring")[1]
    assert data["running"] is True and data["by"] == "script"
    assert data["limit"] == 3 and data["started"] == "2026-10-27T15:38:56-07:00"
    assert post(env, "/api/tailoring", {"limit": 2})[0] == 409
    # A crashed run leaves the file behind; a dead PID doesn't block the next run.
    alive[41] = False
    assert get(env, "/api/tailoring")[1]["running"] is False
    assert post(env, "/api/tailoring", {"limit": 2})[0] == 200
    assert launched == [2]


# --- daily goal ------------------------------------------------------------


def test_goal_counts_first_applied_once_in_local_day(env):
    jid = env["jid"]
    assert get(env, "/api/goal")[1] == {"done": 0, "goal": 10, "date": get(env, "/api/goal")[1]["date"]}
    status, body = post(env, f"/api/job/{jid}/outcome", {"outcome": "applied"})
    assert status == 200 and body["result"]["goal"]["done"] == 1
    # A later outcome (interview) must not move or double the count.
    post(env, f"/api/job/{jid}/outcome", {"outcome": "interview"})
    assert get(env, "/api/goal")[1]["done"] == 1


def test_goal_day_is_pacific(env):
    from datetime import datetime, timezone

    from src import goal

    conn = connect(env["cfg"]["paths"]["db"])
    conn.execute("UPDATE applications SET applied_at = '2026-10-31T03:00:00Z' WHERE job_id = ?", (env["jid"],))
    conn.commit()
    # 03:00 UTC on Oct 31 is 20:00 on Oct 30 in Vancouver.
    assert goal.applied_today(conn, env["cfg"], datetime(2026, 10, 31, 5, 0, tzinfo=timezone.utc))["done"] == 1
    assert goal.applied_today(conn, env["cfg"], datetime(2026, 10, 31, 8, 0, tzinfo=timezone.utc))["done"] == 0
    conn.close()


def test_dashboard_has_goal_bar(env):
    conn = connect(env["cfg"]["paths"]["db"])
    assert 'id="goalBar"' in render_dashboard(conn, server=True)
    conn.close()


def test_applied_at_backfilled_from_history_when_column_added(env):
    from src.tailor.packet import record_outcome

    record_outcome(env["dir"], env["cfg"], "applied")
    record_outcome(env["dir"], env["cfg"], "interview")  # outcome moved on, so only history remembers
    conn = connect(env["cfg"]["paths"]["db"])
    conn.execute("ALTER TABLE applications DROP COLUMN applied_at")
    conn.commit()
    store.ensure_table(conn)
    assert conn.execute("SELECT applied_at FROM applications WHERE job_id = ?", (env["jid"],)).fetchone()[0]
    conn.close()
