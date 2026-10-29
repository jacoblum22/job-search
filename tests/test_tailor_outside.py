"""Tests for src/tailor/outside.py: the outside review and the round that acts on it."""

from __future__ import annotations

import json

import yaml

from src.tailor.appdir import write_json
from src.tailor.loop import next_round, pending_round
from src.tailor.outside import (
    changed_since_review,
    kept,
    parse_notes,
    response,
    resume_text,
    review_input,
    review_round,
    summary,
)
from tests.test_tailor_loop import CFG, add_round, crit

RESUME = {
    "id": "data-analyst-bi",
    "contact": {"name": "Jake"},
    "order": ["summary", "skills", "experience", "education"],
    "summary": {"id": "summary", "text": "Data analyst who wrote SQL daily.", "sources": ["a.sql"]},
    "skills": [{"id": "skills.languages", "label": "Languages", "items": ["SQL", "Python"]}],
    "experience": [{"id": "northwind", "title": "Analyst", "company": "Northwind", "location": "Vancouver, BC",
                    "dates": "Jun 2026 – Oct 2026",
                    "bullets": [{"id": "northwind.sql", "text": "Wrote SQL daily.", "sources": ["a.sql"]}]}],
    "education": [{"id": "ubc", "school": "UBC", "degree": "BSc", "dates": "2022 – 2026",
                   "lines": [{"id": "ubc.coursework", "label": "Coursework", "text": "Databases"}]}],
}
LETTER = {"greeting": "Dear Hiring Manager,", "paragraphs": [{"text": "I wrote SQL.", "sources": ["a.sql"]}],
          "sign_off": "Best regards,\nJake"}


def _app(tmp_path, best=2):
    app = tmp_path / "app"
    app.mkdir()
    write_json(app / "app.json", {"history": [], "best_round": best})
    (app / "posting.md").write_text("# Data Analyst\n\nBuild data pipelines.", encoding="utf-8")
    for n in (1, 2):
        add_round(app, n, 70, ats=66)
        d = app / "drafts" / f"r{n}"
        (d / "resume.yaml").write_text(yaml.safe_dump(RESUME, sort_keys=False), encoding="utf-8")
        write_json(d / "cover-letter.json", LETTER)
    return app


def test_resume_text_reads_like_the_page_without_ids_or_sources():
    text = resume_text(RESUME)
    assert "Data analyst who wrote SQL daily." in text and "Languages: SQL, Python" in text
    assert "Analyst, Northwind, Vancouver, BC (Jun 2026 – Oct 2026)" in text and "- Wrote SQL daily." in text
    assert "Coursework: Databases" in text
    assert "a.sql" not in text and "northwind.sql" not in text and "Jake" not in text


def test_review_input_writes_posting_resume_and_letter(tmp_path):
    app = _app(tmp_path)
    out = review_input(app)
    text = (app / "review" / "input.md").read_text(encoding="utf-8")
    assert out["round"] == 2
    assert text.index("Build data pipelines") < text.index("Wrote SQL daily") < text.index("I wrote SQL.")


def test_review_round_needs_notes_and_is_asked_for_once(tmp_path):
    app = _app(tmp_path)
    assert review_round(app) is None  # no notes yet
    (app / "review").mkdir()
    (app / "review" / "notes.md").write_text("1. Cut 'small'.", encoding="utf-8")
    fb = review_round(app)
    assert fb["round"] == 3 and fb["build_on"] == 2 and fb["review"] is True and "letter" in fb["sections"]
    assert pending_round(app) == 3
    add_round(app, 3, 72, ats=67)
    assert review_round(app) is None


def test_review_round_ends_the_loop_and_becomes_best(tmp_path):
    app = _app(tmp_path)
    (app / "review").mkdir()
    (app / "review" / "notes.md").write_text("1. x", encoding="utf-8")
    review_round(app)
    add_round(app, 3, 69, ats=65.5)  # a little lower is still fine
    out = next_round(app, CFG)
    assert out["action"] == "stop" and out["best_round"] == 3 and "review round done" in out["reason"]
    assert not (app / "drafts" / "r4").exists()


def test_review_round_that_loses_ats_points_or_adds_a_critical_keeps_the_base(tmp_path):
    for i, kwargs in enumerate(({"ats": 60}, {"ats": 66, "criticals": [crit("summary")]})):
        (tmp_path / str(i)).mkdir()
        app = _app(tmp_path / str(i))
        (app / "review").mkdir()
        (app / "review" / "notes.md").write_text("1. x", encoding="utf-8")
        review_round(app)
        add_round(app, 3, 75, **kwargs)
        out = next_round(app, CFG)
        assert out["best_round"] == 2
        # A lost ATS point ends it; an added critical gets one round fixing only those lines.
        assert out["action"] == ("stop" if i == 0 else "repair")


