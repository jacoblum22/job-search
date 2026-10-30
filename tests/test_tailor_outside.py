"""Tests for src/tailor/outside.py: the outside review and the round that acts on it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.tailor.appdir import write_json
from src.tailor.loop import next_round, pending_round
from src.tailor.outside import (
    blocker,
    changed_since_review,
    kept,
    parse_notes,
    response,
    resume_text,
    review_input,
    review_round,
    shipped_text,
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


@pytest.fixture(autouse=True)
def fake_render(monkeypatch):
    """review_input renders the round's PDFs; Word/LibreOffice isn't here, so write stand-ins."""
    calls = []

    def render(app_dir, cfg, rnd, out):
        calls.append(rnd)
        resume, letter = out / "Jake Resume - Northwind.pdf", out / "Jake Cover Letter - Northwind.pdf"
        resume.write_text(f"resume r{rnd}", encoding="utf-8")
        letter.write_text(f"letter r{rnd}", encoding="utf-8")
        return {"resume": str(resume), "letter": str(letter)}

    monkeypatch.setattr("src.tailor.render.render_round", render)
    return calls


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


def test_review_input_sends_jakes_message_the_posting_and_the_two_pdfs(tmp_path, fake_render):
    # Jake, Oct 29 2026: the reviewer gets exactly what he sends in his own review chats.
    app = _app(tmp_path)
    (app / "posting.md").write_text("# Data Analyst\n\n- Company: Northwind\n- URL: https://x.test/1\n"
                                    "- Posted: 2026-10-28\n\nBuild data pipelines.", encoding="utf-8")
    out = review_input(app)
    assert out["round"] == 2 and out["pass"] == 1 and fake_render == [2]
    text = (app / "review" / "message.md").read_text(encoding="utf-8")
    assert text.startswith("Could you use the job-application-review skill on these? Here's the posting.\n\n# Data Analyst")
    assert "Company: Northwind" in text and "Build data pipelines." in text
    assert "https://x.test/1" not in text and "Posted" not in text
    assert "Wrote SQL daily" not in text  # the resume and letter go as PDFs, not text
    assert [p.split("/")[-1].split("\\")[-1] for p in out["attachments"]] == [
        "Jake Resume - Northwind.pdf", "Jake Cover Letter - Northwind.pdf"]
    assert "conversation" not in out and out["notes"].endswith("notes.md")


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


def test_review_round_is_kept_whatever_its_ats_but_a_critical_gets_a_fix_round(tmp_path):
    # Jake, Oct 29 2026: in his chats the revision always goes back to the reviewer.
    for i, kwargs in enumerate(({"ats": 50}, {"ats": 66, "criticals": [crit("summary")]})):
        (tmp_path / str(i)).mkdir()
        app = _app(tmp_path / str(i))
        (app / "review").mkdir()
        (app / "review" / "notes.md").write_text("1. x", encoding="utf-8")
        review_round(app)
        add_round(app, 3, 60, **kwargs)
        out = next_round(app, CFG)
        if i == 0:
            assert out["action"] == "stop" and out["best_round"] == 3
        else:  # an added critical gets one round fixing only those lines
            assert out["action"] == "repair" and out["best_round"] == 2


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


def _review_done(app, rnd, text=NOTES_1, n=1, ats=67, edit=True):
    """Write pass n's notes, run its round and finish it (the round becomes best). The round
    changes the summary unless `edit` is False (a round that applied none of the notes)."""
    d = app / "review" if n == 1 else app / "review" / f"pass{n}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "notes.md").write_text(text, encoding="utf-8")
    fb = review_round(app)
    assert fb["round"] == rnd and fb["review_pass"] == n
    add_round(app, rnd, 72, ats=ats)
    r = app / "drafts" / f"r{rnd}"
    data = {**RESUME, "summary": {**RESUME["summary"], "text": f"Data analyst, edit {rnd}."}} if edit else RESUME
    (r / "resume.yaml").write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    write_json(r / "cover-letter.json", LETTER)
    write_json(app / fb["response"], [{"note": "Summary opener", "action": "left", "why": "keeps the posting title"}])
    return next_round(app, CFG)


def test_parse_notes_reads_verdict_and_sections():
    out = parse_notes(NOTES_1)
    assert out["verdict"] == "not yet" and "Azure" in out["verdict_text"]
    assert out["sections"]["questions only you can answer"] == ["How many sources did you validate?"]
    assert parse_notes("**Verdict: Ready** to submit.\n")["verdict"] == "ready"
    assert parse_notes("")["verdict"] is None


def test_parse_notes_reads_the_skills_own_verdicts():
    # Replies from Jake's own chats (Impact Brands, Nexthop, Oct 26-28 2026).
    assert parse_notes("Yes, it's better, and it's ready to submit once you do the checks below.\n\n"
                       "Verdict: Submit.\n")["verdict"] == "ready"
    v = parse_notes("Yes, this is better.\n\nVerdict: Submit once you've fixed the singular/plural mismatch.\n")
    assert v["verdict"] == "not yet" and v["verdict_text"].startswith("Submit once")
    assert parse_notes("Yes, this is better.\n\n**Verdict**\n\nSubmit after items 1 to 3.\n")["verdict"] == "not yet"
    first = parse_notes("**Verdict:** This is a reasonable match. Apply, but name the gap.\n\n"
                        "## Cover letter\n\n1. **It never names the role or the company.** Open with it.\n\n"
                        "**Questions only you can answer**\n\n1. How many sources?\n")
    assert first["verdict"] == "not yet"
    assert first["sections"]["cover letter"][0].startswith("**It never names the role")
    assert first["sections"]["questions only you can answer"] == ["How many sources?"]


def test_every_pass_is_a_fresh_reviewer_with_the_same_opening_and_the_new_text(tmp_path):
    # Oct 30 2026 bake-off: a brand-new reviewer each round beat one reviewer chat with "Is this better?".
    app = _app(tmp_path)
    first = review_input(app)
    assert first["pass"] == 1 and "follow_up" not in first
    opening = (app / "review" / "message.md").read_text(encoding="utf-8")
    assert opening.startswith("Could you use the job-application-review skill")
    assert _review_done(app, 3)["best_round"] == 3
    out = review_input(app)
    assert out["action"] == "review" and out["pass"] == 2 and out["round"] == 3
    assert (app / "review" / "pass2" / "message.md").read_text(encoding="utf-8") == opening
    # The PDFs go to the reviewer from a folder outside the packet, so it can't read earlier notes.
    assert all(Path(p).exists() and "pass2" in p and str(app) not in p for p in out["attachments"])
    assert "conversation" not in out
    assert not (app / "review" / "pass2" / "conversation.md").exists()


def test_ready_verdict_asks_for_no_round_and_no_more_passes(tmp_path):
    app = _app(tmp_path)
    _review_done(app, 3)
    d = app / "review" / "pass2"
    d.mkdir(parents=True)
    (d / "notes.md").write_text("Verdict: ready\nYes, better.\n\n## What it fixed\n- The opener.\n", encoding="utf-8")
    assert review_round(app) is None
    assert review_input(app) == {"action": "stop", "reason": "review pass 2 said ready to submit"}


def test_a_round_that_changed_nothing_ends_the_passes(tmp_path):
    """Jake, Oct 29 2026: done when the reviewer says ready or nothing left is worth applying. Evismart,
    Infoblox and Jobgether sent the same text six times because the round that judged every note not
    worth applying still earned an "is this better?"."""
    app = _app(tmp_path)
    assert review_input(app)["pass"] == 1
    _review_done(app, 3, edit=False)
    out = review_input(app)
    assert out["action"] == "stop" and "changed nothing" in out["reason"]
    (tmp_path / "b").mkdir()
    app = _app(tmp_path / "b")
    _review_done(app, 3)
    assert review_input(app)["pass"] == 2  # a round that changed the text still gets reviewed


def test_passes_stop_at_the_limit_and_a_round_that_lost_ats_still_gets_reviewed(tmp_path):
    app = _app(tmp_path)
    _review_done(app, 3)
    _review_done(app, 4, n=2)
    _review_done(app, 5, n=3)
    assert review_input(app)["pass"] == 4  # the default cap is 6: passes stop on "ready"
    cap = {"loop": {"review_passes": 3}}
    assert review_input(app, cfg=cap)["action"] == "stop" and "3 review passes" in review_input(app, cfg=cap)["reason"]
    (tmp_path / "b").mkdir()
    app = _app(tmp_path / "b")
    assert _review_done(app, 3, ats=50)["best_round"] == 3  # lost ATS points: kept all the same
    assert review_input(app)["pass"] == 2


def test_summary_keeps_last_pass_items_and_earlier_ones_still_about_the_text(tmp_path):
    # Jake, Oct 29 2026: Jobgether's check.md listed questions about lines cut passes ago.
    app = _app(tmp_path)
    _review_done(app, 3, text=NOTES_1 + "- Is 'wrote SQL daily' every day?\n- Why 'built 12 dashboards'?\n")
    d = app / "review" / "pass2"
    d.mkdir(parents=True)
    (d / "notes.md").write_text("Verdict: not yet\nCloser.\n\n## New claims to verify\n- 9+ sources\n"
                                "- \"I wrote SQL\" (letter): what kind?\n- \"Led the... migration\": whose?\n\n"
                                "## Interview questions\n- What was in the table?\n",
                                encoding="utf-8")
    s = summary(app)
    assert s["passes"] == 2 and s["verdict"] == "not yet" and s["verdict_text"] == "Closer."
    assert s["questions"] == []  # pass 1's question quotes nothing: only the last pass's unquoted items stay
    assert s["interview"] == ["What was in the table?", "Is 'wrote SQL daily' every day?", "Why 'built 12 dashboards'?"]
    shipped = shipped_text(RESUME, LETTER)
    s = summary(app, shipped)
    assert s["claims"] == ["9+ sources", '"I wrote SQL" (letter): what kind?']  # the migration line is gone
    assert s["interview"] == ["What was in the table?", "Is 'wrote SQL daily' every day?"]


def test_ready_after_changes_counts_as_not_yet(tmp_path):
    # Jake, Oct 29 2026: only "ready to submit now" stops; "ready after these changes" is not yet.
    assert parse_notes("Verdict: ready after these changes\nTwo small fixes.\n")["verdict"] == "not yet"
    assert parse_notes("**Verdict: Ready after** the fixes below.\n")["verdict"] == "not yet"
    app = _app(tmp_path)
    _review_done(app, 3)
    d = app / "review" / "pass2"
    d.mkdir(parents=True)
    (d / "notes.md").write_text("Verdict: ready after these changes\nOne fix.\n\n## Still open\n1. **x.** y\n",
                                encoding="utf-8")
    assert review_round(app)["review_pass"] == 2


def test_check_md_top_shows_verdict_and_questions_without_boxes(tmp_path):
    from src.tailor.packet import _reviewer_lines
    from src.tailor.review import undecided

    app = _app(tmp_path)
    assert _reviewer_lines(app, None) == []
    _review_done(app, 3)
    text = "\n".join(_reviewer_lines(app, app / "drafts" / "r3"))
    assert "Verdict after 1 pass: Not yet. A fair match" in text
    assert "- How many sources did you validate?" in text and "- Why did the role last four months?" in text
    assert undecided(text) == []


def test_a_job_jake_cannot_do_ends_the_reviews(tmp_path):
    # Jake, Oct 29 2026: CorGTA required Spanish; five review passes followed before anyone said so.
    from src.tailor.packet import _reviewer_lines

    app = _app(tmp_path)
    (app / "posting.md").write_text("# Spanish Data Analyst\n\n- Spanish-speaking candidates mandatory\n", encoding="utf-8")
    assert blocker(app)
    out = review_input(app)
    assert out["action"] == "stop" and "Spanish-speaking candidates mandatory" in out["reason"]
    assert "Can't apply" in "\n".join(_reviewer_lines(app, None))
    (app / "posting.md").write_text("# Analyst\n\nFrench is an asset.\n", encoding="utf-8")
    assert blocker(app) is None and review_input(app)["pass"] == 1
    (app / "review" / "notes.md").write_text("Verdict: blocked\nRequires a PhD.\n", encoding="utf-8")
    assert parse_notes("Verdict: blocked\nRequires a PhD.\n")["verdict"] == "blocked"
    assert review_round(app) is None and "can't take this job" in review_input(app)["reason"]
