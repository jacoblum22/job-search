"""Tests for src/tailor/loop.py over fixture check/grade files."""

from __future__ import annotations

import json
from pathlib import Path

from src.tailor.appdir import write_json
from src.tailor.loop import next_round

CFG = {"target_score": 80, "loop": {"max_rounds": 3, "min_gain": 2.0}}


def item(iid, passed, sections=None):
    d = {"id": iid, "question": "x", "passed": passed, "confidence": 0.9, "source": "jev"}
    if sections:
        d["sections"] = sections
    return d


def add_round(app, n, score, criticals=(), items=(), ats=70, feedback=(), gaps=()):
    d = app / "drafts" / f"r{n}"
    write_json(d / "check.json", {"criticals": list(criticals), "warnings": [], "flags": [], "reverted": [], "metrics": {}})
    write_json(
        d / "grade.json",
        {"ats": {"total": ats, "components": {}}, "checklist": list(items), "score": score, "stuffing": False,
         "gaps": list(gaps), "feedback": list(feedback)},
    )


def crit(path, doc="resume"):
    return {"code": "invented_number", "message": "m", "path": path, "doc": doc}


def new_app(tmp_path):
    app = tmp_path / "app"
    app.mkdir()
    write_json(app / "app.json", {"history": []})
    return app


def test_stops_when_everything_passes_and_target_met(tmp_path):
    app = new_app(tmp_path)
    add_round(app, 1, 85, items=[item("must.r1", True), item("x", None)], ats=82)
    out = next_round(app, CFG)
    assert out["action"] == "stop" and out["best_round"] == 1 and out["next_round"] is None
    assert not (app / "drafts" / "r2").exists()


def test_first_round_with_failures_repairs_and_writes_feedback_sections(tmp_path):
    app = new_app(tmp_path)
    add_round(
        app, 1, 60,
        criticals=[crit("experience/northwind/northwind.forecast"), crit("letter/1", "letter"), crit("summary")],
        items=[
            item("must.r2", False, ["summary", "skills", "experience/northwind"]),
            item("portable.experience/lab/lab.stats", False, ["experience/lab"]),
            item("top_third", True, ["summary"]),
            item("letter.specific", False, ["letter"]),
        ],
        feedback=["Must-have dbt isn't shown; passage northwind.dbt supports it."],
        gaps=[{"id": "must.r2", "sentence": "s", "sections": ["summary", "skills", "projects/spam"]}],
    )
    out = next_round(app, CFG)
    assert out == {"action": "repair", "best_round": 1, "reason": out["reason"], "next_round": 2}
    fb = json.loads((app / "drafts" / "r2" / "feedback.json").read_text())
    assert fb["round"] == 2
    assert len(fb["criticals"]) == 3
    assert fb["failed_items"] == ["Must-have dbt isn't shown; passage northwind.dbt supports it."]
    assert fb["sections"] == [
        "experience/northwind", "letter", "summary", "skills", "experience/lab", "projects/spam",
    ]
    app_json = json.loads((app / "app.json").read_text())
    assert app_json["rounds"] == [{"round": 1, "score": 60.0, "criticals": 3, "failed_items": 3}]
    assert app_json["best_round"] == 1


def test_stops_on_small_gain_and_keeps_best(tmp_path):
    app = new_app(tmp_path)
    add_round(app, 1, 70, items=[item("a", False)], feedback=["fix a"])
    add_round(app, 2, 71, items=[item("a", False)], feedback=["fix a"])
    out = next_round(app, CFG)
    assert out["action"] == "stop" and "gain" in out["reason"]
    assert out["best_round"] == 2  # still the higher score
    assert not (app / "drafts" / "r3").exists()


def test_continues_on_real_gain(tmp_path):
    app = new_app(tmp_path)
    add_round(app, 1, 60, items=[item("a", False)], feedback=["fix a"], ats=60)
    add_round(app, 2, 66, items=[item("a", False)], feedback=["fix a"], ats=70)
    out = next_round(app, CFG)
    assert out["action"] == "repair" and out["next_round"] == 3


def test_gain_from_extra_questions_alone_is_no_gain(tmp_path):
    # Round 2 changed more bullets, so it was asked more (easy) questions; nothing it was asked
    # both times changed and the ATS didn't move, so the higher score isn't progress.
    app = new_app(tmp_path)
    shared = [item("top_third", False), item("must.r1", True), item("letter.specific", True)]
    add_round(app, 1, 58.2, items=shared + [item("portable.p1", True)], feedback=["fix top"], ats=50.9)
    extra = [item(f"portable.p{i}", True) for i in range(1, 5)]
    add_round(app, 2, 60.5, items=shared + extra, feedback=["fix top"], ats=50.9)
    for n in (1, 2):  # a fit gap: the ATS can't reach the floor, so it earns no rounds itself
        gp = app / "drafts" / f"r{n}" / "grade.json"
        g = json.loads(gp.read_text())
        g.update(needs_ats_repair=False, fit_gap=True)
        gp.write_text(json.dumps(g))
    out = next_round(app, CFG)
    assert out["action"] == "stop" and "gain" in out["reason"]
    assert out["best_round"] == 2


