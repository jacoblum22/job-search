from src.db import Job
from src.location_filter import classify_location, location_from_description


def test_bare_country_reads_the_description():
    # Adzuna gives "Canada" for postings with no city in the location field.
    assert classify_location("Canada", "BDO", "Our Toronto office is looking for a Consultant.") == "other"
    assert classify_location("Canada", "X", "**Work Location:** Toronto, Ontario, Canada") == "other"
    assert classify_location("Canada", "X", "Join our hybrid team, 2 days a week in the office.") == "other"
    assert classify_location("Canada", "X", "**Role Designation:** Remote") == "remote"
    assert classify_location("Canada", "X", "Location: Canada - Fully Remote") == "remote"
    assert classify_location("Canada", "X", "VANCOUVER, BC (OR REMOTE IN CANADA)") == "vancouver"
    assert classify_location("Canada", "X", "Remote, based in AB, SK, or MB.") == "other"


def test_bare_country_with_a_silent_description_stays_remote():
    assert classify_location("Canada", "X", "SQL and dashboards for the analytics team.") == "remote"
    assert classify_location("Canada", "X") == "remote"


def test_description_only_matters_for_a_bare_country():
    # A real city in the location field wins over anything the text says.
    assert classify_location("Vancouver, BC", "X", "Our Toronto office ...") == "vancouver"
    assert classify_location("Remote - Canada", "X", "hybrid, 2 days in office") == "remote"


def test_names_that_mean_something_else_are_not_vancouver():
    assert location_from_description("Experience with Delta Lake and Spark.") is None
    assert location_from_description("Our office in Vancouver, WA is hybrid.") == "other"


def test_job_category_uses_the_description():
    job = Job("adzuna", "1", "Data Analyst", "CorGTA", "Canada", "Location: Downtown Toronto", "https://x/1")
    assert job.location_category == "other"


def test_us_work_site_in_the_description_is_not_canada():
    # Seen live: "Canada" location, description names a Fairfax, VA job site.
    desc = "Machine Learning Engineer\nJob Site: 3701 Pender Drive, Fairfax, VA\nBuild models."
    assert classify_location("Canada", "X", desc) == "other"
    # A labelled US site beats a "remote" mention elsewhere in the posting.
    assert classify_location("Canada", "X", desc + "\nWe are remote-friendly.") == "other"
    assert classify_location("Canada", "X", "Office: Austin, TX 78701. Hybrid.") == "other"
    assert classify_location("Canada", "X", "Based in Reston, VA 20190") == "other"


def test_us_place_pattern_does_not_hit_canadian_or_plain_text():
    assert classify_location("Canada", "X", "Job Site: 100 Pender St, Vancouver, BC") == "vancouver"
    assert classify_location("Canada", "X", "Fully remote. Offices in Austin, TX and Toronto.") == "remote"
    assert classify_location("Canada", "X", "Work with SQL, Python, etc. Apply in Ottawa, CA") == "other"  # Ottawa wins
    assert classify_location("Canada", "X", "Questions? Reach us, OR call. Remote role.") == "remote"
    assert location_from_description("Santa Clara, CA based team") is None
