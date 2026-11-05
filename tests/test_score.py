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


def test_rescore_all_cache_skips_unchanged_rows(tmp_path, monkeypatch):
    conn = connect(tmp_path / "jobs.db")
    upsert_job(conn, Job("t", "1", "Junior Data Scientist", "Acme", "Vancouver, BC", "python sql"))
    upsert_job(conn, Job("t", "2", "Data Analyst", "Acme", "Vancouver, BC", "excel"))
    cache: dict = {}
    first = rescore_all(conn, CFG, cache=cache)

    import src.score as score_mod
    scored = []
    real = score_mod.score_job
    monkeypatch.setattr(score_mod, "score_job", lambda **kw: scored.append(kw["title"]) or real(**kw))
    assert rescore_all(conn, CFG, cache=cache) == first
    assert scored == []  # nothing changed, nothing rescored

    conn.execute("UPDATE jobs SET description = 'python sql tableau' WHERE external_id = '2'")
    rescore_all(conn, CFG, cache=cache)
    assert scored == ["Data Analyst"]


INTEGRATION_ENGINEER = (
    "Configure integrations for enterprise customers and troubleshoot tickets. "
    "Experience with Python. Experience with SQL. "
    "Familiar with Git & Docker. Bachelor's degree in Computer Science. "
) * 3


def test_technical_title_backed_by_skills_ranks_a():
    r = _score("Integration Engineer", INTEGRATION_ENGINEER)
    assert r.tier == "A"
    assert any("technical title" in x for x in r.reasons)
    assert any("python + sql" in x for x in r.reasons)
    assert any("no skill gaps" in x for x in r.reasons)


def test_technical_title_without_skills_gets_no_title_points():
    r = _score("Mechanical Engineer", "Design HVAC systems in AutoCAD. " * 20)
    assert not any("technical title" in x for x in r.reasons)


def test_student_title_skipped_unless_it_says_new_grad():
    assert _score("Data Analyst Co-op Student").tier == "skip"
    r = _score("Student / New Grad Positions - Technology and Analytics")
    assert r.tier != "skip"


def test_years_range_in_title_is_not_a_level():
    r = _score("Software Engineer - Master's New Grad / Bachelor's 2-3 Years Experience", "python " * 50)
    assert not any("title level" in x for x in r.reasons)
    assert any("entry-level title" in x for x in r.reasons)


def test_title_level_ignored_when_posting_asks_two_years_or_less():
    r = _score("Intermediate Software Engineer", "python sql " * 50, years=2)
    assert not any("title level" in x for x in r.reasons)


def test_wrong_field_word_does_not_skip_a_data_title():
    assert _score("Data Scientist, Sales", "python sql " * 50).tier != "skip"
    assert _score("Sales Associate").tier == "skip"


def test_bare_analytics_title_gets_family_points():
    r = _score("Coordinator, Quality Improvement & Analytics", "sql dashboards " * 50)
    assert any("analytics title" in x for x in r.reasons)


def test_internship_is_a_penalty_not_a_skip():
    intern = _score("Data Science Intern", "python sql pandas " * 30)
    full = _score("Data Scientist", "python sql pandas " * 30)
    assert intern.tier != "skip"
    assert intern.score == full.score - 15


def test_co_op_is_still_skipped():
    assert _score("Data Scientist Co-op").tier == "skip"


def test_five_years_caps_tier_at_d():
    r = _score("Data Analyst", "SQL BigQuery Looker dashboards python pandas " * 20, years=5)
    assert r.tier == "D"
    assert r.score is not None


def test_phd_required_skips_but_phd_or_masters_does_not():
    assert _score("Data Scientist", "A PhD is required. python " * 30).tier == "skip"
    assert _score("Data Scientist", "Candidates must hold a PhD in statistics. " * 10).tier == "skip"
    r = _score("Data Scientist", "Bachelor's required; Master's or PhD preferred. python sql " * 20)
    assert r.tier != "skip"
    assert not any("phd" in x.lower() for x in r.reasons)


def test_required_masters_skipped():
    r = _score("Data Scientist", "* Master's or PhD in Biology or a related field.\n" + "python sql " * 40)
    assert r.tier == "skip"
    assert "Master's required" in r.reasons[0]


def test_optional_masters_penalised():
    desc = "python sql " * 40
    base = _score("Data Analyst", desc)
    for line in [
        "Bachelor's degree in Biology; Master's degree preferred.",
        "Master's degree in Biology, or experience working in Biology",
        "A master's degree is an asset.",
    ]:
        r = _score("Data Analyst", f"{line}\n{desc}")
        assert r.tier != "skip", line
        assert r.score == base.score - 10, line
        assert any("Master's preferred or optional" in x for x in r.reasons)


def test_masters_elsewhere_is_optional_when_bachelors_accepted():
    desc = "* Bachelor's degree with 3+ years of experience\n* An M.Sc. with 1+ years of experience\n" + "python sql " * 40
    assert _score("Data Analyst", desc).tier != "skip"


def test_bachelors_or_masters_costs_nothing():
    desc = "python sql " * 40
    base = _score("Data Analyst", desc).score
    for line in [
        "Bachelor's or Master's degree in Biology.",
        "Bachelor's/Master's in Biology or equivalent work experience",
        "Masters complex workflows quickly.",
        "Master's salaries range from $56,550 a year.",
    ]:
        assert _score("Data Analyst", f"{line}\n{desc}").score == base, line