def test_more_criticals_is_a_regression_and_never_best(tmp_path):
    app = new_app(tmp_path)
    add_round(app, 1, 60, items=[item("a", False)], feedback=["fix a"])
    add_round(app, 2, 90, criticals=[crit("summary")], items=[item("a", True)])
    out = next_round(app, CFG)
    assert out["action"] == "stop" and "regression" in out["reason"]
    assert out["best_round"] == 1  # higher score but adds a critical


def test_item_that_passed_before_and_fails_now_is_a_regression(tmp_path):
    app = new_app(tmp_path)
    add_round(app, 1, 60, items=[item("a", True), item("b", False)], feedback=["fix b"])
    add_round(app, 2, 75, items=[item("a", False), item("b", True)], feedback=["fix a"])
    out = next_round(app, CFG)
    assert out["action"] == "stop" and "regression" in out["reason"]
    assert out["best_round"] == 2  # no criticals either way, higher score


def test_round_limit(tmp_path):
    app = new_app(tmp_path)
    for n, s in ((1, 50), (2, 60), (3, 70)):
        add_round(app, n, s, items=[item("a", False)], feedback=["fix a"], ats=s)
    out = next_round(app, CFG)
    assert out["action"] == "stop" and "limit" in out["reason"] and out["best_round"] == 3


def test_best_round_prefers_zero_criticals_then_fewest(tmp_path):
    app = new_app(tmp_path)
    add_round(app, 1, 90, criticals=[crit("summary"), crit("letter", "letter")], items=[item("a", False)])
    add_round(app, 2, 40, criticals=[crit("summary")], items=[item("a", False)])
    out = next_round(app, {**CFG, "loop": {"max_rounds": 2, "min_gain": 2.0}})
    assert out["best_round"] == 2  # all have criticals: fewest wins over score
    add_round(app, 3, 30, items=[item("a", False)])
    assert next_round(app, CFG)["best_round"] == 3  # the only critical-free round


def test_nothing_to_repair_stops(tmp_path):
    app = new_app(tmp_path)
    add_round(app, 1, 70, items=[item("a", True)], ats=70)
    out = next_round(app, CFG)
    assert out["action"] == "stop" and out["next_round"] is None


def test_below_ats_floor_keeps_repairing_despite_small_gain(tmp_path):
    app = new_app(tmp_path)
    cfg = {**CFG, "ats_floor": 70}
    add_round(app, 1, 60.0, ats=51, feedback=["Use the posting's own words for: data analysis."])
    add_round(app, 2, 61.0, ats=55, feedback=["Use the posting's own words for: reports."])
    out = next_round(app, cfg)
    assert out["action"] == "repair" and out["next_round"] == 3
    # at or above the floor the usual small-gain stop applies
    (tmp_path / "b").mkdir()
    app2 = new_app(tmp_path / "b")
    add_round(app2, 1, 60.0, ats=72, feedback=["x"])
    add_round(app2, 2, 61.0, ats=73, feedback=["x"])
    assert next_round(app2, cfg)["action"] == "stop"


def test_fit_gap_stops_on_small_gain_even_below_floor(tmp_path):
    # The evidence can't reach 70, so repairing harder would only stuff keywords.
    app = new_app(tmp_path)
    cfg = {**CFG, "ats_floor": 70}
    add_round(app, 1, 60.0, ats=60, feedback=["x"])
    add_round(app, 2, 61.0, ats=61, feedback=["x"])
    for n in (1, 2):
        gp = app / "drafts" / f"r{n}" / "grade.json"
        g = json.loads(gp.read_text())
        g.update(needs_ats_repair=False, fit_gap=True)
        gp.write_text(json.dumps(g))
    assert next_round(app, cfg)["action"] == "stop"


def test_ats_wording_line_alone_needs_no_round_when_the_ats_needs_no_repair(tmp_path):
    # The ATS is already at what the evidence can reach: the wording line alone would be an empty round.
    app = new_app(tmp_path)
    line = "Use the posting's own words for these terms the vault backs: forecast dashboards."
    add_round(app, 1, 60.0, ats=52, items=[item("must.r1", True)], feedback=[line],
              gaps=[{"id": "ats.unused", "sentence": line, "sections": ["summary"]}])
    gp = app / "drafts" / "r1" / "grade.json"
    g = json.loads(gp.read_text())
    g.update(needs_ats_repair=False, fit_gap=True)
    gp.write_text(json.dumps(g))
    out = next_round(app, {**CFG, "ats_floor": 70})
    assert out["action"] == "stop" and out["reason"] == "nothing left to repair"
    # With a wording gap the same line still earns a round.
    g.update(needs_ats_repair=True, fit_gap=False)
    gp.write_text(json.dumps(g))
    assert next_round(app, {**CFG, "ats_floor": 70})["action"] == "repair"


