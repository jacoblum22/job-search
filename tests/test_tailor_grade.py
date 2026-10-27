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


def test_soft_skills_do_not_count():
    # Jake, Oct 23 2026: ATS searches key on hard skills, so a soft skill is no part of the score.
    r = req(terms=["SQL", "communication"])
    out = ats_score(base(), r, ev(["SQL"]), CFG)
    assert out["components"]["keyword"] == 100.0
    assert ats_score(base(), r, ev(["SQL"]), {**CFG, "ats_soft_weight": 1.0})["components"]["keyword"] == 50.0
    # A posting whose only terms are soft skills has no keyword or skills component to score.
    soft_only = ats_score(base(), req(terms=["communication"]), ev([]), CFG)["components"]
    assert soft_only["keyword"] is None and soft_only["skills"] is None


def test_ceiling_counts_the_title_when_the_plan_found_it_truthful():
    from src.tailor.grade import ats_gap
    r = {**req(terms=["SQL"]), "title": "Data Developer"}
    data = {"summary": {"text": "Analyst writing SQL daily."}, "skills": [{"items": ["SQL"]}]}
    plain = ats_gap(data, r, ev(["SQL"]), CFG)["ceiling"]
    assert ats_gap(data, r, ev(["SQL"]), CFG, title_ok=True)["ceiling"] > plain


def test_title_note_when_the_summary_does_not_open_with_the_true_title():
    # Jake, Oct 23 2026: say the job title when it is true, as the summary's opening.
    from src.tailor.grade import ats_gap, ats_gap_lines
    r = {**req(terms=["SQL"]), "title": "Junior Data Developer"}
    data = {"summary": {"text": "Analyst writing SQL daily."}, "skills": [{"items": ["SQL"]}]}
    gap = ats_gap(data, r, ev(["SQL"]), CFG, title_ok="Data developer")
    assert gap["title_missing"] == "Data developer"
    line = [g for g in ats_gap_lines(gap, {}, data) if g["id"] == "ats.title"]
    assert line and '"Data developer"' in line[0]["sentence"] and line[0]["sections"] == ["summary"]
    # Already opening with it (level word dropped): no note.
    done = {**data, "summary": {"text": "Data developer writing SQL daily."}}
    assert ats_gap(done, r, ev(["SQL"]), CFG, title_ok="Data developer")["title_missing"] == ""
    # The plan found no true title: nothing to ask for.
    assert ats_gap(data, r, ev(["SQL"]), CFG)["title_missing"] == ""


def test_plan_title_with_words_left_out_still_counts():
    # Allstate, Oct 23 2026: the summary opened with "Product analyst" for "Provincial Product
    # Analyst", but only the full title counted, so the title note came back every round.
    from src.tailor.grade import ats_gap
    r = {**req(terms=["SQL"]), "title": "Provincial Product Analyst"}
    data = {"summary": {"text": "Product analyst writing SQL daily."}, "skills": [{"items": ["SQL"]}]}
    assert ats_score(data, r, ev(["SQL"]), CFG)["components"]["title"] < 100
    assert ats_score(data, r, ev(["SQL"]), CFG, "Product analyst")["components"]["title"] == 100
    assert ats_gap(data, r, ev(["SQL"]), CFG, title_ok="Product analyst")["title_missing"] == ""
    # A headline with words the posting's title doesn't have earns nothing extra.
    assert ats_score(data, r, ev(["SQL"]), CFG, "Data analyst")["components"]["title"] < 100


def test_title_ok_reads_the_plan_headline(tmp_path):
    from src.tailor.grade import title_ok
    assert title_ok(tmp_path) == ""
    write_json(tmp_path / "plan.json", {"headline": None})
    assert title_ok(tmp_path) == ""
    write_json(tmp_path / "plan.json", {"headline": " Product analyst "})
    assert title_ok(tmp_path) == "Product analyst"


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


