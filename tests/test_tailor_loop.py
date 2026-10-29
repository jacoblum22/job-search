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


def test_wide_gap_keeps_repairing_despite_small_gain(tmp_path):
    # Jake, Oct 29 2026: no fixed 70 target. More than loop.wide_gap (8) under the ceiling keeps
    # repairing on a small gain, even above 70 (Quora Full Stack stopped at 71.6 with 79.5 reachable).
    app = new_app(tmp_path)
    add_round(app, 1, 60.0, ats=70, feedback=["Use the posting's own words for: data analysis."])
    add_round(app, 2, 61.0, ats=71, feedback=["Use the posting's own words for: reports."])
    for n in (1, 2):
        _set_grade(app, n, ats_ceiling=80)
    out = next_round(app, CFG)
    assert out["action"] == "repair" and out["next_round"] == 3
    # within wide_gap of the ceiling the usual small-gain stop applies, even under 70
    (tmp_path / "b").mkdir()
    app2 = new_app(tmp_path / "b")
    add_round(app2, 1, 60.0, ats=62, feedback=["x"])
    add_round(app2, 2, 61.0, ats=63, feedback=["x"])
    for n in (1, 2):
        _set_grade(app2, n, ats_ceiling=68)
    assert next_round(app2, CFG)["action"] == "stop"


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
    # The phrase warning rides along with the round (pipeline audit, Oct 29 2026), it doesn't start one.
    assert [w["code"] for w in fb["warnings"]] == ["term_stuffing", "ai_phrase"]
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
    # Counted by probability over the shared questions, the coin flips cancel and the ATS decides.
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


def test_regression_with_a_wording_gap_repairs_again_from_the_best_round(tmp_path):
    # REW.ca Data Engineer, Oct 20 2026: round 2 failed an item round 1 passed and the loop
    # stopped at ATS 57.1 with 75.3 reachable. A wording gap that big earns another round, from round 1.
    app = new_app(tmp_path)
    add_round(app, 1, 65.6, items=[item("a", True), item("b", False)], ats=56.0, feedback=["use the words: cloud"])
    add_round(app, 2, 57.6, items=[item("a", False), item("b", False)], ats=57.1, feedback=["r2 notes"])
    for n in (1, 2):
        gp = app / "drafts" / f"r{n}" / "grade.json"
        g = json.loads(gp.read_text())
        g["needs_ats_repair"] = True
        gp.write_text(json.dumps(g))
    out = next_round(app, CFG)
    assert out["action"] == "repair" and out["next_round"] == 3 and "from round 1" in out["reason"]
    fb = json.loads((app / "drafts" / "r3" / "feedback.json").read_text())
    assert fb["build_on"] == 1 and fb["failed_items"] == ["use the words: cloud"]
    # REW.ca's own shape: round 1 had criticals, so round 2 is still the best and round 3 builds on it
    (tmp_path / "c").mkdir()
    app3 = new_app(tmp_path / "c")
    add_round(app3, 1, 65.6, criticals=[crit("summary")], items=[item("a", True)], ats=56.0, feedback=["r1"])
    add_round(app3, 2, 57.6, items=[item("a", False)], ats=57.1, feedback=["r2 words: cloud"])
    gp = app3 / "drafts" / "r2" / "grade.json"
    g = json.loads(gp.read_text())
    g["needs_ats_repair"] = True
    gp.write_text(json.dumps(g))
    assert next_round(app3, CFG)["action"] == "repair"
    assert json.loads((app3 / "drafts" / "r3" / "feedback.json").read_text())["build_on"] == 2
    # without a wording gap the regression still stops the loop
    (tmp_path / "b").mkdir()
    app2 = new_app(tmp_path / "b")
    add_round(app2, 1, 65.6, items=[item("a", True)], ats=72, feedback=["x"])
    add_round(app2, 2, 57.6, items=[item("a", False)], ats=72, feedback=["x"])
    assert next_round(app2, CFG)["reason"].startswith("regression")


def test_pending_round_is_a_round_asked_for_and_never_graded(tmp_path):
    from src.tailor.loop import pending_round

    app = new_app(tmp_path)
    add_round(app, 1, 60, items=[item("must.r1", False, ["summary"])], ats=60, feedback=["show SQL"])
    assert pending_round(app) is None
    next_round(app, CFG)
    assert pending_round(app) == 2
    add_round(app, 2, 70, items=[item("must.r1", True)], ats=66)
    assert pending_round(app) is None


