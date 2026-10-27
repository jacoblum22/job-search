import json
from pathlib import Path

import pytest

from src.db import Job, connect, upsert_job
from src.tailor import TailorError, appdir, store
from src.tailor.jev import FakeJev
from src.tailor.packet import approve, record_outcome, run_packet
from src.tailor.paths import load_config
from src.tailor.queue import GATE_QUESTIONS, run_queue

DESC = "SQL and dashboards for the analytics team. " * 40
GOOD = {"seniority_fit": 3, "must_haves": 3, "domain_fit": 3, "location_ok": 0.9,
        "requires_phd": 0.1, "years_ok": 0.9, "is_coop": 0.1}


@pytest.fixture
def cfg(tmp_path):
    return load_config({"paths": {
        "db": str(tmp_path / "jobs.db"),
        "applications": str(tmp_path / "apps"),
        "bases": str(tmp_path / "bases"),
    }, "tiers": ["A", "B"], "rescore_before_queue": False})


def add(cfg, ext, title, tier, score, desc=DESC, group=None, company="Contoso Retail"):
    conn = connect(cfg["paths"]["db"])
    job = Job("test", ext, title, company, "Vancouver, BC", desc, f"https://x/{ext}")
    job.dedup_group_id = group
    jid, _ = upsert_job(conn, job)
    conn.execute("UPDATE jobs SET tier = ?, score = ? WHERE id = ?", (tier, score, jid))
    conn.commit()
    conn.close()
    return jid


def titles(paths):
    return [appdir.load_app(p)["title"] for p in paths]


def test_flagged_sinks_within_tier_only(cfg):
    add(cfg, "a1", "A flagged", "A", 90)
    add(cfg, "a2", "A clean", "A", 70)
    add(cfg, "b1", "B clean", "B", 99)

    def answers(state, q):
        bad = "A flagged" in state
        return 0 if bad and q.id == "seniority_fit" else GOOD[q.id]

    out = run_queue(cfg, limit=5, jev=FakeJev(answers))
    assert titles(out) == ["A clean", "A flagged", "B clean"]
    flagged = appdir.load_app(out[1])
    assert flagged["gate"]["flagged"] and flagged["gate"]["queue_rank"] == 2
    assert flagged["gate"]["flags"][0]["reason"] == "failed"
    assert not appdir.load_app(out[0])["gate"]["flagged"]


def test_yes_no_sides_and_unchecked(cfg):
    add(cfg, "a1", "Needs PhD", "A", 80)
    out = run_queue(cfg, jev=FakeJev({**GOOD, "requires_phd": 0.9, "is_coop": None}))
    flags = {f["question"]: f["reason"] for f in appdir.load_app(out[0])["gate"]["flags"]}
    assert flags == {"requires_phd": "failed", "is_coop": "unchecked"}


def test_no_jev_answers_means_unchecked_but_still_queued(cfg):
    add(cfg, "a1", "Analyst", "A", 80)
    out = run_queue(cfg, jev=FakeJev())
    flags = appdir.load_app(out[0])["gate"]["flags"]
    assert len(flags) == len(GATE_QUESTIONS)
    assert {f["reason"] for f in flags} == {"unchecked"}
    assert (out[0] / "posting.md").read_text().startswith("# Analyst")


def test_eligibility_dedup_and_cap(cfg):
    add(cfg, "s1", "Short", "A", 99, desc="too short")
    add(cfg, "x1", "Skipped", "skip", 99)
    add(cfg, "d1", "Dup short", "A", 80, desc=DESC, group="g1")
    add(cfg, "d2", "Dup long", "A", 79, desc=DESC + " more detail", group="g1")
    add(cfg, "c1", "Third", "B", 50)
    jev = FakeJev(GOOD)
    out = run_queue(cfg, limit=2, jev=jev)
    assert titles(out) == ["Dup long", "Third"]
    # second run: dedup group and existing applications are excluded
    assert run_queue(cfg, limit=5, jev=jev) == []
    conn = store.connect(cfg["paths"]["db"])
    assert conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 2


