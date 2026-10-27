import pytest

from src.experience import YearsAsk, parse_min_years_experience, parse_years_ask


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


@pytest.mark.parametrize(
    "text, required, preferred",
    [
        ("Requirements:\n- 2+ years of experience with SQL\n", 2, None),
        ("Preferred Qualifications:\n- 3+ years of experience with SQL\n", None, 3),
        ("- 1+ years of experience with SQL\n- 3+ years of Python experience is an asset\n", 1, 3),
        ("Bachelor's degree. 2 years of relevant experience preferred.", None, 2),
        ("No years mentioned here.", None, None),
    ],
)
def test_years_ask_splits_required_and_preferred(text, required, preferred):
    assert parse_years_ask(text) == YearsAsk(required, preferred)


def test_preference_cue_after_semicolon_covers_only_its_part():
    text = "Qualifications\n- 5+ years as a Systems Analyst; 4+ years of testing experience preferred\n"
    assert parse_years_ask(text) == YearsAsk(5, 4)


def test_preference_cue_on_a_later_comma_part_isnt_about_the_years():
    text = "What We're Looking For\n* 5+ years of experience in data analytics, ideally within a SaaS company.\n"
    assert parse_years_ask(text) == YearsAsk(5, None)
    assert parse_years_ask("Ideally, 2+ years of experience with SQL.") == YearsAsk(None, 2)


@pytest.mark.parametrize(
    "text, years",
    [
        # VCH Business Advisor, Data and Analytics (job 1221): scored A 82 with no years penalty.
        ("Bachelor's degree in Data Science or related field, with a minimum of three (3) years’ "
         "recent, related experience in data analysis", 3),
        ("plus at least one (1) years’ experience as a Data Engineer", 1),
        ("3 (three) years of experience in SQL", 3),
        ("Diploma plus three to four (3-4) years' recent, related experience", 3),
        ("plus five (5) to seven (7) years of related experience in decision support", 5),
        ("A minimum of one to two (1-2) years recent related experience", 1),
        ("• 2-4 (max) years of experience in data analysis", 2),
        ("* Two to five years of experience in project reporting", 2),
        ("* Two or more years’ experience working in drug discovery", 2),
        ("* 3 or more years of professional software development experience", 3),
        ("* Minimum 2**+ years** professional working experience as a **Data Engineer**", 2),
        ("- **3+ years** in data analytics.", 3),
        ("* 10​+ years of experience in ASIC Design Verification", 10),
    ],
)
def test_spelled_bracketed_and_formatted_numbers(text, years):
    assert parse_min_years_experience(text) == years


@pytest.mark.parametrize(
    "text",
    [
        "Serving one (1) million residents for over twenty years",
        "Compensation: $70,000 to $85,000 per year, based on experience",
        "In this two-year program you will gain meaningful work experience",
    ],
)
def test_folding_numbers_does_not_overmatch(text):
    assert parse_min_years_experience(text) is None


def test_bracketed_years_keep_their_section():
    text = "Requirements\n- Two (2) years of experience with SQL\n\nAssets\n- Three (3) years of Tableau experience"
    assert parse_years_ask(text) == YearsAsk(required=2, preferred=3)