def test_regrade_scores_the_ats_again_under_todays_rules(tmp_path):
    # Remarcable, Oct 23 2026: the review page kept an ATS graded under older rules.
    from src.tailor.grade import regrade
    app = make_app(tmp_path)
    fresh = run_grade(app, 1, CFG, FakeJev({}))
    path = app / "drafts" / "r1" / "grade.json"
    stale = {**fresh, "ats": {"total": 10.0, "components": {}}, "ats_ceiling": 99.0, "score": 1.0,
             "gaps": [{"id": "ats.unused", "sentence": "Use the posting's own words: old."}],
             "feedback": ["Use the posting's own words: old.", "kept"]}
    write_json(path, stale)
    out = regrade(app, 1, CFG)
    assert out["ats"] == fresh["ats"] and out["ats_ceiling"] == fresh["ats_ceiling"]
    assert out["score"] == fresh["score"] and out["checklist"] == fresh["checklist"]
    assert "Use the posting's own words: old." not in out["feedback"] and "kept" in out["feedback"]
    assert json.loads(path.read_text())["ats_ceiling"] == 99.0  # nothing written
    assert regrade(app, 2, CFG) is None


def test_regrade_scores_the_resume_that_ships(tmp_path):
    # Amazon ICQA, Oct 27 2026: a line fixed by hand in the humanized copy kept the draft's ATS.
    from src.tailor.grade import regrade
    app = make_app(tmp_path)
    fresh = run_grade(app, 1, CFG, FakeJev({}))
    shipped = base()
    shipped["summary"]["text"] = "Analyst."
    for e in shipped["experience"]:
        for b in e.get("bullets") or []:
            b["text"] = "Did work."
    (app / "humanize").mkdir()
    (app / "humanize" / "resume.yaml").write_text(yaml.safe_dump(shipped, sort_keys=False), encoding="utf-8")
    write_json(app / "humanize" / "round.json", {"round": 1})
    write_json(app / "app.json", {"company": "Contoso Retail", "history": [], "best_round": 1})
    assert regrade(app, 1, CFG)["ats"]["total"] < fresh["ats"]["total"]
    # A humanized copy from another round isn't this round's resume.
    write_json(app / "humanize" / "round.json", {"round": 2})
    write_json(app / "app.json", {"company": "Contoso Retail", "history": [], "best_round": 2})
    assert regrade(app, 1, CFG)["ats"] == fresh["ats"]


def test_run_grade_without_jev_marks_everything_unchecked(tmp_path):
    app = make_app(tmp_path)
    out = run_grade(app, 1, CFG, FakeJev({}))
    assert out["checklist"] and all(it["source"] == "unchecked" and it["passed"] is None for it in out["checklist"])
    assert out["score"] == pytest.approx(0.6 * out["ats"]["total"] + 40.0, abs=0.06)
    saved = json.loads((app / "drafts" / "r1" / "grade.json").read_text())
    assert saved["score"] == out["score"]
    ids = {it["id"] for it in out["checklist"]}
    assert {"must.r1", "must.r2", "top_third", "letter.specific", "letter.opener", "letter.closer"} <= ids
    # "Could this bullet describe almost any candidate?" came back at 0.6 confidence or less on 125
    # of 152 answers (Oct 22 2026) and never failed above 0.6, so it isn't asked.
    assert not any(i.startswith("portable.") for i in ids)


def test_failed_items_become_feedback_without_question_text(tmp_path):
    app = make_app(tmp_path)

    def answers(state, q):
        if q.id == "letter.opener":
            return 0.9  # "yes, could open any letter" -> fail
        if q.id == "letter.specific":
            return 0.2
        return 0.8

    jev = FakeJev(answers)
    out = run_grade(app, 1, CFG, jev)
    by_id = {it["id"]: it for it in out["checklist"]}
    assert by_id["must.r1"]["passed"] is True and by_id["must.r1"]["source"] == "jev"
    assert by_id["letter.specific"]["passed"] is False
    assert by_id["letter.opener"]["passed"] is False and by_id["letter.opener"]["p_pass"] == 0.1
    fb = " ".join(out["feedback"])
    assert "Must-have dbt isn't shown; passage northwind.dbt supports it." in out["feedback"]
    assert "Contoso Retail" in fb
    for it in out["checklist"]:
        assert it["question"] not in out["feedback"] and "backed by a resume bullet" not in fb
    # the state sent to Jev has the name removed
    assert "Rivera" not in jev.calls[0][0]


