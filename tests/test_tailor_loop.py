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
    add_round(app, 1, 60, items=[item("a", False)], feedback=["fix a"])
    add_round(app, 2, 66, items=[item("a", False)], feedback=["fix a"])
    out = next_round(app, CFG)
    assert out["action"] == "repair" and out["next_round"] == 3


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
        add_round(app, n, s, items=[item("a", False)], feedback=["fix a"])
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


def test_unfixable_must_does_not_count_as_a_failed_item(tmp_path):
    app = new_app(tmp_path)
    gap = {**item("must.r2", False), "fit_gap": ["C#"]}
    add_round(app, 1, 85, items=[item("must.r1", True), gap], ats=82)
    out = next_round(app, CFG)
    assert out["action"] == "stop" and out["next_round"] is None