def test_html_description_becomes_markdown_and_job_ids(cfg):
    jid = add(cfg, "h1", "Skip tier but asked for", "skip", 10,
              desc="<p>Intro</p><ul><li>SQL</li><li>Tableau</li></ul>")
    out = run_queue(cfg, job_ids=[jid], jev=FakeJev(GOOD))
    text = (out[0] / "posting.md").read_text()
    assert "* SQL" in text and "<li>" not in text
    with pytest.raises(TailorError):
        run_queue(cfg, job_ids=[999], jev=FakeJev(GOOD))


def _packet_app(cfg):
    jid = add(cfg, "p1", "Analyst", "A", 80)
    d = run_queue(cfg, jev=FakeJev({**GOOD, "is_coop": 0.9}))[0]
    appdir.log(d, "base", base_id="data-analyst", best_round=1)
    appdir.write_json(d / "evidence.json", {
        "requirements": [{"id": "r1", "status": "partial", "strength": 1, "passages": ["a.b"]}],
        "buckets": {"data-analyst": {"matched": ["SQL"], "injectable": ["dbt"], "non_injectable": ["Looker"],
                                     "current_pct": 50.0, "potential_pct": 75.0}},
    })
    appdir.write_json(d / "requirements.json", {"requirements": [{"id": "r1", "text": "Strong SQL", "kind": "must"}]})
    r1 = d / "drafts" / "r1"
    appdir.write_json(r1 / "check.json", {
        "criticals": [], "warnings": [{"code": "dash", "message": "em dash", "path": "summary"}],
        "flags": [{"code": "jev_unsupported", "message": "unsupported", "path": "p"}]})
    appdir.write_json(r1 / "grade.json", {"ats": {"total": 78, "components": {"keyword": 80}}, "score": 76.2})
    appdir.write_json(d / "plan.json", {"base_id": "data-analyst"})
    bases = Path(cfg["paths"]["bases"])
    bases.mkdir(parents=True, exist_ok=True)
    (bases / "data-analyst.yaml").write_text("id: data-analyst\nsummary: {text: old}\n")
    (r1 / "resume.yaml").write_text("id: data-analyst\nsummary: {text: new}\n")
    return jid, d


def test_packet_and_approve_gate(cfg):
    jid, d = _packet_app(cfg)
    res = run_packet(d, cfg)
    assert res["status"] == "ready_for_review"
    notes = (d / "fit-notes.md").read_text()
    assert "Strong SQL" in notes and "75.0%" in notes and "Interview prep" in notes
    assert "Looker" in notes and "Must-have: Strong SQL" in notes
    check = (d / "check.md").read_text()
    assert check.index("Gate flags: review before applying") < check.index("Score: 76.2")
    assert "- [ ] Reviewed  This may be a co-op or student work term." in check
    assert "- [ ] Keep  - [ ] Remove  Summary: em dash" in check  # an unknown code keeps its message
    assert "- [ ] Keep  - [ ] Remove  p: Jev doesn't think this line is backed" in check
    assert "  - Before: old\n  - After: new" in check and "- **Summary**" in check
    assert check.count("\n> ") >= 4  # each section opens with a note saying what it's for
    conn = store.connect(cfg["paths"]["db"])
    assert store.get_app(conn, jid)["status"] == "ready_for_review"

    with pytest.raises(TailorError):
        approve(d, cfg)
    ticked = []
    for line in check.splitlines():
        if "Reviewed" in line:
            line = line.replace("[ ]", "[x]", 1)
        elif "Keep" in line:
            line = line.replace("[ ] Keep", "[x] Keep", 1)
        ticked.append(line)
    (d / "check.md").write_text("\n".join(ticked))
    assert approve(d, cfg)["status"] == "approved"
    assert store.get_app(conn, jid)["status"] == "approved"

    record_outcome(d, cfg, "applied")
    row = store.get_app(conn, jid)
    assert row["status"] == "applied" and row["outcome"] == "applied" and row["outcome_at"]
    record_outcome(d, cfg, "interview")
    assert store.get_app(conn, jid)["status"] == "applied"
    with pytest.raises(TailorError):
        record_outcome(d, cfg, "bogus")


