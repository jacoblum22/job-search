"""`why`: one application's status and open items in a single read."""

from __future__ import annotations

from pathlib import Path

from src.tailor import why
from src.tailor.appdir import write_json


def _cfg(tmp_path: Path) -> dict:
    return {"paths": {"applications": str(tmp_path / "apps"), "materials": str(tmp_path / "materials")}}


def _app(tmp_path: Path) -> Path:
    app = tmp_path / "apps" / "2026-10-27 Amazon - ICQA Data Analyst, YVR4"
    (app / "drafts" / "r1").mkdir(parents=True)
    write_json(app / "app.json", {
        "job_id": 904, "company": "Amazon", "title": "ICQA Data Analyst, YVR4", "status": "needs_fixes",
        "best_round": 1, "rounds": [{"round": 1, "score": 67.0, "criticals": 1}],
        "gate": {"flags": [{"question": "years_ok", "text": "Does the posting ask for no more than about three "
                            "years of experience?", "answer": 0.4, "confidence": 0.6}]},
        "history": [{"step": "packet", "note": "needs_fixes, 1 critical(s)"}]})
    (app / "drafts" / "r1" / "resume.yaml").write_text(
        "name: Jake\nsummary:\n  text: Data analyst.\nskills:\n- id: skills.tools\n  label: Tools\n"
        "  items: [MS Office]\n", encoding="utf-8")
    write_json(app / "drafts" / "r1" / "check.json", {
        "criticals": [{"code": "invented_skill", "path": "skills/skills.tools", "doc": "resume",
                       "message": "'MS Office' (Microsoft Office) is not how any vault passage or the base words it",
                       "data": {"term": "Microsoft Office", "wording": "MS Office"}}],
        "warnings": [{"code": "skill_only_in_list", "message": "'R' appears only in the skills list",
                      "path": "skills", "data": {"term": "R"}}],
        "flags": []})
    write_json(app / "drafts" / "r1" / "grade.json", {"score": 67.0, "ats": {"total": 71.7}, "ats_ceiling": 71.7})
    (app / "check.md").write_text("# Check\n\n## Remaining issues\n\n- [ ] Keep  - [ ] Remove  Skills list: x\n",
                                  encoding="utf-8")
    return app


def test_find_by_job_id_or_folder_words(tmp_path):
    app = _app(tmp_path)
    cfg = _cfg(tmp_path)
    assert why.find(cfg, "904") == [app]
    assert why.find(cfg, "amazon icqa") == [app]
    assert why.find(cfg, "905") == [] and why.find(cfg, "amazon scientist") == []


def test_summary_says_what_set_the_status(tmp_path):
    app = _app(tmp_path)
    out = why.summarize(app, _cfg(tmp_path))
    assert out["status"] == "needs_fixes" and out["job_id"] == 904
    assert len(out["why_status"]) == 1 and out["why_status"][0].startswith("Critical: Skills list (Tools)")
    assert "Microsoft Office" in out["why_status"][0]
    assert out["warnings"][0].startswith("Skills list: R is in your skills list")
    assert out["gate_flags"] and out["open_review_items"] == 1
    assert out["last_steps"] == ["packet: needs_fixes, 1 critical(s)"]


def test_wide_gap_is_named_when_there_is_no_critical(tmp_path):
    app = _app(tmp_path)
    write_json(app / "drafts" / "r1" / "check.json", {"criticals": [], "warnings": [], "flags": []})
    write_json(app / "drafts" / "r1" / "grade.json", {"ats": {"total": 55.0}, "ats_ceiling": 80.0})
    out = why.summarize(app, {**_cfg(tmp_path), "loop": {"wide_gap": 10}})
    assert out["why_status"] == ["Wide ATS gap: 55.0 against a reachable 80.0 (more than 10 under)"]


def test_run_review_notes_for_this_job(tmp_path):
    app = _app(tmp_path)
    notes = tmp_path / "materials" / "tailor" / "run-reviews"
    notes.mkdir(parents=True)
    (notes / "2026-10-27_0823.md").write_text(
        "## Look at before sending\n\n**Amazon ICQA (needs_fixes):**\n- Fix the Tools item.\n- Bullet 6 is tacked on.\n\n"
        "**Amazon Data Scientist:**\n- Not this one.\n\n**VCH Business Advisor:**\n- Nor this.\n", encoding="utf-8")
    out = why.summarize(app, _cfg(tmp_path))
    assert out["run_review_notes"] == [{"review": "2026-10-27_0823",
                                        "notes": ["Fix the Tools item.", "Bullet 6 is tacked on."]}]