def _letter_app(tmp_path, monkeypatch, warnings):
    import src.tailor.checks as checks

    app = new_app(tmp_path)
    add_round(app, 1, 60, ats=60)
    add_round(app, 2, 70, ats=66)
    write_json(app / "app.json", {"history": [], "best_round": 2})
    calls = []

    def fake_recheck(app_dir, rnd, cfg):
        calls.append(rnd)
        return {"criticals": [], "warnings": warnings}

    monkeypatch.setattr(checks, "recheck", fake_recheck)
    return app, calls


SHORT = {"code": "letter_length", "message": "214 words; aim for about 250-300 (add a little); use the room "
         "to show Airflow", "path": "letter", "doc": "letter", "data": {"words": 214, "show": ["Airflow"]}}


def test_letter_round_asked_for_when_the_best_letter_fails_todays_rules(tmp_path, monkeypatch):
    from src.tailor.loop import letter_round, pending_round

    app, calls = _letter_app(tmp_path, monkeypatch, [SHORT, {**SHORT, "code": "ai_phrase"}])
    fb = letter_round(app, CFG)
    assert calls == [2]
    assert fb["round"] == 3 and fb["build_on"] == 2 and fb["letter_only"] is True
    assert fb["sections"] == ["letter"] and [w["code"] for w in fb["warnings"]] == ["letter_length"]
    assert "Airflow" in fb["warnings"][0]["message"]
    assert pending_round(app) == 3
    # Already waiting: not asked for twice.
    assert letter_round(app, CFG) is None


def test_letter_round_not_asked_for_a_good_letter(tmp_path, monkeypatch):
    from src.tailor.loop import letter_round

    app, _ = _letter_app(tmp_path, monkeypatch, [{**SHORT, "doc": "resume", "code": "term_stuffing"}])
    assert letter_round(app, CFG) is None
    assert not (app / "drafts" / "r3").exists()


def test_letter_round_asked_for_soft_skills_neither_draft_names(tmp_path, monkeypatch):
    # REW.ca, Oct 23 2026: the letter told teamwork stories but never said "teamwork", and with the
    # rounds used up the soft-skill note was never acted on.
    import src.tailor.loop as loop

    app, _ = _letter_app(tmp_path, monkeypatch, [])
    monkeypatch.setattr(loop, "soft_for_letter", lambda *a: ["teamwork", "communication"])
    fb = loop.letter_round(app, CFG)
    assert fb["letter_only"] is True and fb["warnings"] == [] and fb["sections"] == ["letter"]
    assert fb["failed_items"] == [loop.LETTER_SOFT + "teamwork, communication."]
    # Once per best round, like any letter round.
    add_round(app, 3, 70, ats=66)
    assert loop.letter_round(app, CFG) is None


def test_letter_round_keeps_soft_skills_the_letter_already_names(tmp_path, monkeypatch):
    # REW.ca, Oct 23 2026: rewording a sentence for "teamwork" dropped "knowledge sharing", which
    # only the old letter named, and the loop ended without saying so.
    import src.tailor.loop as loop

    app, _ = _letter_app(tmp_path, monkeypatch, [])
    monkeypatch.setattr(loop, "soft_for_letter", lambda *a: ["teamwork"])
    monkeypatch.setattr(loop, "soft_in_letter", lambda *a: ["mentoring", "knowledge sharing"])
    fb = loop.letter_round(app, CFG)
    assert fb["keep_soft"] == ["mentoring", "knowledge sharing"]
    assert fb["failed_items"][-1] == loop.LETTER_KEEP + "mentoring, knowledge sharing."
    add_round(app, 3, 70, ats=66)
    write_json(app / "drafts" / "r3" / "cover-letter.json", {"paragraphs": [
        {"text": "Teamwork meant mentoring two new hires through the reporting stack."}]})
    out = next_round(app, CFG)
    assert out["best_round"] == 3
    assert out["reason"].endswith("the new letter no longer names knowledge sharing, which round 2's did")


def test_unsaid_soft_keeps_apart_the_ones_only_the_letter_names():
    from src.tailor.grade import unsaid_soft

    gap = {"unused_soft": ["teamwork", "knowledge sharing"]}
    unsaid_soft(gap, [], {"requirements": []}, {"paragraphs": [{"text": "I shared knowledge-sharing notes."}]})
    assert gap["unused_soft"] == ["teamwork"] and gap["letter_soft"] == ["knowledge sharing"]