def test_fit_notes_count_the_plans_evidence_adds(cfg):
    # REW.ca, Oct 23 2026: fit-notes listed a term as not backed (and as interview prep) while
    # check.md and the grade counted the plan's match for it.
    _, d = _packet_app(cfg)
    ev = json.loads((d / "evidence.json").read_text())
    ev.update(present=["SQL", "dbt"], absent=["Looker"],
              terms=[{"term": "Looker", "canonical": "Looker", "passages": [], "related": [], "in_base": {}}])
    appdir.write_json(d / "evidence.json", ev)
    appdir.write_json(d / "plan.json", {"base_id": "data-analyst",
                                        "evidence_adds": [{"term": "Looker", "passage": "a.dash"}]})
    run_packet(d, cfg)
    notes = (d / "fit-notes.md").read_text()
    assert "- Can be added (backed by the vault): dbt, Looker" in notes
    assert "- Not backed by the vault: none" in notes and "Term not in your record: Looker" not in notes


def test_packet_criticals_and_missing_inputs(cfg):
    jid, d = _packet_app(cfg)
    chk = d / "drafts" / "r1" / "check.json"
    data = json.loads(chk.read_text())
    data["criticals"] = [{"code": "invented_number", "message": "99%", "path": "summary"}]
    chk.write_text(json.dumps(data))
    (d / "drafts" / "r1" / "grade.json").unlink()
    assert run_packet(d, cfg)["status"] == "needs_fixes"
    assert "No grade available" in (d / "check.md").read_text()
    (d / "evidence.json").unlink()
    with pytest.raises(TailorError):
        run_packet(d, cfg)


def test_packet_leaves_ai_phrases_to_the_humanize_pass(cfg):
    _, d = _packet_app(cfg)
    r1 = d / "drafts" / "r1"
    letter = {"greeting": "Dear Hiring Manager,", "paragraphs": [
        {"text": "I leveraged SQL daily.", "sources": []}, {"text": "I leveraged dashboards.", "sources": []}]}
    appdir.write_json(r1 / "cover-letter.json", letter)
    appdir.write_json(r1 / "check.json", {"criticals": [], "flags": [], "warnings": [
        {"code": "ai_phrase", "message": "paragraphs[0]: banned_word 'leveraged'", "path": "paragraphs[0]", "doc": "letter"},
        {"code": "ai_phrase", "message": "paragraphs[1]: banned_word 'leveraged'", "path": "paragraphs[1]", "doc": "letter"}]})
    run_packet(d, cfg)  # no humanize pass yet: they're listed
    assert "paragraph 2" in (d / "check.md").read_text().split("## Remaining issues")[1]
    # humanize rewrote only the first paragraph; neither is a review line once it has run
    letter["paragraphs"][0]["text"] = "I used SQL daily."
    appdir.write_json(d / "humanize" / "cover-letter.json", letter)
    (d / "humanize" / "resume.yaml").write_text((r1 / "resume.yaml").read_text())
    run_packet(d, cfg)
    issues = (d / "check.md").read_text().split("## Remaining issues")[1]
    assert "paragraph 1" not in issues and "paragraph 2" not in issues


def test_packet_asks_only_about_skills_the_draft_added_to_the_list(cfg):
    _, d = _packet_app(cfg)
    r1 = d / "drafts" / "r1"
    warn = {"code": "skill_only_in_list", "path": "skills", "doc": "resume"}
    appdir.write_json(r1 / "check.json", {"criticals": [], "flags": [], "warnings": [
        {**warn, "message": "'R' appears only in the skills list", "data": {"term": "R", "added": False}},
        {**warn, "message": "'AWS' appears only in the skills list", "data": {"term": "AWS", "added": True}},
        {**warn, "message": "'dbt' appears only in the skills list", "data": {"term": "dbt"}}]})
    run_packet(d, cfg)
    issues = (d / "check.md").read_text().split("## Remaining issues")[1]
    assert "AWS is in your skills list" in issues and "dbt is in your skills list" in issues
    assert "R is in your skills list" not in issues


