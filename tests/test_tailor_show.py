"""`show`, `vault`, `sent` and `revise-start`/`revise-done`: the first steps chats kept repeating."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tailor import parsecheck, revise, show
from src.tailor.appdir import load_app, write_json

RESUME = """name: Jake
summary:
  text: Data analyst who writes SQL daily.
skills:
- id: skills.data
  label: Data
  items: [SQL, Python]
experience:
- id: algaecal
  title: Associate Data Scientist
  company: AlgaeCal
  dates: Jun 2026 – Oct 2026
  bullets:
  - id: algaecal.sql
    text: Wrote SQL daily in BigQuery for 6+ third-party sources.
    sources: [algaecal.sql-daily]
"""


def _cfg(tmp_path: Path) -> dict:
    write_json(tmp_path / "vault-index.json", {"passages": [
        {"id": "algaecal.sql-daily", "file": "work/algaecal.md", "section": ["What I Did"], "use": "claim",
         "text": "Wrote SQL daily in BigQuery (CTEs, window functions)."},
        {"id": "firmament.docker", "file": "projects/firmament.md", "use": "claim",
         "text": "The repo has a Dockerfile for the backend."},
        {"id": "algaecal.feedback", "file": "work/algaecal.md", "use": "interview_only",
         "text": "Manager said my SQL was careful."},
    ]})
    return {"paths": {"applications": str(tmp_path / "apps"), "materials": str(tmp_path / "materials"),
                      "vault_index": str(tmp_path / "vault-index.json"), "bases": str(tmp_path / "bases")}}


def _app(tmp_path: Path, name: str = "2026-10-20 REW.ca - Data Engineer", status: str = "approved",
         job_id: int = 7) -> Path:
    app = tmp_path / "apps" / name
    (app / "drafts" / "r2").mkdir(parents=True)
    write_json(app / "app.json", {"job_id": job_id, "company": name.split(" ", 1)[1].split(" - ")[0],
                                  "title": "Data Engineer", "status": status, "best_round": 2, "history": []})
    (app / "drafts" / "r2" / "resume.yaml").write_text(RESUME, encoding="utf-8")
    write_json(app / "drafts" / "r2" / "cover-letter.json", {
        "greeting": "Dear Hiring Manager,", "sign_off": "Best regards,\nJake",
        "paragraphs": [{"text": "I am applying for the Data Engineer contract."},
                       {"text": "At AlgaeCal I checked data from Shopify and Braze."}]})
    (app / "posting.md").write_text("# Data Engineer\nBuild ETL pipelines.\n", encoding="utf-8")
    return app


def test_show_prints_shipped_text_with_ids_sources_and_passages(tmp_path):
    cfg = _cfg(tmp_path)
    app = _app(tmp_path)
    text = show.show(app, cfg, passages=True)
    assert "resume from: drafts/r2/resume.yaml" in text
    assert "- Wrote SQL daily in BigQuery for 6+ third-party sources.  [algaecal.sql; algaecal.sql-daily]" in text
    assert "> algaecal.sql-daily: Wrote SQL daily in BigQuery (CTEs, window functions)." in text
    assert "Data: SQL, Python" in text
    assert "At AlgaeCal I checked data from Shopify and Braze." in text
    assert "add --posting" in text and "Build ETL pipelines" not in text
    assert "Build ETL pipelines" in show.show(app, cfg, posting=True)


def test_show_prefers_final_then_humanize(tmp_path):
    app = _app(tmp_path)
    (app / "humanize").mkdir()
    (app / "humanize" / "resume.yaml").write_text(RESUME, encoding="utf-8")
    write_json(app / "humanize" / "round.json", {"round": 2})
    assert show.shipped(app)["resume"] == app / "humanize" / "resume.yaml"
    (app / "final").mkdir()
    (app / "final" / "resume.yaml").write_text(RESUME, encoding="utf-8")
    assert show.shipped(app)["resume"] == app / "final" / "resume.yaml"
    assert show.shipped(app)["letter"] == app / "drafts" / "r2" / "cover-letter.json"


def test_show_flags_a_leftover_pdf(tmp_path):
    cfg = _cfg(tmp_path)
    app = _app(tmp_path)
    (app / "final").mkdir()
    write_json(app / "final" / "parse.json", {"resume": {"pdf": "Jake Resume - REW.ca.pdf", "pages": 1, "ok": True}})
    for n in ("Jake Resume - REW.ca.pdf", "Jake Resume - REW.ca - Data Engineer.pdf"):
        (app / "final" / n).write_bytes(b"%PDF")
    text = show.show(app, cfg)
    assert "Jake Resume - REW.ca.pdf (1 page(s), parse ok)" in text
    assert "Jake Resume - REW.ca - Data Engineer.pdf (not from the last render: delete it?)" in text


def test_vault_finds_word_starts_and_can_skip_interview_only(tmp_path):
    cfg = _cfg(tmp_path)
    assert [p["id"] for p in show.vault(cfg, ["docker"])] == ["firmament.docker"]
    assert {p["id"] for p in show.vault(cfg, ["SQL"])} == {"algaecal.sql-daily", "algaecal.feedback"}
    assert [p["id"] for p in show.vault(cfg, ["sql"], claims_only=True)] == ["algaecal.sql-daily"]
    assert show.vault(cfg, ["ocker"]) == []  # word starts only


def test_vault_finds_what_the_grade_counts_as_the_same_wording(tmp_path):
    # Pattison, Oct 30 2026: the grade asked for "data analytics" on a "data analysis" passage and
    # this search said the vault had none.
    cfg = _cfg(tmp_path)
    assert [p["id"] for p in show.vault(cfg, ["window-function"])] == ["algaecal.sql-daily"]
    write_json(tmp_path / "vault-index.json", {"passages": [
        {"id": "lab.analysis", "file": "work/lab.md", "use": "claim", "text": "Did the data analysis in R."}]})
    assert [p["id"] for p in show.vault(cfg, ["data analytics"])] == ["lab.analysis"]


def test_sent_searches_shipped_lines_and_filters_by_status_or_outcome(tmp_path):
    cfg = _cfg(tmp_path)
    _app(tmp_path)
    other = _app(tmp_path, "2026-10-21 Remarcable - Integration Engineer", status="ready_for_review", job_id=8)
    hits = show.sent(cfg, r"\d\+ third-party")
    assert [h["folder"] for h in hits] == ["2026-10-20 REW.ca - Data Engineer", other.name]
    assert hits[0]["hits"] == [{"line": "resume algaecal/algaecal.sql",
                                "text": "Wrote SQL daily in BigQuery for 6+ third-party sources."}]
    assert [h["folder"] for h in show.sent(cfg, "Braze", statuses=["approved"])] == [
        "2026-10-20 REW.ca - Data Engineer"]
    app = load_app(other)
    write_json(other / "app.json", {**app, "outcome": "applied", "status": "applied"})
    assert [h["folder"] for h in show.sent(cfg, "Braze", statuses=["applied"])] == [other.name]


def test_revise_start_saves_final_and_sets_up_humanize(tmp_path):
    app = _app(tmp_path)
    (app / "final").mkdir()
    (app / "final" / "a.pdf").write_bytes(b"old")
    out = revise.revise_start(app, today="2026-10-27")
    assert (app / "previous-version-2026-10-27" / "a.pdf").read_bytes() == b"old"
    assert (app / "humanize" / "resume.yaml").read_text(encoding="utf-8") == RESUME
    assert json.loads((app / "humanize" / "round.json").read_text())["round"] == 2
    assert sorted(out["copied_from_round"]) == ["cover-letter.json", "resume.yaml"]
    # A second revision the same day keeps the first save.
    revise.revise_start(app, today="2026-10-27")
    assert (app / "previous-version-2026-10-27-2" / "a.pdf").exists()
    assert load_app(app)["history"][-1]["step"] == "revise-start"


def test_revise_start_replaces_a_stale_humanize_copy(tmp_path):
    app = _app(tmp_path)
    (app / "humanize").mkdir()
    (app / "humanize" / "resume.yaml").write_text("name: old\n", encoding="utf-8")
    write_json(app / "humanize" / "cover-letter.json", {"paragraphs": ["old"]})
    write_json(app / "humanize" / "round.json", {"round": 1})
    revise.revise_start(app, today="2026-10-27")
    assert (app / "humanize" / "resume.yaml").read_text(encoding="utf-8") == RESUME
    assert "Data Engineer contract" in (app / "humanize" / "cover-letter.json").read_text(encoding="utf-8")


def test_revise_start_warns_when_final_letter_was_edited_by_hand(tmp_path):
    app = _app(tmp_path)
    revise.revise_start(app, today="2026-10-27")
    (app / "final").mkdir()
    write_json(app / "final" / "cover-letter.json", {"paragraphs": ["edited in final"]})
    out = revise.revise_start(app, today="2026-10-28")
    assert any("final/cover-letter.json differs" in n for n in out["notes"])


def test_revise_done_keeps_status_and_logs_the_note(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    app = _app(tmp_path, status="applied")
    revise.revise_start(app, today="2026-10-27")

    def fake_render(app_dir, cfg):
        from src.tailor.appdir import log

        log(app_dir, "render", "rendered; parse ok; dropped 0 bullet(s)")
        return {"ok": True, "dropped": [], "resume": {"pages": 1, "pdf": "r.pdf", "checks": []},
                "letter": {"pages": 1, "pdf": "l.pdf", "checks": []}}

    monkeypatch.setattr("src.tailor.render.run_render", fake_render)
    out = revise.revise_done(app, cfg, "summary rewritten from outside feedback")
    assert out["pages"] == {"resume": 1, "letter": 1} and out["parse_ok"]
    assert isinstance(out["phrase_hits"], list)
    a = load_app(app)
    assert a["status"] == "applied"
    assert a["history"][-1] == {**a["history"][-1], "step": "hand-edit",
                                "note": "summary rewritten from outside feedback"}


@pytest.mark.parametrize("no_rapidfuzz", [False, True])
def test_round_trip_with_and_without_rapidfuzz(monkeypatch, no_rapidfuzz):
    if no_rapidfuzz:
        monkeypatch.setattr(parsecheck, "fuzz", None)
    text = "Wrote SQL daily in BigQuery for six third-party sources\nBuilt an ETL jop in Apps Script\nEnd"
    items = [("a", "Wrote SQL daily in BigQuery for six third-party sources"),
             ("b", "Built an ETL job in Apps Script")]  # "jop": one letter off, still found
    assert parsecheck._round_trip(items, text) == []
    assert parsecheck._round_trip([("b", items[1][1]), ("a", items[0][1])], text)[0]["reason"] == "out of order"
    assert parsecheck._round_trip([("c", "Led a team of twelve engineers")], text)[0]["reason"] == "missing"
