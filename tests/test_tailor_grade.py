"""Tests for src/tailor/grade.py: ATS components and the Jev checklist."""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml

from src.resume import load_resume
from src.tailor.appdir import write_json
from src.tailor.grade import ats_score, run_grade
from src.tailor.jev import FakeJev

FIX = Path(__file__).parent / "fixtures" / "tailor"
GRADE_FIX = FIX / "grade"
CFG = {
    "ats_weights": {"keyword": 40, "skills": 20, "title": 15, "sections": 15, "dates": 10},
    "synonym_credit": 0.5,
    "stuffing_score": 90,
    "target_score": 80,
}


def base():
    return load_resume(FIX / "base-analyst.yaml")


def req(terms=(), keywords=(), title="Junior Data Analyst"):
    return {
        "title": title,
        "company": "Contoso Retail",
        "requirements": [
            {"id": f"r{i}", "text": t, "kind": "must", "terms": [t], "weight": "role"} for i, t in enumerate(terms, 1)
        ],
        "keywords": [{"term": k, "weight": "role"} for k in keywords],
    }


def ev(present=()):
    return {"requirements": [], "terms": [], "present": list(present), "absent": []}


def make_app(tmp_path: Path, resume=None) -> Path:
    app = tmp_path / "app"
    (app / "drafts" / "r1").mkdir(parents=True)
    write_json(app / "app.json", {"company": "Contoso Retail", "history": []})
    shutil.copy(FIX / "posting.md", app / "posting.md")
    shutil.copy(GRADE_FIX / "requirements.json", app / "requirements.json")
    shutil.copy(GRADE_FIX / "evidence.json", app / "evidence.json")
    shutil.copy(GRADE_FIX / "cover-letter.json", app / "drafts" / "r1" / "cover-letter.json")
    data = resume or base()
    (app / "drafts" / "r1" / "resume.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return app


# --- ATS components -------------------------------------------------------


def test_exact_gets_full_credit_synonym_half():
    # "SQL" is worded exactly; "Postgres" only matches through the taxonomy (resume says PostgreSQL).
    r = req(terms=["SQL"], keywords=["Postgres"])
    out = ats_score(base(), r, ev(["SQL"]), CFG)
    # weights: SQL must 1.5 (credit 1), Postgres 1.0 (credit 0.5) -> (1.5 + 0.5) / 2.5
    assert out["components"]["keyword"] == pytest.approx(80.0)


def test_unbacked_terms_earn_nothing():
    r = req(terms=["SQL"])
    assert ats_score(base(), r, ev([]), CFG)["components"]["keyword"] == 0.0
    assert ats_score(base(), r, ev(["SQL"]), CFG)["components"]["keyword"] == 100.0


def test_boilerplate_weighs_a_quarter_and_must_one_and_a_half():
    r = req(terms=["SQL"], keywords=["Looker"])
    r["keywords"].append({"term": "Excel", "weight": "boilerplate"})
    out = ats_score(base(), r, ev(["SQL", "Excel"]), CFG)
    # SQL 1.5 earned, Looker 1.0 unbacked, Excel 0.25 earned -> 1.75 / 2.75
    assert out["components"]["keyword"] == pytest.approx(63.6, abs=0.1)


def test_soft_skills_weigh_half():
    r = req(terms=["SQL", "communication"])
    out = ats_score(base(), r, ev(["SQL"]), CFG)
    # SQL must 1.5 earned, communication must 1.5 x 0.5 unbacked -> 1.5 / 2.25
    assert out["components"]["keyword"] == pytest.approx(66.7, abs=0.1)
    assert ats_score(base(), r, ev(["SQL"]), {**CFG, "ats_soft_weight": 1.0})["components"]["keyword"] == 50.0


def test_soft_skills_are_never_pushed_for_points(tmp_path):
    from src.tailor.grade import ats_gap
    r = req(terms=["SQL", "communication", "Looker"])
    out = ats_gap({"summary": {"text": "Analyst."}}, r, ev(["SQL", "communication"]), CFG)
    assert out["unused"] == ["SQL"] and out["unused_soft"] == ["communication"]
    assert out["unbacked"] == ["Looker"]


def test_unscorable_components_are_none_and_weight_is_redistributed():
    data = base()
    data["experience"][1]["dates"] = "2024"  # one of four dated entries is malformed -> 75
    out = ats_score(data, req(), ev(), CFG)
    comps = out["components"]
    assert comps["keyword"] is None and comps["skills"] is None
    assert comps["title"] == 100 and comps["sections"] == 100 and comps["dates"] == 75
    # only title 15, sections 15, dates 10 count: (1500 + 1500 + 750) / 40
    assert out["total"] == pytest.approx(93.75, abs=0.06)


def test_skills_looks_in_skills_section_and_bullets():
    r = req(terms=["Tableau", "dbt", "SQL", "Python"])
    out = ats_score(base(), r, ev(), CFG)
    assert out["components"]["skills"] == 75.0  # dbt is missing


def test_title_scores():
    data = base()
    assert ats_score(data, req(), ev(), CFG)["components"]["title"] == 100  # core "Data Analyst" in sentence one
    data["summary"]["text"] = "Statistics graduate. Worked as a data analyst at a logistics company."
    assert ats_score(data, req(), ev(), CFG)["components"]["title"] == 75
    data["summary"]["text"] = "Statistics graduate who likes data."
    assert ats_score(data, req(), ev(), CFG)["components"]["title"] == 25.0  # 1 of 2 core words, up to 50
    data.pop("summary")
    assert ats_score(data, req(), ev(), CFG)["components"]["title"] is None


def test_sections_and_dates():
    data = base()
    data.pop("skills")
    data["education"][0]["dates"] = "Sep 2022 to May 2026"
    out = ats_score(data, req(), ev(), CFG)["components"]
    assert out["sections"] == 75.0
    assert out["dates"] == 75.0


def test_present_date_range_and_single_project_date_ok():
    data = base()
    data["experience"][0]["dates"] = "Jan 2026 – Present"
    assert ats_score(data, req(), ev(), CFG)["components"]["dates"] == 100.0


def test_stuffing_needs_high_score_and_repetition():
    data = base()
    data["summary"]["text"] = "Data analyst. SQL SQL SQL SQL SQL."
    r = req(terms=["SQL"])
    cfg = {**CFG, "stuffing_score": 50}
    assert ats_score(data, r, ev(["SQL"]), cfg)["stuffing"] is True
    assert ats_score(base(), r, ev(["SQL"]), cfg)["stuffing"] is False


# --- run_grade ------------------------------------------------------------


def test_run_grade_without_jev_marks_everything_unchecked(tmp_path):
    app = make_app(tmp_path)
    out = run_grade(app, 1, CFG, FakeJev({}))
    assert out["checklist"] and all(it["source"] == "unchecked" and it["passed"] is None for it in out["checklist"])
    assert out["score"] == pytest.approx(0.6 * out["ats"]["total"] + 40.0, abs=0.06)
    saved = json.loads((app / "drafts" / "r1" / "grade.json").read_text())
    assert saved["score"] == out["score"]
    ids = {it["id"] for it in out["checklist"]}
    assert {"must.r1", "must.r2", "top_third", "letter.specific", "letter.opener", "letter.closer"} <= ids
    assert any(i.startswith("portable.") for i in ids)


def test_failed_items_become_feedback_without_question_text(tmp_path):
    app = make_app(tmp_path)

    def answers(state, q):
        if q.id.startswith("portable."):
            return 0.9  # "yes, could describe anyone" -> fail
        if q.id == "letter.specific":
            return 0.2
        return 0.8

    jev = FakeJev(answers)
    out = run_grade(app, 1, CFG, jev)
    by_id = {it["id"]: it for it in out["checklist"]}
    assert by_id["must.r1"]["passed"] is True and by_id["must.r1"]["source"] == "jev"
    assert by_id["letter.specific"]["passed"] is False
    assert any(it["passed"] is False for i, it in by_id.items() if i.startswith("portable."))
    fb = " ".join(out["feedback"])
    assert "Must-have dbt isn't shown; passage northwind.dbt supports it." in out["feedback"]
    assert "Contoso Retail" in fb
    for it in out["checklist"]:
        assert it["question"] not in out["feedback"] and "backed by a resume bullet" not in fb
    # the state sent to Jev has the name removed
    assert "Rivera" not in jev.calls[0][0]


def test_failed_must_with_only_unbacked_terms_missing_is_a_fit_gap(tmp_path):
    app = make_app(tmp_path)
    r = json.loads((app / "requirements.json").read_text())
    r["requirements"][0] = {**r["requirements"][0], "text": "SQL and Looker", "terms": ["SQL", "Looker"]}
    r["requirements"][1] = {**r["requirements"][1], "text": "SQL and dbt", "terms": ["SQL", "dbt"]}
    write_json(app / "requirements.json", r)
    out = run_grade(app, 1, CFG, FakeJev(lambda state, q: 0.2 if q.id.startswith("must.") else 0.8))
    by_id = {it["id"]: it for it in out["checklist"]}
    # SQL is on the resume and Looker isn't in the vault: nothing to repair
    assert by_id["must.r1"]["passed"] is False and by_id["must.r1"]["fit_gap"] == ["Looker"]
    assert not any("Looker" in f or f.startswith("Must-have SQL needs") for f in out["feedback"])
    # dbt is backed but not shown: still repair feedback, naming the backed terms
    assert "fit_gap" not in by_id["must.r2"]
    assert any("dbt" in f for f in out["feedback"])


def test_portability_only_counts_changed_bullets(tmp_path):
    app = make_app(tmp_path)
    write_json(
        app / "drafts" / "r1" / "edits.json",
        {"strategy": "nudge", "edits": [{"path": "experience/northwind/northwind.dashboards", "action": "replace"}]},
    )
    out = run_grade(app, 1, CFG, FakeJev({}))
    ports = [it["id"] for it in out["checklist"] if it["id"].startswith("portable.")]
    assert ports == ["portable.experience/northwind/northwind.dashboards"]


def test_jev_failure_means_unchecked(tmp_path):
    class Boom:
        def ask(self, state, questions):
            raise NotImplementedError

    out = run_grade(make_app(tmp_path), 1, CFG, Boom())
    assert all(it["source"] == "unchecked" for it in out["checklist"])


def test_failed_checklist_lowers_score(tmp_path):
    app = make_app(tmp_path)
    good = run_grade(app, 1, CFG, FakeJev(lambda s, q: 0.0 if q.id.startswith("portable.") else 0.9))
    bad = run_grade(app, 1, CFG, FakeJev(lambda s, q: 0.9 if q.id.startswith("portable.") else 0.9))
    assert bad["score"] < good["score"]
    assert good["ats"]["total"] == bad["ats"]["total"]


def test_letter_opener_and_closer_are_separate_questions(tmp_path):
    app = make_app(tmp_path)
    letter_path = app / "drafts" / "r1" / "cover-letter.json"
    letter = json.loads(letter_path.read_text())
    letter["paragraphs"] = [{"text": "I am applying for this role. I wrote SQL daily.", "sources": [], "company_facts": []},
                            {"text": "I used dbt. I would like to talk soon.", "sources": [], "company_facts": []}]
    letter_path.write_text(json.dumps(letter))
    asked = {}

    def answers(state, q):
        asked[q.id] = q.text
        return 0.9 if q.id == "letter.closer" else 0.1

    out = run_grade(app, 1, CFG, FakeJev(answers))
    assert '"I am applying for this role."' in asked["letter.opener"]
    assert '"I would like to talk soon."' in asked["letter.closer"]
    by_id = {it["id"]: it for it in out["checklist"]}
    assert by_id["letter.opener"]["passed"] is True and by_id["letter.closer"]["passed"] is False
    assert any("last sentence" in s for s in out["feedback"])
    assert not any("first sentence" in s for s in out["feedback"])


def test_ats_gap_lists_unused_and_unbacked_terms(tmp_path):
    app = make_app(tmp_path)
    out = run_grade(app, 1, {**CFG, "ats_floor": 70}, FakeJev({}))
    assert out["ats_floor"] == 70 and out["below_floor"] == (out["ats"]["total"] < 70)
    assert out["ats_ceiling"] >= out["ats"]["total"]
    assert set(out["unused_terms"]).isdisjoint(out["unbacked_terms"])
    assert out["ats_target"] == min(70, out["ats_ceiling"] - 5)
    assert out["fit_gap"] == (out["ats_ceiling"] < 70)
    if out["unused_terms"]:
        assert any(s.startswith("Use the posting's own words") for s in out["feedback"])
        assert any(g["id"] == "ats.unused" for g in out["gaps"])


def test_soft_must_that_jev_passes_needs_no_word(tmp_path):
    app = make_app(tmp_path)
    r = json.loads((app / "requirements.json").read_text())
    r["requirements"][1] = {**r["requirements"][1], "text": "Strong communication", "terms": ["communication"]}
    write_json(app / "requirements.json", r)
    e = json.loads((app / "evidence.json").read_text())
    e["present"] = list(e.get("present") or []) + ["communication"]
    write_json(app / "evidence.json", e)
    out = run_grade(app, 1, CFG, FakeJev(lambda state, q: 0.8))
    assert not any("communication" in f for f in out["feedback"])
    out = run_grade(app, 1, CFG, FakeJev(lambda state, q: 0.2 if q.id == "must.r2" else 0.8))
    assert any("communication" in f for f in out["feedback"])


def test_failed_years_requirement_is_a_fit_gap(tmp_path):
    app = make_app(tmp_path)
    r = json.loads((app / "requirements.json").read_text())
    r["requirements"][1] = {**r["requirements"][1], "text": "About 2+ years of software development", "terms": [],
                            "quote": "2+ years of professional software development experience."}
    write_json(app / "requirements.json", r)
    out = run_grade(app, 1, CFG, FakeJev(lambda state, q: 0.2 if q.id == "must.r2" else 0.8))
    item = next(it for it in out["checklist"] if it["id"] == "must.r2")
    assert item["fit_gap"] == ["years of experience"]
    assert not any("software development" in f for f in out["feedback"])


def test_degree_requirement_is_asked_about_education_and_never_repaired(tmp_path):
    app = make_app(tmp_path)
    r = json.loads((app / "requirements.json").read_text())
    r["requirements"][1] = {**r["requirements"][1], "text": "Bachelor's degree in Statistics or a related field",
                            "terms": [], "quote": "Bachelor's degree in Statistics, Economics or a related field."}
    write_json(app / "requirements.json", r)
    out = run_grade(app, 1, CFG, FakeJev(lambda state, q: 0.2 if q.id == "must.r2" else 0.8))
    item = next(it for it in out["checklist"] if it["id"] == "must.r2")
    # A degree isn't a bullet with a tool and a scope, and no rewrite can change the degree held.
    assert "names a tool" not in item["question"] and "education" in item["question"]
    assert item["passed"] is False and item["fit_gap"] == ["degree"]
    assert not any("Statistics" in f for f in out["feedback"])