def test_gate_skipped_without_jev_key(cfg):
    add(cfg, "k1", "Analyst", "A", 80)

    class NoKey:
        available = False

    out = run_queue(cfg, jev=NoKey())
    gate = appdir.load_app(out[0])["gate"]
    assert gate["flags"] == [] and gate["checked"] is False


def test_packet_lists_evidence_drops(cfg):
    _, d = _packet_app(cfg)
    appdir.write_json(d / "plan.json", {"base_id": "data-analyst", "evidence_drops": [
        {"term": "Microsoft Access", "passage": "firmament.oauth-2-0", "reason": "OAuth access tokens"}]})
    run_packet(d, cfg)
    check = (d / "check.md").read_text()
    assert "## Evidence set aside" in check
    line = next(x for x in check.splitlines() if "Undo" in x and x.startswith("- [ ]"))
    assert line == ("- [ ] Set aside  - [ ] Undo  Microsoft Access: not counted from firmament.oauth-2-0. "
                    "<!-- undo: Microsoft Access | firmament.oauth-2-0 -->")
    assert "  - Why: OAuth access tokens." in check
    assert check.index("Evidence set aside") < check.index("Changes from the base")
    # Every section with buttons comes before the read-only ones (Jake, Oct 22 2026).
    assert check.index("## Remaining issues") < check.index("## Grade") < check.index("## Changes from the base")
    assert "- [ ]" not in check[check.index("## Grade"):]
    # The pair in the comment is what approve uses to undo the reject.
    from src.tailor import rejects
    assert rejects._UNDO.match(line.replace("[ ] Undo", "[x] Undo"))["passage"] == "firmament.oauth-2-0"
    assert not rejects.apply_undos(line.replace("[ ] Set aside", "[x] Set aside"), cfg)  # set aside = keep it
    with pytest.raises(TailorError):
        approve(d, cfg)  # a drop needs a decision too


def test_packet_lists_jev_no_answers(cfg):
    _, d = _packet_app(cfg)
    g = d / "drafts" / "r1" / "grade.json"
    data = json.loads(g.read_text())
    data["checklist"] = [{"id": "letter.closer", "question": "Could this closing sentence end any letter?",
                          "passed": False, "confidence": 0.53},
                         {"id": "top_third", "question": "Top third?", "passed": True, "confidence": 0.9}]
    g.write_text(json.dumps(data))
    ev = json.loads((d / "evidence.json").read_text())
    ev["jev_said_no"] = [{"term": "Microsoft Access", "passage": "firmament.oauth", "text": "OAuth access tokens"}]
    (d / "evidence.json").write_text(json.dumps(ev))
    run_packet(d, cfg)
    check = (d / "check.md").read_text()
    assert "## Jev said no: check for false rejections" in check
    assert "- [ ] Reviewed  The letter's closing sentence may be generic: it could fit almost any job (53% sure)." in check
    assert "Top third?" not in check and "Jev's checks passed: 1 of 2" in check
    assert '- Microsoft Access: not counted from firmament.oauth: "OAuth access tokens"' in check


