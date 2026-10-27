"""Tests for src/tailor/outside.py: the outside review and the round that acts on it."""

from __future__ import annotations

import json

import yaml

from src.tailor.appdir import write_json
from src.tailor.loop import next_round, pending_round
from src.tailor.outside import resume_text, response, review_input, review_round

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
        assert next_round(app, CFG)["best_round"] == 2


def test_response_reads_only_entries_with_a_note(tmp_path):
    app = _app(tmp_path)
    write_json(app / "review" / "response.json",
               [{"note": "Cut 'small'", "action": "changed", "why": "cut"}, {"action": "left"}, "junk"])
    assert response(app) == [{"note": "Cut 'small'", "action": "changed", "why": "cut"}]
    assert json.loads((app / "review" / "response.json").read_text())[0]["note"] == "Cut 'small'"