def test_each_required_year_costs_more():
    desc = "python sql " * 40
    none = _score("Data Analyst", desc, years=None).score
    scores = [_score("Data Analyst", desc, years=y).score for y in range(6)]
    assert scores[0] > none  # "0-2 years" says no experience needed
    assert none > scores[1] > scores[2] > scores[3] > scores[4] > scores[5]


def _score_pref(title, description, years=None, preferred=None):
    return score_job(title=title, description=description, location_category="vancouver",
                     years_experience=years, years_preferred=preferred, cfg=CFG)


def test_preferred_years_cost_less_than_required():
    desc = "python sql " * 40
    none = _score("Data Analyst", desc).score
    required = _score_pref("Data Analyst", desc, years=3).score
    preferred = _score_pref("Data Analyst", desc, preferred=3)
    assert required < preferred.score < none
    assert any("prefers 3 years (not required)" in x for x in preferred.reasons)
    # Preferring fewer years than required adds nothing; preferring more counts only if it costs more.
    assert _score_pref("Data Analyst", desc, years=3, preferred=1).score == required
    assert _score_pref("Data Analyst", desc, years=1, preferred=5).score < _score_pref("Data Analyst", desc, years=1).score
    # A preferred 0 is no bonus.
    assert _score_pref("Data Analyst", desc, preferred=0).score == none


def test_preferred_years_dont_cap_tier():
    desc = "SQL BigQuery Looker dashboards python pandas " * 20
    assert _score_pref("Data Analyst", desc, years=5).tier == "D"
    assert _score_pref("Data Analyst", desc, preferred=5).tier != "D"


def test_open_to_new_grads_bonus():
    desc = "python sql " * 40
    base = _score("Data Analyst", desc).score
    for line in [
        "New grads welcome to apply!",
        "Ideal for recent university graduates.",
        "No prior experience required; we will train you.",
        "Experience is not required.",
        "0-2 years of experience in analytics.",
        "Open to students graduating in 2026.",
    ]:
        r = _score("Data Analyst", f"{line}\n{desc}")
        assert r.score > base, line
        assert any("open to new grads" in x for x in r.reasons), line
    for line in [
        "This role is not suitable for new grads.",
        "No new graduates please.",
        "Graduated from an accredited university.",
    ]:
        r = _score("Data Analyst", f"{line}\n{desc}")
        assert not any("open to new grads" in x for x in r.reasons), line


def test_no_new_grad_bonus_when_posting_requires_years():
    desc = "New grads welcome.\n" + "python sql " * 40
    assert any("open to new grads" in x for x in _score("Data Analyst", desc, years=1).reasons)
    assert not any("open to new grads" in x for x in _score("Data Analyst", desc, years=2).reasons)


def test_rescore_splits_required_and_preferred_years(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    base = "Analyze data with SQL and Python. " * 20
    upsert_job(conn, Job("x", "1", "Data Analyst", "Acme", "Vancouver, BC",
                         base + "\nRequirements:\n- 3+ years of experience in analytics\n"))
    upsert_job(conn, Job("x", "2", "Data Analyst", "Beta", "Vancouver, BC",
                         base + "\nNice to have:\n- 3+ years of experience in analytics\n"))
    rescore_all(conn, CFG)
    rows = dict(conn.execute("SELECT external_id, score_reasons FROM jobs").fetchall())
    assert "asks for 3 years" in rows["1"]
    assert "prefers 3 years (not required)" in rows["2"]


def test_rescore_reads_where_a_country_only_job_is(tmp_path):
    # Enrichment fills the description after insert; the rescore then places the job.
    conn = connect(tmp_path / "jobs.db")
    upsert_job(conn, Job("adzuna", "1", "Junior Data Analyst", "Acme", "Canada", "SQL"))
    conn.execute("UPDATE jobs SET description = ? WHERE external_id = '1'",
                 ("SQL and BigQuery daily. **Work Location:** Toronto, Ontario, Canada. " * 5,))
    rescore_all(conn, CFG)
    row = conn.execute("SELECT location_category, tier FROM jobs").fetchone()
    assert row["location_category"] == "other" and row["tier"] == "skip"


def test_required_language_skipped():
    desc = "python sql " * 40
    for line in [
        "* Fluency in Spanish.",
        "* Fully bilingual (English/French)",
        "• Spanish-speaking candidates mandatory",
        "* Ability to communicate effectively in French in a bilingual environment.",
    ]:
        r = _score("Data Analyst", line + "\n" + desc)
        assert r.tier == "skip", line
        assert "language required" in r.reasons[0]


def test_optional_language_not_skipped():
    desc = "python sql " * 40
    for line in [
        "* Bilingual in English and French is an asset",
        "* Bilingual (English and French) strongly preferred",
        "* Fluency in French will be considered an asset",
        "complete an attribute-based assessment and other skills test (such as simulation, coding, French proficiency)",
        "bilingualism (French, English, both oral and written) is required **for Quebec only**",
        "* Excellent written and verbal communication skills in English.",
    ]:
        assert _score("Data Analyst", line + "\n" + desc).tier != "skip", line


def test_over_five_years_preferred_still_skipped():
    assert _score_pref("Data Scientist", "python " * 50, years=4, preferred=6).tier == "skip"