def test_review_round_with_a_new_critical_gets_one_fix_round(tmp_path):
    app = _app(tmp_path)
    (app / "review").mkdir()
    (app / "review" / "notes.md").write_text("1. x", encoding="utf-8")
    review_round(app)
    add_round(app, 3, 75, ats=67, criticals=[crit("experience/northwind/northwind.sql")])
    out = next_round(app, CFG)
    assert out == {**out, "action": "repair", "next_round": 4, "best_round": 2}
    fb = json.loads((app / "drafts" / "r4" / "feedback.json").read_text())
    assert fb["review_fix"] and fb["build_on"] == 3 and fb["compare_to"] == 2 and fb["review_pass"] == 1
    assert fb["sections"] == ["experience/northwind"] and len(fb["criticals"]) == 1
    # Fixed: the round keeps the review's changes and ships.
    add_round(app, 4, 74, ats=67)
    out = next_round(app, CFG)
    assert out["action"] == "stop" and out["best_round"] == 4
    write_json(app / "app.json", {**json.loads((app / "app.json").read_text()), "best_round": 4})
    assert kept(app, 1) is True
    # Still broken: the round the review read ships, and no second fix round is asked for.
    (tmp_path / "b").mkdir()
    app = _app(tmp_path / "b")
    (app / "review").mkdir()
    (app / "review" / "notes.md").write_text("1. x", encoding="utf-8")
    review_round(app)
    add_round(app, 3, 75, ats=67, criticals=[crit("summary")])
    next_round(app, CFG)
    add_round(app, 4, 75, ats=67, criticals=[crit("summary")])
    out = next_round(app, CFG)
    assert out["action"] == "stop" and out["best_round"] == 2
    write_json(app / "app.json", {**json.loads((app / "app.json").read_text()), "best_round": 2})
    assert kept(app, 1) is False


def test_review_round_that_drops_a_posting_word_gets_one_fix_round(tmp_path):
    # A reworded line lost a backed term's match: put it back instead of losing every review fix.
    app = _app(tmp_path)
    (app / "review").mkdir()
    (app / "review" / "notes.md").write_text("1. x", encoding="utf-8")
    review_round(app)
    add_round(app, 3, 75, ats=60)
    g = app / "drafts" / "r3" / "grade.json"
    write_json(g, {**json.loads(g.read_text()), "unused_terms": ["dashboards"]})
    out = next_round(app, CFG)
    assert out == {**out, "action": "repair", "next_round": 4, "best_round": 2}
    assert "dropped dashboards" in out["reason"]
    fb = json.loads((app / "drafts" / "r4" / "feedback.json").read_text())
    assert fb["review_fix"] and fb["build_on"] == 3 and fb["compare_to"] == 2
    assert "dashboards" in fb["failed_items"][0] and "experience" in fb["sections"]
    # Put back: the review's changes ship.
    add_round(app, 4, 75, ats=66)
    assert next_round(app, CFG)["best_round"] == 4


def test_a_round_made_after_the_review_gets_another_pass(tmp_path):
    # Nexthop, Oct 27 2026: gap rounds after the review shipped a draft no reviewer read.
    app = _app(tmp_path)
    assert review_input(app)["pass"] == 1
    assert json.loads((app / "review" / "reviewed.json").read_text()) == {"round": 2}
    d = app / "review"
    (d / "notes.md").write_text("Verdict: ready\nGood to go.\n", encoding="utf-8")
    assert review_round(app) is None and review_input(app)["action"] == "stop"
    add_round(app, 3, 74, ats=70)  # a gap round on a later day
    (app / "drafts" / "r3" / "resume.yaml").write_text(yaml.safe_dump(RESUME, sort_keys=False), encoding="utf-8")
    write_json(app / "app.json", {**json.loads((app / "app.json").read_text()), "best_round": 3})
    assert changed_since_review(app) == 3
    out = review_input(app)
    assert out["action"] == "review" and out["pass"] == 2 and out["round"] == 3


def test_response_reads_only_entries_with_a_note(tmp_path):
    app = _app(tmp_path)
    write_json(app / "review" / "response.json",
               [{"note": "Cut 'small'", "action": "changed", "why": "cut"}, {"action": "left"}, "junk"])
    assert response(app) == [{"note": "Cut 'small'", "action": "changed", "why": "cut"}]
    assert json.loads((app / "review" / "response.json").read_text())[0]["note"] == "Cut 'small'"


# Jake, Oct 29 2026: "is this better?" passes after the first review, as in his own review chats.

NOTES_1 = """Verdict: not yet
A fair match; the main risk is the missing Azure experience.

## Resume
1. **Summary doesn't read as the role.** Replace 'Data analyst' with 'Data developer'.

## Cover letter
1. **No closing ask.** Add one.

## Questions only you can answer
1. How many sources did you validate?

## Interview questions
- Why did the role last four months?
"""