def test_unfixable_must_does_not_count_as_a_failed_item(tmp_path):
    app = new_app(tmp_path)
    gap = {**item("must.r2", False), "fit_gap": ["C#"]}
    add_round(app, 1, 85, items=[item("must.r1", True), gap], ats=82)
    out = next_round(app, CFG)
    assert out["action"] == "stop" and out["next_round"] is None


def test_coin_flip_jev_answer_is_not_a_regression(tmp_path):
    app = new_app(tmp_path)
    add_round(app, 1, 60, items=[item("a", True), item("b", False)], feedback=["fix b"])
    flip = dict(item("a", False), confidence=0.5)
    add_round(app, 2, 66, items=[flip, item("b", True)], feedback=["fix a"])
    out = next_round(app, CFG)
    assert "regression" not in out["reason"]


def test_stuffing_warning_earns_a_round_and_reaches_feedback(tmp_path):
    app = new_app(tmp_path)
    add_round(app, 1, 85, items=[item("a", True)], ats=60)
    check = json.loads((app / "drafts" / "r1" / "check.json").read_text())
    check["warnings"] = [
        {"code": "term_stuffing", "message": "'BigQuery' appears 7 times", "path": "", "doc": "resume",
         "data": {"term": "BigQuery", "paths": ["summary", "experience/algaecal/algaecal.sql"]}},
        {"code": "ai_phrase", "message": "leverage", "path": "summary", "doc": "resume"},
    ]
    write_json(app / "drafts" / "r1" / "check.json", check)
    out = next_round(app, {**CFG, "target_score": 80})
    assert out["action"] == "repair"
    fb = json.loads((app / "drafts" / "r2" / "feedback.json").read_text())
    assert [w["code"] for w in fb["warnings"]] == ["term_stuffing"]
    assert fb["sections"] == ["summary", "experience/algaecal"]


def test_ride_along_warning_alone_does_not_earn_a_round(tmp_path):
    app = new_app(tmp_path)
    add_round(app, 1, 85, items=[item("a", True)], ats=60)
    check = json.loads((app / "drafts" / "r1" / "check.json").read_text())
    check["warnings"] = [{"code": "skill_only_in_list", "message": "m", "path": "skills", "doc": "resume"}]
    write_json(app / "drafts" / "r1" / "check.json", check)
    out = next_round(app, CFG)
    assert out["action"] == "stop" and "nothing left" in out["reason"]


def test_skill_the_draft_added_to_the_list_only_earns_a_round(tmp_path):
    app = new_app(tmp_path)
    add_round(app, 1, 85, items=[item("a", True)], ats=60)
    check = json.loads((app / "drafts" / "r1" / "check.json").read_text())
    check["warnings"] = [{"code": "skill_only_in_list", "message": "m", "path": "skills", "doc": "resume",
                          "data": {"term": "AWS S3", "added": True}}]
    write_json(app / "drafts" / "r1" / "check.json", check)
    assert next_round(app, CFG)["action"] == "repair"


def test_best_round_ignores_coin_flip_jev_answers(tmp_path):
    # Amazon BI Engineer, Oct 22 2026 (real answers): round 2 used the posting's words (ATS 56.6 ->
    # 60.2). Its firm answers matched round 1's, but its 50/50 answers came up no where round 1's
    # came up yes, and round 1 asked about more lines, so round 1 scored 67.3 to 62.8 and was kept.
    def jev(iid, passed, conf):
        return {**item(iid, passed), "confidence": conf}

    same = [jev("must.r7", False, 0.97), jev("must.r8", False, 0.8), item("must.r9", True),
            jev("must.r11", True, 0.87), jev("must.r12", False, 0.65), jev("must.r13", True, 0.96),
            jev("must.r14", True, 0.92), jev("top_third", True, 0.71), jev("letter.specific", True, 0.96),
            jev("letter.opener", True, 0.86), jev("letter.closer", True, 0.65)]
    r1 = same + [jev("must.r10", True, 0.54), jev("portable.sql", True, 0.51), jev("portable.apps", True, 0.52)] + [
        jev(f"portable.p{i}", True, 0.52) for i in range(4)]
    add_round(app := new_app(tmp_path), 1, 67.3, items=r1, ats=56.6, feedback=["fix"])
    r2 = same + [jev("must.r10", False, 0.55), jev("portable.sql", False, 0.5), jev("portable.apps", True, 0.51),
                 jev("portable.std", True, 0.51)]
    add_round(app, 2, 62.8, items=r2, ats=60.2, feedback=["fix"])
    assert next_round(app, CFG)["best_round"] == 2
