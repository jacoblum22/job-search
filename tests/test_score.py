from pathlib import Path

import yaml

from src.db import Job, connect, upsert_job
from src.score import rescore_all, score_job

CFG = yaml.safe_load(
    (Path(__file__).resolve().parent.parent / "config" / "settings.yaml").read_text(encoding="utf-8")
)["score"]


def _score(title, description="", location_category="vancouver", years=None):
    return score_job(
        title=title,
        description=description,
        location_category=location_category,
        years_experience=years,
        cfg=CFG,
    )


def test_strong_fit_ranks_a():
    r = _score(
        "Junior Data Analyst",
        "SQL and BigQuery daily, build Looker dashboards with stakeholders. " * 10,
        years=1,
    )
    assert r.tier == "A"
    assert any("data analyst title" in x for x in r.reasons)
    assert any("entry-level title" in x for x in r.reasons)


def test_three_to_four_years_is_a_penalty_not_a_skip():
    base = _score("Data Scientist", "python sql " * 50, years=None)
    three = _score("Data Scientist", "python sql " * 50, years=3)
    four = _score("Data Scientist", "python sql " * 50, years=4)
    assert three.tier != "skip" and four.tier != "skip"
    assert base.score > three.score > four.score


def test_five_years_penalised_and_over_five_skipped():
    assert _score("Data Scientist", years=5).tier != "skip"
    assert _score("Data Scientist", years=6).tier == "skip"


def test_wrong_field_and_senior_titles_skipped():
    assert _score("Business Development Representative").tier == "skip"
    assert _score("Senior Data Scientist").tier == "skip"
    assert _score("Data Analyst Co-op").tier == "skip"


def test_level_two_penalised():
    assert _score("Data Analyst II").score < _score("Data Analyst").score


def test_us_residence_required_skipped_but_remote_us_kept():
    ok = _score("Data Analyst", "Remote role open across North America.", "remote")
    assert ok.tier != "skip"
    us_only = _score("Data Analyst", "Candidates must reside in the United States.", "remote")
    assert us_only.tier == "skip"


def test_short_tokens_do_not_match_inside_words():
    # "i" (entry-level) must not match "is"; "hr" (skip) must not match "hrs"
    r = _score("Data Analyst - this is 40 hrs a week")
    assert r.tier != "skip"
    assert not any("entry-level title" in x for x in r.reasons)


def test_plural_skills_match():
    r = _score("Data Analyst", "You will maintain dashboards.")
    assert any("dashboard" in x for x in r.reasons)


def test_rescore_all_writes_columns(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    upsert_job(conn, Job("t", "1", "Junior Data Scientist", "Acme", "Vancouver, BC", "python sql"))
    upsert_job(conn, Job("t", "2", "Senior Data Scientist", "Acme", "Vancouver, BC"))
    counts = rescore_all(conn, CFG)
    assert counts["skip"] == 1
    rows = {r["external_id"]: r for r in conn.execute("SELECT * FROM jobs")}
    assert rows["1"]["score"] > 0 and rows["1"]["score_reasons"]
    assert rows["2"]["tier"] == "skip" and rows["2"]["score"] is None
