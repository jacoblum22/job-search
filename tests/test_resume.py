"""Tests for src/resume.py: base validation and the .docx template."""

from __future__ import annotations

import copy

import pytest

from src.resume import build_document, iter_bullets, validate

CONTACT = {
    "name": "Pat Example",
    "location": "Vancouver, BC",
    "email": "pat@example.com",
    "phone": "",
    "linkedin": "linkedin.com/in/pat",
    "github": "github.com/pat",
}

BASE = {
    "id": "data-scientist",
    "summary": {"id": "summary", "text": "Data scientist."},
    "skills": [{"id": "skills.languages", "label": "Languages", "items": ["SQL", "Python"]}],
    "experience": [
        {
            "id": "acme",
            "title": "Data Scientist",
            "company": "Acme",
            "location": "Vancouver, BC",
            "dates": "Jun 2026 – Oct 2026",
            "bullets": [{"id": "acme.sql", "text": "Wrote SQL.", "sources": ["acme.sql-daily"]}],
        }
    ],
    "projects": [
        {
            "id": "proj",
            "name": "Project",
            "url": "https://github.com/pat/proj",
            "bullets": [{"id": "proj.one", "text": "Built it.", "sources": []}],
        }
    ],
    "education": [
        {
            "id": "ubc",
            "school": "University of British Columbia",
            "degree": "BSc",
            "dates": "2022 – 2026",
            "lines": [{"label": "Coursework", "text": "Databases"}],
        }
    ],
}


def _texts(doc) -> list[str]:
    return [p.text for p in doc.paragraphs]


def test_valid_base_has_no_problems():
    assert validate(BASE) == []


def test_iter_bullets_gives_paths():
    assert [p for p, _ in iter_bullets(BASE)] == ["experience/acme/acme.sql", "projects/proj/proj.one"]


@pytest.mark.parametrize(
    "mutate, expected",
    [
        (lambda b: b["projects"][0]["bullets"][0].update(id="acme.sql"), "duplicate id"),
        (lambda b: b["experience"][0]["bullets"][0].update(id="Bad Id"), "must be lowercase"),
        (lambda b: b["experience"][0].pop("dates"), "missing dates"),
        (lambda b: b["experience"][0]["bullets"][0].update(text=" "), "empty text"),
        (lambda b: b.update(order=["summary", "hobbies"]), "unknown section"),
        (lambda b: b["skills"][0].update(items=["Git (GitHub", "Bitbucket)"]), "unbalanced brackets"),
    ],
)
def test_validate_catches_problems(mutate, expected):
    base = copy.deepcopy(BASE)
    mutate(base)
    assert any(expected in p for p in validate(base))


def test_strict_mode_requires_sources():
    problems = validate(BASE, require_sources=True)
    assert problems == ["projects/proj/proj.one: no source passage ids"]


def test_bullets_are_real_u2022_text_not_word_list_style():
    doc = build_document(BASE, CONTACT)
    bullets = [p for p in doc.paragraphs if p.text.startswith("•")]
    assert [p.text for p in bullets] == ["•\tWrote SQL.", "•\tBuilt it."]
    assert all(p.style.name == "Normal" for p in bullets)
    assert not any("" in t for t in _texts(doc))


def test_contact_line_has_location_and_headings_are_caps():
    texts = _texts(build_document(BASE, CONTACT))
    assert texts[0] == "Pat Example"
    assert texts[1].startswith("Vancouver, BC | pat@example.com | linkedin.com/in/pat")
    for heading in ("SUMMARY", "SKILLS", "EXPERIENCE", "PROJECTS", "EDUCATION"):
        assert heading in texts
    assert "PROFILE" not in texts


def test_title_and_company_are_separate_runs_without_pipes():
    doc = build_document(BASE, CONTACT)
    line = next(p for p in doc.paragraphs if p.text.startswith("Data Scientist, Acme"))
    runs = [r.text for r in line.runs]
    assert "Data Scientist" in runs and "Acme" in runs
    assert "|" not in line.text
    assert line.text.endswith("\tJun 2026 – Oct 2026")


def test_order_picks_and_orders_sections():
    base = copy.deepcopy(BASE)
    base["order"] = ["education", "experience"]
    texts = _texts(build_document(base, CONTACT))
    assert texts.index("EDUCATION") < texts.index("EXPERIENCE")
    assert "SKILLS" not in texts


def test_check_sources_flags_unknown_and_non_claim_ids(tmp_path):
    import json

    from src.resume import check_sources

    index = tmp_path / "vault-index.json"
    index.write_text(json.dumps({"passages": [
        {"id": "acme.sql-daily", "use": "claim"},
        {"id": "acme.departure", "use": "interview-only"},
    ]}))
    base = copy.deepcopy(BASE)
    assert check_sources(base, index) == []
    base["projects"][0]["bullets"][0]["sources"] = ["acme.departure", "nope"]
    assert check_sources(base, index) == [
        "projects/proj/proj.one: passage 'acme.departure' is interview-only, not a resume claim",
        "projects/proj/proj.one: unknown passage id 'nope'",
    ]