def test_unshown_must_feedback_names_only_backed_terms(tmp_path):
    # "Looker" comes first but the vault can't back it; repair must only be asked for dbt.
    app = make_app(tmp_path)
    r = json.loads((app / "requirements.json").read_text())
    r["requirements"][1] = {**r["requirements"][1], "text": "Looker and dbt", "terms": ["Looker", "dbt"]}
    write_json(app / "requirements.json", r)
    out = run_grade(app, 1, CFG, FakeJev(lambda state, q: 0.8))
    assert "Must-have dbt isn't shown; passage northwind.dbt supports it." in out["feedback"]
    assert not any("Looker" in s and s.startswith("Must-have") for s in out["feedback"])


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


def test_jev_failure_means_unchecked(tmp_path):
    class Boom:
        def ask(self, state, questions):
            raise NotImplementedError

    out = run_grade(make_app(tmp_path), 1, CFG, Boom())
    assert all(it["source"] == "unchecked" for it in out["checklist"])


def test_failed_checklist_lowers_score(tmp_path):
    app = make_app(tmp_path)
    good = run_grade(app, 1, CFG, FakeJev(lambda s, q: 0.9 if q.id == "top_third" else 0.9))
    bad = run_grade(app, 1, CFG, FakeJev(lambda s, q: 0.1 if q.id == "top_third" else 0.9))
    assert bad["score"] < good["score"]
    assert good["ats"]["total"] == bad["ats"]["total"]


def test_checklist_counts_jevs_probability_not_yes_or_no(tmp_path):
    # A 0.51 yes and a 0.49 no are the same coin flip; they shouldn't move the score 1/n apart.
    app = make_app(tmp_path)
    yes = run_grade(app, 1, CFG, FakeJev(lambda s, q: 0.51 if q.id == "top_third" else 0.9))
    no = run_grade(app, 1, CFG, FakeJev(lambda s, q: 0.49 if q.id == "top_third" else 0.9))
    top = {it["id"]: it for it in no["checklist"]}["top_third"]
    assert top["passed"] is False and top["p_pass"] == 0.49
    assert yes["score"] - no["score"] < 0.5


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


def test_soft_skill_the_letter_names_is_not_asked_for_again(tmp_path):
    # The note says "neither draft names yet", so a soft skill the letter says isn't on it.
    app = make_app(tmp_path)
    r = json.loads((app / "requirements.json").read_text())
    r["requirements"][1] = {**r["requirements"][1], "text": "Strong communication", "terms": ["communication"]}
    write_json(app / "requirements.json", r)
    e = json.loads((app / "evidence.json").read_text())
    e["present"] = list(e.get("present") or []) + ["communication"]
    write_json(app / "evidence.json", e)
    jev = FakeJev(lambda state, q: 0.2 if q.id == "must.r2" else 0.8)
    assert "communication" in run_grade(app, 1, CFG, jev)["unused_soft_terms"]
    letter_path = app / "drafts" / "r1" / "cover-letter.json"
    letter = json.loads(letter_path.read_text())
    letter["paragraphs"].append({"text": "Clear communication with the store teams mattered most.",
                                 "sources": [], "company_facts": []})
    letter_path.write_text(json.dumps(letter))
    out = run_grade(app, 1, CFG, jev)
    assert "communication" not in out["unused_soft_terms"]
    assert not any(g["id"] == "ats.soft" for g in out["gaps"])


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


def test_degree_meeting_the_level_passes_a_related_field_requirement_by_rule(tmp_path):
    app = make_app(tmp_path)
    r = json.loads((app / "requirements.json").read_text())
    r["requirements"][1] = {**r["requirements"][1], "text": "Bachelor's degree in Statistics or a related field",
                            "terms": [], "quote": "Bachelor's degree in Statistics, Economics or a related field."}
    write_json(app / "requirements.json", r)
    ev = json.loads((app / "evidence.json").read_text())
    ev["requirements"] = [e for e in ev.get("requirements") or [] if e.get("id") != "r2"] + [
        {"id": "r2", "status": "covered", "strength": 2, "passages": [], "method": "degree"}]
    write_json(app / "evidence.json", ev)
    jev = FakeJev(lambda state, q: 0.2 if q.id == "must.r2" else 0.8)
    item = next(it for it in run_grade(app, 1, {**CFG, "degree_counts_as_related": True}, jev)["checklist"]
                if it["id"] == "must.r2")
    assert item["passed"] is True and item["source"] == "rule"
    # Without Jake's rule, or for a strict field, Jev still decides.
    item = next(it for it in run_grade(app, 1, CFG, jev)["checklist"] if it["id"] == "must.r2")
    assert item["passed"] is False