def test_letter_round_ends_the_loop_and_becomes_best(tmp_path, monkeypatch):
    from src.tailor.loop import letter_round

    app, _ = _letter_app(tmp_path, monkeypatch, [SHORT])
    letter_round(app, CFG)
    # Jev's answers on the same resume came out a little lower: still the letter round wins.
    add_round(app, 3, 68, ats=66)
    out = next_round(app, CFG)
    assert out["action"] == "stop" and out["best_round"] == 3 and "letter round done" in out["reason"]
    assert not (app / "drafts" / "r4").exists()
    # One try per best round: the letter round is the best now and isn't redone.
    assert letter_round(app, CFG) is None


def test_letter_round_that_adds_a_critical_keeps_the_round_it_built_on(tmp_path, monkeypatch):
    from src.tailor.loop import letter_round

    app, _ = _letter_app(tmp_path, monkeypatch, [SHORT])
    letter_round(app, CFG)
    add_round(app, 3, 72, criticals=[crit("letter", "letter")], ats=66)
    out = next_round(app, CFG)
    assert out["action"] == "stop" and out["best_round"] == 2
    write_json(app / "app.json", {**json.loads((app / "app.json").read_text()), "best_round": 2})
    # The try was spent on round 2: no new letter round every day.
    assert letter_round(app, CFG) is None


def _set_grade(app, n, **fields):
    p = app / "drafts" / f"r{n}" / "grade.json"
    write_json(p, {**json.loads(p.read_text()), **fields})


WIDE = {**CFG, "loop": {**CFG["loop"], "wide_gap": 10, "max_rounds_wide_gap": 5}}


def test_wide_gap_that_still_gains_gets_rounds_past_the_limit(tmp_path):
    # Jake, Oct 23 2026: more than 10 under what the evidence allows isn't acceptable.
    app = new_app(tmp_path)
    for n, ats in ((1, 50), (2, 54), (3, 58)):
        add_round(app, n, 60 + n, items=[item("must.r1", False, ["summary"])], ats=ats, feedback=["show SQL"])
        _set_grade(app, n, ats_ceiling=75, needs_ats_repair=True)
    out = next_round(app, WIDE)
    assert out["action"] == "repair" and out["next_round"] == 4
    # Without the wide gap the usual limit holds.
    for n in (1, 2, 3):
        _set_grade(app, n, ats_ceiling=62)
    (app / "drafts" / "r4" / "feedback.json").unlink()
    assert next_round(app, WIDE)["action"] == "stop"


def test_eight_points_under_is_a_wide_gap(tmp_path):
    # Jake, Oct 28 2026: Nexthop new grad stopped at 3 drafts on ATS 65.5 with 74 reachable (8.5 under)
    # though the last round gained 3.2; the wide gap is now 8 points.
    app = new_app(tmp_path)
    for n, ats in ((1, 62.3), (2, 62.3), (3, 65.5)):
        add_round(app, n, 60 + n, items=[item("must.r1", False, ["summary"])], ats=ats, feedback=["show SQL"])
        _set_grade(app, n, ats_ceiling=74, needs_ats_repair=True)
    cfg = {**CFG, "loop": {**CFG["loop"], "wide_gap": 8, "max_rounds_wide_gap": 5}}
    out = next_round(app, cfg)
    assert out["action"] == "repair" and out["next_round"] == 4


def test_wide_gap_that_stopped_gaining_stops_at_the_limit(tmp_path):
    app = new_app(tmp_path)
    for n, ats in ((1, 50), (2, 58), (3, 58)):
        add_round(app, n, 60 + n, items=[item("must.r1", False, ["summary"])], ats=ats, feedback=["show SQL"])
        _set_grade(app, n, ats_ceiling=75, needs_ats_repair=True)
    out = next_round(app, WIDE)
    assert out["action"] == "stop" and "round limit" in out["reason"]


