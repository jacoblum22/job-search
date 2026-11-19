"""The AI fit verdict for reviewed applications: input, validation, caching."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.tailor import TailorError, fitverdict
from src.tailor.appdir import write_json

GOOD = {"score_check": "too high", "stretch": "some stretch", "outlook": "mixed",
        "text": "Worth applying, but treat it as a stretch: the posting wants three years of BI work and "
                "the score only saw the SQL and Power BI words."}


def _app(tmp_path: Path, status: str = "ready_for_review") -> Path:
    app = tmp_path / "2026-11-19 Acme - Data Analyst"
    app.mkdir()
    write_json(app / "app.json", {"job_id": 7, "company": "Acme", "title": "Data Analyst", "tier": "A",
                                  "score": 71, "status": status})
    (app / "posting.md").write_text("Data Analyst at Acme. 3+ years of SQL and Power BI.", encoding="utf-8")
    (app / "check.md").write_text("# Check\n\n- [ ] Reviewed  Fit summary\n", encoding="utf-8")
    (app / "fit-notes.md").write_text("# Fit notes\n", encoding="utf-8")
    return app


def _cfg(tmp_path: Path) -> dict:
    return {"paths": {"db": str(tmp_path / "missing.db"), "applications": str(tmp_path)}}


def _write(app: Path, data: dict) -> None:
    (app / "fit-verdict").mkdir(exist_ok=True)
    (app / "fit-verdict" / "verdict.json").write_text(json.dumps(data), encoding="utf-8")


def test_input_has_the_posting_the_packet_and_the_score(tmp_path):
    app = _app(tmp_path)
    out = fitverdict.build_input(app, _cfg(tmp_path))
    text = Path(out["input"]).read_text(encoding="utf-8")
    assert "3+ years of SQL" in text and "Fit summary" in text and "Score 71" in text
    assert out["output"].endswith("verdict.json")


def test_save_keeps_a_valid_verdict_and_it_stays_current(tmp_path):
    app = _app(tmp_path)
    assert fitverdict.needs_verdict(app)
    _write(app, GOOD)
    fitverdict.save(app)
    saved = fitverdict.load(app)
    assert saved["outlook"] == "mixed" and saved["stretch"] == "some stretch"
    assert not fitverdict.needs_verdict(app)


def test_ticking_a_box_or_a_new_score_does_not_make_it_stale_but_a_new_packet_does(tmp_path):
    app = _app(tmp_path)
    _write(app, GOOD)
    fitverdict.save(app)
    (app / "check.md").write_text("# Check\n\n- [x] Reviewed  Fit summary\n", encoding="utf-8")
    write_json(app / "app.json", {"job_id": 7, "company": "Acme", "title": "Data Analyst", "tier": "B",
                                  "score": 55, "status": "ready_for_review"})
    assert not fitverdict.needs_verdict(app)
    (app / "check.md").write_text("# Check\n\n- [ ] Reviewed  A different packet\n", encoding="utf-8")
    assert fitverdict.needs_verdict(app)


@pytest.mark.parametrize("bad", [
    {**GOOD, "outlook": "great"}, {**GOOD, "stretch": "huge"}, {**GOOD, "score_check": "wrong"},
    {**GOOD, "text": "Too short."}, {**GOOD, "text": "x " * 600},
])
def test_save_refuses_a_bad_verdict(tmp_path, bad):
    app = _app(tmp_path)
    _write(app, bad)
    with pytest.raises(TailorError):
        fitverdict.save(app)
    assert fitverdict.load(app) is None


def test_only_reviewed_applications_need_one(tmp_path):
    assert not fitverdict.needs_verdict(_app(tmp_path, "applied"))
    shortlisted = tmp_path / "2026-11-19 Beta - Analyst"
    shortlisted.mkdir()
    write_json(shortlisted / "app.json", {"job_id": 8, "status": "shortlisted"})
    assert not fitverdict.needs_verdict(shortlisted)


def test_pending_lists_newest_first_and_honours_the_limit(tmp_path):
    a = _app(tmp_path)
    b = tmp_path / "2026-11-20 Beta - Analyst"
    b.mkdir()
    write_json(b / "app.json", {"job_id": 8, "status": "needs_fixes"})
    (b / "check.md").write_text("# Check\n", encoding="utf-8")
    assert fitverdict.pending([a, b]) == [str(b), str(a)]
    assert fitverdict.pending([a, b], limit=1) == [str(b)]
