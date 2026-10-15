"""Keep-logic: aliases, noisy 'events', location, seniority."""

from __future__ import annotations

from types import SimpleNamespace

from src.search_match import api_queries, keep_job, text_matches_canonical

# Fixed search config so these tests exercise the matching logic, not whatever
# keywords the live config/settings.yaml happens to target.
_SEARCH = {
    "location": "Vancouver, BC",
    "remote_sweep_location": "Canada",
    "require_relevant_location": True,
    "keywords": [
        "Public affairs",
        "Talent acquisition",
        "Indigenous Relations",
        "Events",
        "Market Intelligence",
        "Market Research",
        "Business strategy",
        "Business Development",
        "Business Analyst",
        "Human Resources",
        "Campus Recruitment",
    ],
    "level_terms": ["intern", "internship", "co-op", "coop", "new grad", "entry level", "student", "junior"],
    "exclude_title_terms": [
        "senior", "sr", "director", "manager", "lead", "principal", "vice president",
        "vice-president", "vp", "head", "chief", "ux", "ui/ux", "user experience",
    ],
    "max_years_experience": 2,
}


def _search() -> dict:
    return {k: list(v) if isinstance(v, list) else v for k, v in _SEARCH.items()}


def _job(**kwargs):
    defaults = dict(
        title="x",
        company="",
        location="Vancouver, BC",
        description="",
        years_experience=None,
        raw=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_hr_coordinator_title_matches_human_resources():
    s = _search()
    assert keep_job(
        _job(title="HR Coordinator Co-op"),
        s,
        match_keywords=True,
    )


def test_recruiting_in_description_does_not_match_ta():
    s = _search()
    job = _job(
        title="Warehouse Associate",
        description="We are recruiting a warehouse associate for our Burnaby site.",
        location="Burnaby, BC",
    )
    assert not keep_job(job, s, match_keywords=True)


def test_recruiter_in_title_matches():
    s = _search()
    assert keep_job(_job(title="Campus Recruiter Intern"), s, match_keywords=True)


def test_events_boilerplate_in_description_does_not_match():
    s = _search()
    job = _job(
        title="Software Developer Intern",
        description="In the event of a system outage, contact IT. Vancouver office.",
    )
    assert not text_matches_canonical("Events", job.title, job.description, s)


def test_event_coordinator_title_matches_events():
    s = _search()
    assert keep_job(_job(title="Event Coordinator Intern"), s, match_keywords=True)


def test_boilerplate_human_resources_in_description_does_not_keep_unrelated_title():
    s = _search()
    job = _job(
        title="Facilities HVAC Technician",
        description="Apply through Human Resources. We are a business development minded team.",
        location="Vancouver, BC",
        company="City of Vancouver",
    )
    assert not keep_job(job, s, match_keywords=True)


def test_precise_body_intern_phrase_keeps_generic_title():
    s = _search()
    job = _job(
        title="Co-op Student, Information Systems",
        description="This business analyst intern will own reporting dashboards.",
        location="UBC Vancouver Campus",
        company="UBC",
    )
    assert keep_job(job, s, match_keywords=True)
    s = _search()
    assert keep_job(
        _job(title="Program Coordinator, The Office of Indigenous Strategic Initiatives"),
        s,
        match_keywords=True,
    )


def test_senior_title_excluded():
    s = _search()
    assert not keep_job(_job(title="Senior Business Analyst"), s, match_keywords=True)


def test_years_experience_cap():
    s = _search()
    assert not keep_job(
        _job(title="Business Analyst Intern", years_experience=5),
        s,
        match_keywords=True,
    )


def test_toronto_onsite_dropped():
    s = _search()
    assert not keep_job(
        _job(title="Business Analyst Intern", location="Toronto, Ontario"),
        s,
        match_keywords=True,
    )


def test_remote_canada_kept():
    s = _search()
    assert keep_job(
        _job(title="Business Analyst Intern", location="Remote, Canada"),
        s,
        match_keywords=True,
    )


def test_city_of_vancouver_facility_code_via_company():
    s = _search()
    assert keep_job(
        _job(
            title="Business Analyst",
            location="LOC0049 Brookside Utilities Building",
            company="City of Vancouver",
        ),
        s,
        match_keywords=True,
    )


def test_api_queries_include_co_op_and_hr_alias():
    s = _search()
    qs = [q.lower() for q in api_queries(s)]
    assert any("co-op" in q for q in qs)
    assert any("hr intern" == q or q.startswith("hr intern ") for q in qs)
    assert "business analyst intern" in qs
    assert len(qs) < 150


def test_require_relevant_location_can_be_disabled():
    s = dict(_search())
    s["require_relevant_location"] = False
    assert keep_job(
        _job(title="Business Analyst Intern", location="Toronto, Ontario"),
        s,
        match_keywords=True,
    )


def test_should_hydrate_skips_hvac_and_keeps_intern():
    from src.search_match import should_hydrate_record

    s = _search()
    assert not should_hydrate_record("Facilities HVAC Technician", s, company="City of Vancouver")
    assert should_hydrate_record("Recruiter", s)
    assert should_hydrate_record("Co-op Student, Information Systems", s)


def test_graduate_program_titles_are_worth_a_fetch():
    from src.search_match import should_hydrate_record

    assert should_hydrate_record("2K Games – Engineering Graduate Program – Vancouver", {"keywords": ["data analyst"]})
    assert should_hydrate_record("Indigenous – New & Recent Graduates", {"keywords": ["data analyst"]})
