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