def _review_done(app, rnd, text=NOTES_1, n=1, ats=67):
    """Write pass n's notes, run its round and finish it (the round becomes best)."""
    d = app / "review" if n == 1 else app / "review" / f"pass{n}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "notes.md").write_text(text, encoding="utf-8")
    fb = review_round(app)
    assert fb["round"] == rnd and fb["review_pass"] == n
    add_round(app, rnd, 72, ats=ats)
    r = app / "drafts" / f"r{rnd}"
    (r / "resume.yaml").write_text(yaml.safe_dump(RESUME, sort_keys=False), encoding="utf-8")
    write_json(r / "cover-letter.json", LETTER)
    write_json(app / fb["response"], [{"note": "Summary opener", "action": "left", "why": "keeps the posting title"}])
    return next_round(app, CFG)


def test_parse_notes_reads_verdict_and_sections():
    out = parse_notes(NOTES_1)
    assert out["verdict"] == "not yet" and "Azure" in out["verdict_text"]
    assert out["sections"]["questions only you can answer"] == ["How many sources did you validate?"]
    assert parse_notes("**Verdict: Ready** to submit.\n")["verdict"] == "ready"
    assert parse_notes("1. no verdict")["verdict"] is None


def test_second_pass_sees_earlier_notes_and_responses(tmp_path):
    app = _app(tmp_path)
    assert review_input(app)["pass"] == 1
    assert _review_done(app, 3)["best_round"] == 3
    out = review_input(app)
    assert out["action"] == "review" and out["pass"] == 2 and out["follow_up"] and out["round"] == 3
    text = (app / "review" / "pass2" / "input.md").read_text(encoding="utf-8")
    assert "missing Azure experience" in text and "Left as is: Summary opener (keeps the posting title)" in text
    assert text.index("Your review of the last version") < text.index("# Resume (revised)")


def test_ready_verdict_asks_for_no_round_and_no_more_passes(tmp_path):
    app = _app(tmp_path)
    _review_done(app, 3)
    d = app / "review" / "pass2"
    d.mkdir(parents=True)
    (d / "notes.md").write_text("Verdict: ready\nYes, better.\n\n## What it fixed\n- The opener.\n", encoding="utf-8")
    assert review_round(app) is None
    assert review_input(app) == {"action": "stop", "reason": "review pass 2 said ready to submit"}


def test_passes_stop_at_the_limit_or_when_a_review_round_is_not_kept(tmp_path):
    app = _app(tmp_path)
    _review_done(app, 3)
    _review_done(app, 4, n=2)
    _review_done(app, 5, n=3)
    assert review_input(app)["action"] == "stop" and "3 review passes" in review_input(app)["reason"]
    (tmp_path / "b").mkdir()
    app = _app(tmp_path / "b")
    assert _review_done(app, 3, ats=50)["best_round"] == 2  # lost ATS points: not kept
    assert "not kept" in review_input(app)["reason"]


def test_review_input_carries_verified_company_facts(tmp_path):
    app = _app(tmp_path)
    write_json(app / "app.json", {"history": [], "best_round": 2, "company": "Remarcable Inc"})
    cfg = {"paths": {"companies": str(tmp_path / "companies")}}
    write_json(tmp_path / "companies" / "remarcable-inc" / "facts.json", [
        {"id": "f1", "fact": "Over 30,000 active users", "quote": "over 30,000 active users", "verified": True,
         "url": "https://remarcable.com"},
        {"id": "f2", "fact": "Founded in 1990", "quote": "x", "verified": False}])
    review_input(app, cfg=cfg)
    text = (app / "review" / "input.md").read_text(encoding="utf-8")
    assert "Over 30,000 active users (https://remarcable.com)" in text and "1990" not in text


def test_summary_gathers_questions_from_every_pass(tmp_path):
    app = _app(tmp_path)
    _review_done(app, 3)
    d = app / "review" / "pass2"
    d.mkdir(parents=True)
    (d / "notes.md").write_text("Verdict: not yet\nCloser.\n\n## New claims to verify\n- 9+ sources\n\n"
                                "## Interview questions\n- Why did the role last four months?\n- What was in the table?\n",
                                encoding="utf-8")
    s = summary(app)
    assert s["passes"] == 2 and s["verdict"] == "not yet" and s["verdict_text"] == "Closer."
    assert s["questions"] == ["How many sources did you validate?"] and s["claims"] == ["9+ sources"]
    assert s["interview"] == ["Why did the role last four months?", "What was in the table?"]


def test_check_md_top_shows_verdict_and_questions_without_boxes(tmp_path):
    from src.tailor.packet import _reviewer_lines
    from src.tailor.review import undecided

    app = _app(tmp_path)
    assert _reviewer_lines(app) == []
    _review_done(app, 3)
    text = "\n".join(_reviewer_lines(app))
    assert "Verdict after 1 pass: Not yet. A fair match" in text
    assert "- How many sources did you validate?" in text and "- Why did the role last four months?" in text
    assert undecided(text) == []
