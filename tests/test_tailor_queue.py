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
    }})


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
    assert "- [ ] Reviewed  is_coop: failed" in check
    assert "- [ ] Keep  - [ ] Remove  dash: em dash (summary)" in check
    assert "before: old" in check and "after: new" in check
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
    assert "## Evidence matches the plan rejected" in check
    assert "- [ ] Undo  Microsoft Access (firmament.oauth-2-0): OAuth access tokens" in check
    assert check.index("rejected") < check.index("Changes from the base")


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
    assert "- Failed: Could this closing sentence end any letter? (confidence 0.53)" in check
    assert "Top third?" not in check
    assert '- Not counted as evidence: Microsoft Access in firmament.oauth: "OAuth access tokens"' in check


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
    assert "- [ ] Reviewed  ATS 51.3 is below the 70 minimum; your evidence could reach about 70.7, so the gap is wording" in check
    assert "doesn't use the posting's words: data analysis, presentations" in check
    assert "your vault doesn't show them: SPSS" in check
    assert "ATS score below" not in check.split("## Grade")[1]  # flag sits above the grade
    with pytest.raises(TailorError):
        approve(d, cfg)  # the Reviewed line must be ticked first


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
    assert "best your evidence can reach is about 66.0, under the 70 minimum, so this is missing skills" in check
    assert "your vault doesn't show them: SPSS, healthcare data" in check
