from src.vault import assign_ids, build_index

NOTE = """# Associate Data Scientist — Acme

**Role**: Associate Data Scientist
**Duration**: June 2026 – October 2026

## What I Did

- **Daily SQL**: Wrote SQL in BigQuery every day. ^sql-daily
- **Churn project**: Predicting churn.
  - Data: 1M+ rows.

```
scripts/
  not-a-passage.py
```

| Skill | Evidence |
|-------|----------|
| **SQL** | Daily BigQuery work |

## Stories

### Story 1: Proposing the Hazard Model

- **Situation**: Churn had no clear event.
- **Result**: The team came back to the hazard model.

## Departure (for interviews, not the resume)

- Employment ended without cause.

## Related Notes

- [[skills-map]] — Skills cross-reference
"""


def _vault(tmp_path, text=NOTE, name="acme.md", newline="\n"):
    (tmp_path / "work").mkdir(exist_ok=True)
    path = tmp_path / "work" / name
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return path


def test_assign_then_index(tmp_path):
    path = _vault(tmp_path)
    assign_ids(path)
    passages, problems = build_index(tmp_path)
    assert problems == []
    ids = {p.id: p for p in passages}
    assert set(ids) == {
        "acme.role", "acme.duration", "acme.sql-daily", "acme.churn-project", "acme.data-1m-rows",
        "acme.sql", "acme.proposing-hazard-situation", "acme.proposing-hazard-result",
        "acme.employment-ended-without",
    }
    assert ids["acme.data-1m-rows"].parent == "acme.churn-project"
    assert ids["acme.data-1m-rows"].numbers == ["1M+"]
    assert ids["acme.sql"].kind == "table" and ids["acme.sql"].text == "Skill: SQL; Evidence: Daily BigQuery work"
    assert ids["acme.employment-ended-without"].use == "interview-only"
    assert ids["acme.sql-daily"].text == "Daily SQL: Wrote SQL in BigQuery every day."
    assert path.read_text().startswith("<!-- id: acme -->\n")


def test_ids_survive_text_edits(tmp_path):
    path = _vault(tmp_path)
    assign_ids(path)
    path.write_text(path.read_text().replace("Wrote SQL in BigQuery every day.", "Wrote BigQuery SQL daily."))
    assert assign_ids(path) == []
    passages, _ = build_index(tmp_path)
    assert next(p for p in passages if p.id == "acme.sql-daily").text == "Daily SQL: Wrote BigQuery SQL daily."


def test_missing_and_duplicate_ids_are_problems(tmp_path):
    _vault(tmp_path, "<!-- id: acme -->\n- First. ^same\n- Second. ^same\n- Third.\n")
    _, problems = build_index(tmp_path)
    assert any("no id" in p for p in problems)
    assert any("duplicate id acme.same" in p for p in problems)


def test_assign_keeps_crlf_line_endings(tmp_path):
    path = _vault(tmp_path, newline="\r\n")
    assign_ids(path)
    raw = path.read_bytes()
    assert b"\r\n" in raw and b"\n" not in raw.replace(b"\r\n", b"")


def test_guidance_and_course_headings(tmp_path):
    _vault(tmp_path, "<!-- id: course -->\n### CPSC 330 — Applied Machine Learning (84%, A-) ^cpsc-330\n\n"
                     "- scikit-learn ^cpsc-330-sklearn\n- First aid lapsed: do not claim it. ^first-aid\n", name="coursework.md")
    passages, problems = build_index(tmp_path)
    assert problems == []
    ids = {p.id: p for p in passages}
    assert ids["course.cpsc-330"].kind == "heading"
    assert ids["course.cpsc-330"].text == "CPSC 330 — Applied Machine Learning (84%, A-)"
    assert ids["course.first-aid"].use == "guidance"