def test_packet_flags_ats_below_floor(cfg):
    _, d = _packet_app(cfg)
    g = d / "drafts" / "r1" / "grade.json"
    data = json.loads(g.read_text())
    data.update(ats={"total": 51.3, "components": {}}, ats_ceiling=70.7,
                unused_terms=["data analysis", "presentations"], unbacked_terms=["SPSS"])
    g.write_text(json.dumps(data))
    res = run_packet(d, cfg)
    assert res["below_ats_floor"] is True
    check = (d / "check.md").read_text()
    assert "## ATS score below 70: review before applying" in check
    assert "- [ ] Reviewed  ATS 51.3 is below the 70 minimum; your evidence could reach about 70.7, so the gap is wording." in check
    assert "doesn't use the posting's words:\n    - data analysis\n    - presentations" in check
    assert "your vault doesn't show them in these words:\n    - SPSS\n" in check
    assert "ATS score below" not in check.split("## Grade")[1]  # flag sits above the grade
    with pytest.raises(TailorError):
        approve(d, cfg)  # the Reviewed line must be ticked first


def test_packet_below_floor_with_no_unused_terms_does_not_promise_a_wording_fix(cfg):
    # Ceiling over the floor, but every backed term is already used: no repair round can help.
    _, d = _packet_app(cfg)
    g = d / "drafts" / "r1" / "grade.json"
    data = json.loads(g.read_text())
    data.update(ats={"total": 68.4, "components": {}}, ats_ceiling=70.4, fit_gap=False,
                unused_terms=[], unbacked_terms=["SPSS"])
    g.write_text(json.dumps(data))
    check = (d / "check.md").read_text() if run_packet(d, cfg) else ""
    assert "## ATS score below 70: review before applying" in check
    assert "the gap is wording" not in check and "another repair round could raise" not in check
    assert "- [ ] Reviewed  ATS 68.4 is below the 70 minimum; your evidence could reach about 70.4, " \
           "but no backed term is left to add." in check


def test_packet_calls_a_low_ceiling_a_weaker_fit(cfg):
    _, d = _packet_app(cfg)
    g = d / "drafts" / "r1" / "grade.json"
    data = json.loads(g.read_text())
    data.update(ats={"total": 62.0, "components": {}}, ats_ceiling=66.0, fit_gap=True,
                unused_terms=[], unbacked_terms=["SPSS", "healthcare data"])
    g.write_text(json.dumps(data))
    res = run_packet(d, cfg)
    assert res["weaker_fit"] is True
    check = (d / "check.md").read_text()
    assert "## Weaker fit: review before applying" in check
    assert "the best this resume could reach is about 66.0, under the 70 minimum" in check
    assert "your vault doesn't show them in these words:\n    - SPSS\n    - healthcare data" in check
    assert "doesn't use the posting's words:\n    - None" in check  # both lists always shown


def test_gate_judges_against_the_closest_base(cfg):
    bases = Path(cfg["paths"]["bases"])
    bases.mkdir(parents=True, exist_ok=True)
    (bases / "data-scientist.yaml").write_text("summary: {text: Python with pandas and scikit-learn models}\n")
    (bases / "junior-swe.yaml").write_text("summary: {text: TypeScript and React apps with Git and Docker}\n")
    add(cfg, "s1", "Software Engineer I", "A", 80,
        desc="Build features in TypeScript and React; use Git and Docker. " * 30)
    add(cfg, "d1", "Data Scientist", "A", 70, desc="Build models in Python with pandas and scikit-learn. " * 30)
    seen = {}

    def answers(state, q):
        seen[state.split("\n")[1]] = state.split("RESUME\n", 1)[1]
        return GOOD[q.id]

    out = run_queue(cfg, limit=5, jev=FakeJev(answers))
    assert "React" in seen["Software Engineer I at Contoso Retail"]
    assert "pandas" in seen["Data Scientist at Contoso Retail"]
    assert {appdir.load_app(p)["gate"]["resume_base"] for p in out} == {"junior-swe", "data-scientist"}