def test_round_limit_reason_counts_the_drafts_past_it(tmp_path):
    # REW.ca, Oct 22 2026: a 4th draft (the round pending asked for) stopped with "round limit of 3".
    app = new_app(tmp_path)
    for n, ats in ((1, 50), (2, 54), (3, 58), (4, 62)):
        add_round(app, n, 60 + n, items=[item("must.r1", False, ["summary"])], ats=ats, feedback=["show SQL"])
    out = next_round(app, CFG)
    assert out["action"] == "stop" and out["reason"] == "round limit of 3 reached (4 drafts with the one pending asked for)"


def test_soft_skill_note_alone_does_not_start_a_round(tmp_path):
    app = new_app(tmp_path)
    soft = "Soft skills the vault shows that neither draft names yet: teamwork."
    add_round(app, 1, 70, ats=72, feedback=[soft], gaps=[{"id": "ats.soft", "sentence": soft, "sections": ["letter"]}])
    _set_grade(app, 1, needs_ats_repair=False)
    out = next_round(app, CFG)
    assert out["action"] == "stop" and out["reason"] == "nothing left to repair"


def test_title_note_counts_as_a_wording_gap(tmp_path):
    title = 'Open the summary\'s first sentence with the job title "Data developer", worded as ...'
    for needs, action in ((False, "stop"), (True, "repair")):
        # Advice only while the ATS is within reach, a reason for a round when it isn't.
        (tmp_path / str(needs)).mkdir()
        app = new_app(tmp_path / str(needs))
        add_round(app, 1, 60, ats=58, feedback=[title],
                  gaps=[{"id": "ats.title", "sentence": title, "sections": ["summary"]}])
        _set_grade(app, 1, needs_ats_repair=needs)
        assert next_round(app, CFG)["action"] == action
    assert title in json.loads((app / "drafts" / "r2" / "feedback.json").read_text())["failed_items"]


def test_gap_round_builds_on_a_letter_round(tmp_path, monkeypatch):
    # Remarcable and Allstate, Oct 23 2026: their best round was a letter-only round.
    import src.tailor.grade as grade
    from src.tailor.loop import gap_round

    app = new_app(tmp_path)
    add_round(app, 1, 60, ats=55)
    add_round(app, 2, 61, ats=55)
    write_json(app / "drafts" / "r2" / "feedback.json", {"round": 2, "build_on": 1, "letter_only": True})
    write_json(app / "app.json", {"history": [], "best_round": 2})
    write_json(app / "requirements.json", {"requirements": []})
    (app / "drafts" / "r2" / "resume.yaml").write_text("summary:\n  text: Analyst.\n", encoding="utf-8")
    line = {"id": "ats.unused", "sentence": "Use the posting's own words ...: SQL.", "sections": ["summary"]}
    monkeypatch.setattr(grade, "graded_evidence", lambda *a: {})
    monkeypatch.setattr(grade, "_vault_wording", lambda *a: None)
    monkeypatch.setattr(grade, "ats_gap", lambda *a, **k: {"unused": ["SQL"], "unused_soft": [], "ceiling": 80.0})
    monkeypatch.setattr(grade, "ats_score", lambda *a: {"total": 55.0})
    monkeypatch.setattr(grade, "ats_gap_lines", lambda *a: [line])
    fb = gap_round(app, CFG)
    assert fb and fb["round"] == 3 and fb["build_on"] == 2