def test_unshown_must_with_a_degree_match_points_at_the_terms_passage(tmp_path):
    # "5+ years of dbt work with a Bachelor's degree" matched as a degree requirement; the degree
    # line backs no term, so repair must be pointed at dbt's own passage.
    app = make_app(tmp_path)
    e = json.loads((app / "evidence.json").read_text())
    e["requirements"] = [x for x in e["requirements"] if x["id"] != "r2"] + [
        {"id": "r2", "status": "covered", "strength": 2, "passages": ["edu.degree"], "method": "degree"}]
    write_json(app / "evidence.json", e)
    out = run_grade(app, 1, CFG, FakeJev(lambda state, q: 0.8))
    assert "Must-have dbt isn't shown; passage northwind.dbt supports it." in out["feedback"]
    assert not any("edu.degree" in f for f in out["feedback"])


def test_synonym_the_vault_never_says_is_not_pushed(tmp_path):
    # The check flags "data requirements" as invented when the vault only says "requirements
    # gathering", so the grade must not tell repair to use it; both judge against the same text.
    from src.tailor.paths import load_config

    app = make_app(tmp_path)
    (tmp_path / "bases").mkdir()
    shutil.copy(FIX / "base-analyst.yaml", tmp_path / "bases" / "data-analyst.yaml")
    shutil.copy(FIX / "checks" / "plan.json", app / "plan.json")
    idx = json.loads((FIX / "vault-index.json").read_text(encoding="utf-8"))
    idx["passages"].append({**idx["passages"][0], "id": "skills.requirements",
                            "text": "Stakeholder requirements gathering for the operations team"})
    (tmp_path / "vault-index.json").write_text(json.dumps(idx), encoding="utf-8")
    cfg = load_config({"paths": {"bases": str(tmp_path / "bases"), "vault_index": str(tmp_path / "vault-index.json")}})
    r = json.loads((app / "requirements.json").read_text())
    r["keywords"] += [{"term": "data requirements", "weight": "role"}, {"term": "requirements gathering", "weight": "role"}]
    write_json(app / "requirements.json", r)
    e = json.loads((app / "evidence.json").read_text())
    e["present"].append("requirements gathering")
    write_json(app / "evidence.json", e)
    out = run_grade(app, 1, {**cfg, **CFG}, FakeJev({}))
    assert "requirements gathering" in out["unused_terms"]
    assert "data requirements" not in out["unused_terms"]


def test_synonym_is_pushed_when_its_skill_is_confirmed_for_a_passage():
    # A confirmed pair backs the skill's name in any wording (the check's confirmed_for).
    from src.tailor.grade import ats_gap
    r = req(terms=["data requirements"])
    out = ats_gap({"summary": {"text": "Analyst."}}, r, ev(["requirements gathering"]), CFG,
                  ("Mapped what each team needed.", {"requirements gathering"}))
    assert out["unused"] == ["data requirements"]
    out = ats_gap({"summary": {"text": "Analyst."}}, r, ev(["requirements gathering"]), CFG,
                  ("Mapped what each team needed.", set()))
    assert out["unused"] == []


def test_narrower_phrase_backed_only_through_its_skill_is_not_pushed(tmp_path):
    from src.tailor.grade import ats_gap
    r = req(terms=["reporting pipelines", "key performance indicators"])
    out = ats_gap({"summary": {"text": "Analyst."}}, r, ev(["reporting", "KPIs/metrics"]), CFG)
    # "reporting pipelines" is backed as reporting, but the vault doesn't say the phrase.
    assert out["unused"] == ["key performance indicators"]
    assert out["unbacked"] == []