def test_packet_lists_bullets_cut_to_fit(cfg):
    _, d = _packet_app(cfg)
    (d / "drafts" / "r1" / "resume.yaml").write_text(
        "id: data-analyst\nsummary: {text: new}\nexperience:\n- id: acme\n  company: Acme\n  bullets:\n"
        "  - {id: a1, text: Kept bullet}\n  - {id: a2, text: Wrote weekly sales reports}\n")
    appdir.write_json(d / "final" / "parse.json", {"ok": True, "dropped": ["experience/acme/a2"]})
    run_packet(d, cfg)
    check = (d / "check.md").read_text()
    assert "## Bullets cut to fit one page" in check
    line = next(x for x in check.splitlines() if "Wrote weekly sales reports" in x)
    assert line.startswith("- [ ] Reviewed  ") and "Acme" in line
    from src.tailor.packet import unresolved_lines
    assert line in unresolved_lines(check)  # the cut needs a look before approving


def test_closed_and_internal_postings_are_never_queued(cfg):
    add(cfg, "o1", "Open", "A", 70)
    add(cfg, "c1", "Closed", "A", 99, desc=DESC + "\n\nPosting End Date: October 1, 2020")
    add(cfg, "i1", "Internal", "A", 98, desc=DESC + "\n\nThis position will be filled internally.")
    # A closed copy from another source closes the whole group.
    add(cfg, "g1", "Copy", "A", 97, desc=DESC + " more detail", group="g")
    add(cfg, "g2", "Copy", "D", 10, desc="Posting End Date: October 1, 2020", group="g")
    assert titles(run_queue(cfg, limit=5, jev=FakeJev(GOOD))) == ["Open"]


def test_queue_rescores_so_a_stale_tier_is_not_drafted(cfg):
    # Stored as A-tier remote before the country-only location rule existed; the posting is Toronto, on-site.
    conn = connect(cfg["paths"]["db"])
    job = Job("test", "t1", "Data Analyst", "Big Bank", "Canada",
              "Work on-site in our Toronto, ON office. SQL and Python. " * 3, "https://x/t1")
    jid, _ = upsert_job(conn, job)
    conn.execute("UPDATE jobs SET tier = 'A', score = 90, location_category = 'remote' WHERE id = ?", (jid,))
    conn.commit()
    conn.close()
    assert run_queue({**cfg, "rescore_before_queue": True}, limit=5) == []


def test_queue_never_drafts_a_job_you_dismissed_or_applied_to(cfg):
    keep = add(cfg, "k1", "Data Analyst", "A", 90)
    gone = add(cfg, "d1", "BI Analyst", "A", 95)
    twin = add(cfg, "d2", "BI Analyst (repost)", "A", 94, group="g-dismissed")
    other = add(cfg, "d3", "BI Analyst elsewhere", "A", 93, group="g-dismissed")
    done = add(cfg, "a1", "Analyst", "A", 92)
    conn = connect(cfg["paths"]["db"])
    conn.executemany("UPDATE jobs SET status = ? WHERE id = ?",
                     [("dismissed", gone), ("dismissed", twin), ("applied", done)])
    conn.commit()
    conn.close()
    out = run_queue(cfg, limit=10)
    assert [appdir.load_app(p)["job_id"] for p in out] == [keep]
    assert other  # same posting group as a dismissed one, so left out too


def test_limit_zero_queues_nothing_without_touching_the_database(tmp_path):
    from src.tailor.queue import run_queue

    assert run_queue({"paths": {"db": str(tmp_path / "missing" / "jobs.db")}}, limit=0) == []


def test_packet_lists_what_the_review_round_did_with_each_note(cfg):
    _, d = _packet_app(cfg)
    appdir.write_json(d / "review" / "response.json", [
        {"note": "Summary names the Loyalty team", "action": "changed", "why": "now says business teams"},
        {"note": "Quantify the Apps Script time saved", "action": "left", "why": "no number in the vault"}])
    run_packet(d, cfg)
    check = (d / "check.md").read_text()
    section = check.split("## Outside review")[1]
    assert "- Changed: Summary names the Loyalty team: now says business teams" in section
    assert "- Left as is: Quantify the Apps Script time saved: no number in the vault" in section
    assert check.index("## Remaining issues") < check.index("## Outside review")  # read-only, after the buttons