def test_gap_round_asked_for_when_the_best_round_is_far_under_reach(tmp_path, monkeypatch):
    import src.tailor.grade as grade
    from src.tailor.loop import gap_round, pending_round

    app = new_app(tmp_path)
    add_round(app, 1, 60, ats=55, feedback=["Use the posting's own words for these terms the vault backs: old."],
              gaps=[{"id": "ats.unused", "sentence": "Use the posting's own words for these terms the vault backs: old.",
                     "sections": ["summary"]}])
    add_round(app, 2, 62, ats=58, feedback=["Use the posting's own words for these terms the vault backs: old."])
    write_json(app / "app.json", {"history": [], "best_round": 2})
    write_json(app / "requirements.json", {"requirements": []})
    (app / "drafts" / "r2" / "resume.yaml").write_text("summary:\n  text: Analyst.\n", encoding="utf-8")
    line = {"id": "ats.unused", "sentence": "Use the posting's own words ...: coding best practices.",
            "sections": ["experience/algaecal"]}
    gap = {"unused": ["coding best practices"], "unused_soft": [], "ceiling": 72.0}
    monkeypatch.setattr(grade, "graded_evidence", lambda *a: {})
    monkeypatch.setattr(grade, "_vault_wording", lambda *a: None)
    monkeypatch.setattr(grade, "ats_gap", lambda *a, **k: gap)
    monkeypatch.setattr(grade, "ats_score", lambda *a: {"total": 58.3})
    monkeypatch.setattr(grade, "ats_gap_lines", lambda *a: [line])
    fb = gap_round(app, CFG)
    assert fb["round"] == 3 and fb["build_on"] == 2 and fb["revisit"] is True
    assert fb["failed_items"] == [line["sentence"]] and "experience/algaecal" in fb["sections"]
    assert pending_round(app) == 3
    # One try per best round.
    add_round(app, 3, 63, ats=60)
    assert gap_round(app, CFG) is None
    # Within 8 of the ceiling: no round.
    app2 = tmp_path / "b"
    app2.mkdir()
    write_json(app2 / "app.json", {"history": [], "best_round": 1})
    write_json(app2 / "requirements.json", {"requirements": []})
    add_round(app2, 1, 60, ats=65)
    (app2 / "drafts" / "r1" / "resume.yaml").write_text("summary:\n  text: Analyst.\n", encoding="utf-8")
    monkeypatch.setattr(grade, "ats_score", lambda *a: {"total": 65.0})
    assert gap_round(app2, CFG) is None


def test_gap_round_soft_note_leaves_out_what_the_letter_already_says(tmp_path, monkeypatch):
    # VCH Junior Data Developer, Oct 22 2026: the round asked for a soft skill again after the
    # letter said it.
    import src.tailor.grade as grade
    from src.tailor.loop import gap_round

    app = new_app(tmp_path)
    add_round(app, 1, 60, ats=55)
    write_json(app / "app.json", {"history": [], "best_round": 1})
    write_json(app / "requirements.json", {"requirements": []})
    (app / "drafts" / "r1" / "resume.yaml").write_text("summary:\n  text: Analyst.\n", encoding="utf-8")
    write_json(app / "drafts" / "r1" / "cover-letter.json",
               {"paragraphs": [{"text": "At Northwind I ran cross-functional reviews with the store teams."}]})
    gap = {"unused": ["dbt"], "unused_soft": ["cross-functional", "teamwork"], "ceiling": 72.0}
    monkeypatch.setattr(grade, "graded_evidence", lambda *a: {})
    monkeypatch.setattr(grade, "_vault_wording", lambda *a: None)
    monkeypatch.setattr(grade, "ats_gap", lambda *a, **k: gap)
    monkeypatch.setattr(grade, "ats_score", lambda *a: {"total": 55.0})
    fb = gap_round(app, CFG)
    soft = [f for f in fb["failed_items"] if f.startswith("Soft skills")]
    assert soft and soft[0].endswith("through a story: teamwork.")


# Pipeline audit, Oct 29 2026.


def test_a_round_that_changed_nothing_ends_the_loop(tmp_path):
    import yaml

    app = new_app(tmp_path)
    resume = {"summary": {"id": "summary", "text": "Analyst who writes SQL.", "sources": ["a"]}}
    for n in (1, 2):
        add_round(app, n, 60 + n * 3, items=[item("a", False)], ats=60, feedback=["fix a"])
        (app / "drafts" / f"r{n}" / "resume.yaml").write_text(yaml.safe_dump(resume), encoding="utf-8")
        resume = {"summary": {**resume["summary"], "sources": ["a", "b"]}}  # citations only: same text
    write_json(app / "drafts" / "r2" / "feedback.json", {"round": 2, "build_on": 1})
    out = next_round(app, CFG)
    assert out["action"] == "stop" and "left the resume and letter as round 1 had them" in out["reason"]


def test_rounds_are_compared_on_todays_ats(tmp_path, monkeypatch):
    from src.tailor import loop

    app = new_app(tmp_path)
    add_round(app, 1, 64, items=[item("a", False)], ats=60, feedback=["fix a"])
    add_round(app, 2, 70, items=[item("a", False)], ats=70, feedback=["fix a"])
    # Stored, round 2 gained 6 points; under today's rules both score 70, so it gained nothing.
    monkeypatch.setattr(loop, "_todays_ats", lambda app_dir, cfg: (lambda n: 70.0))
    out = next_round(app, CFG)
    assert out["action"] == "stop" and "gain under" in out["reason"]
