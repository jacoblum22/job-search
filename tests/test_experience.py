import pytest

from src.experience import parse_min_years_experience


@pytest.mark.parametrize(
    "text, years",
    [
        ("- 5+ years in P&C insurance analytics, actuarial, underwriting", 5),
        ("* 2–4 years in a data or business analyst role", 2),
        ("- 3+ years of C++ development.", 3),
        ("Requirements\n- 4 years working with SQL and Python", 4),
        ("3+ years building data pipelines", 3),
        ("Minimum 3 years of relevant experience", 3),
    ],
)
def test_requirement_lines_without_the_word_experience(text, years):
    assert parse_min_years_experience(text) == years


@pytest.mark.parametrize(
    "text",
    [
        "For over 25 years, Global Relay has set the standard.",
        "We have been in business for 35 years in the community.",
        "Our team has 20 years in business serving clients.",
        "* One year of post-secondary (30-60 credits) - wage step 2",
        "The contract runs for 2 years in Vancouver.",
    ],
)
def test_company_history_and_education_are_not_experience(text):
    assert parse_min_years_experience(text) is None


@pytest.mark.parametrize(
    "text, years",
    [
        # J.D. Power / Autodata Data Engineer (jobs 1379, 956): "yrs" was never read.
        (
            "* At least 5 yrs of professional experience with a Bachelor’s degree or 3 yrs with a "
            "Graduate degree as a full-time professional (non-academic) experience in data engineering",
            5,
        ),
        ("5+ yrs experience in data engineering", 5),
        ("Requires 4 yrs. of SQL experience", 4),
        ("1 yr of experience with Tableau", 1),
        ("5 plus years of experience", 5),
        ("three-plus years of experience", 3),
    ],
)
def test_abbreviated_and_plus_forms(text, years):
    assert parse_min_years_experience(text) == years


@pytest.mark.parametrize(
    "text, years",
    [
        # The bachelor's half drops the unit; it's the half that applies to a bachelor's holder.
        (
            "3+ years of full-time, non-academic data engineering experience with a graduate degree, "
            "or 5+ with a bachelor's",
            5,
        ),
        ("2 years of experience with a Master's degree, or 4 with a Bachelor's degree", 4),
        ("3 years of analytics experience (5 for candidates with a diploma)", 5),
        ("Two years of experience with a PhD or four with a BSc", 4),
    ],
)
def test_degree_conditional_years(text, years):
    assert parse_min_years_experience(text) == years


@pytest.mark.parametrize(
    "text, years",
    [
        ("- Minimum of 3 years of full-time work in analytics", 3),
        ("3+ years of full-time experience as a data analyst", 3),
    ],
)
def test_full_time_phrasings(text, years):
    assert parse_min_years_experience(text) == years


@pytest.mark.parametrize(
    "text",
    [
        "Applicants must be 18 yrs old.",
        "A Bachelor's degree, or 2 with a diploma",  # no years requirement before it
        "Python experience is a plus. We grew 5 plus offices.",
    ],
)
def test_new_forms_do_not_overmatch(text):
    assert parse_min_years_experience(text) is None
