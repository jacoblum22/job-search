"""Plain-language wording for the review checklist."""

from __future__ import annotations

from src.tailor import explain, rejects

RESUME = {
    "summary": {"text": "Data analyst who writes SQL."},
    "skills": [{"id": "skills.analytics", "label": "Analytics & BI", "items": ["SQL", "R"]}],
    "experience": [{"id": "algaecal", "company": "AlgaeCal", "bullets": [
        {"id": "algaecal.sql", "text": "Wrote SQL daily."}, {"id": "algaecal.dash", "text": "Fixed dashboards."}]}],
    "projects": [{"id": "wids", "name": "WiDS Datathon", "bullets": [{"id": "wids.churn", "text": "Topped it."}]}],
}
INDEX = {
    "algaecal.sql-daily": {"file": "work/algaecal.md", "section": ["What I Did"], "text": "Daily SQL.",
                           "file_title": "Associate Data Scientist — AlgaeCal"},
    "course.db": {"file": "coursework.md", "section": [], "text": "Databases."},
}


def test_path_labels_name_the_resume_line():
    assert explain.path_label("summary", RESUME) == "Summary"
    assert explain.path_label("skills/skills.analytics", RESUME) == "Skills list (Analytics & BI)"
    assert explain.path_label("experience/algaecal/algaecal.dash", RESUME) == "AlgaeCal, bullet 2"
    assert explain.path_label("projects/wids/wids.churn", RESUME) == "WiDS Datathon project, bullet 1"
    assert explain.path_label("paragraphs[0]", RESUME) == "Cover letter, paragraph 1"
    assert explain.line_text("experience/algaecal/algaecal.sql", RESUME) == "Wrote SQL daily."


def test_issues_read_as_sentences_old_and_new():
    new = {"code": "skill_only_in_list", "message": "'R' appears only in the skills list", "path": "skills",
           "data": {"term": "R"}}
    old = {k: v for k, v in new.items() if k != "data"}  # check.json written before "data" existed
    for it in (new, old):
        head, details = explain.issue(it, RESUME)
        assert head == "Skills list: R is in your skills list, but no bullet shows you using it."
        assert details[0].startswith("Why it matters: A skill with no bullet")
    head, details = explain.issue({"code": "bullet_long", "message": "230 characters (limit 200)",
                                   "path": "experience/algaecal/algaecal.sql"}, RESUME)
    assert head == "AlgaeCal, bullet 1: This bullet is long (over 200 characters)."
    assert details == ['The line: "Wrote SQL daily."', "Why it matters: Long bullets wrap to three lines and get skimmed.",
                       "Checker's note: 230 characters (limit 200)"]
    head, _ = explain.issue({"code": "brand_new_code", "message": "something odd", "path": "summary"}, RESUME)
    assert head == "Summary: something odd"


def test_citation_gap_is_a_note_with_where_the_passages_came_from():
    it = {"code": "jev_citation_gap", "path": "summary",
          "message": "Jev doubted this line with its cited passages (p=0.29) but agreed once "
                     "algaecal.sql-daily, course.db were cited too (p=0.85); those were added to its sources"}
    assert explain.is_note(it)
    text = explain.note(it, RESUME, INDEX)
    assert "2 more of your vault passages (Associate Data Scientist — AlgaeCal (1), Coursework (1))" in text
    assert "p=" not in text


def test_jev_items_say_what_was_judged():
    reqs = {"r2": {"text": "Strong SQL", "quote": "Strong SQL skills with healthcare data"}}
    head, details = explain.jev_item({"id": "must.r2", "question": "Is Strong SQL backed...?", "passed": False,
                                      "confidence": 0.89}, reqs, RESUME, "Analyst", "VCH")
    assert head.startswith('Must-have not clearly shown: "Strong SQL".') and "(89% sure)" in head
    assert details[0] == 'The posting says: "Strong SQL skills with healthcare data"'
    head, details = explain.jev_item({"id": "letter.opener", "passed": False, "confidence": 0.6,
                                      "question": 'Could this opening sentence start ...: "I love data."?'},
                                     reqs, RESUME, "Analyst", "VCH")
    assert "opening sentence may be generic" in head and details[0] == 'The sentence: "I love data."'
    reqs = {"r3": {"text": "Bachelor's degree in Statistics or a related field"}}
    head, details = explain.jev_item({"id": "must.r3", "question": "Does the resume's education meet ...?",
                                      "passed": False, "confidence": 0.6, "fit_gap": ["degree"]},
                                     reqs, RESUME, "Analyst", "VCH")
    assert "degree" in head and "named tool" not in head
    assert not any("Not in your vault" in d for d in details)


def test_drops_show_the_passage_and_old_undo_lines_still_work():
    head, details = explain.drop({"term": "SQL", "passage": "algaecal.sql-daily", "reason": "Not a skill"}, INDEX, True)
    assert head == "SQL: not counted from Associate Data Scientist — AlgaeCal (What I Did)."
    assert details == ['The passage: "Daily SQL."', "Why: Not a skill.", "First set aside on this job; later jobs skip it too."]
    old = rejects._OLD_UNDO.match("- [x] Undo  Excel (job-search.outputs): an export")
    assert (old["old_term"], old["old_passage"]) == ("Excel", "job-search.outputs")
