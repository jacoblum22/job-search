from src.db import Job, connect, reflow_stored
from src.reflow import reflow

FLAT = (
    "Description Do you enjoy translating data into insights? At Amazon, we hire the best minds "
    "- customer obsession is part of our DNA. Key job responsibilities As a Business Intelligence "
    "Engineer, you will: - Build small- to mid-size BI solutions - Troubleshoot data, analyses, and "
    "code A day in the life We&#39;re on the lookout. Basic Qualifications - 3+ years of analyzing "
    "data with Redshift, Oracle, NoSQL etc. experience - 2+ years of Tableau Desktop Preferred "
    "Qualifications - Master&#39;s degree in BI, finance - Experience with AWS &amp; Python "
) + "Amazon is an equal opportunity employer. " * 15


def test_flat_posting_gets_headings_and_bullets_back():
    out = reflow(FLAT)
    lines = out.split("\n")
    for heading in ("Description", "Key job responsibilities", "A day in the life",
                    "Basic Qualifications", "Preferred Qualifications"):
        assert heading in lines
    assert "- 3+ years of analyzing data with Redshift, Oracle, NoSQL etc. experience" in lines
    assert "- Master's degree in BI, finance" in lines
    assert "AWS & Python" in out
    # A dash inside a sentence stays put.
    assert "best minds - customer obsession" in out


def test_text_that_already_has_lines_is_untouched():
    text = "Requirements\n- SQL\n- Python &amp; R\n" + "x " * 500
    assert reflow(text) == text
    assert reflow("short &amp; flat") == "short &amp; flat"


def test_everyday_words_need_a_colon_to_be_headings():
    text = "We value Experience With customers. Location: Vancouver, BC " + "Filler text. " * 80
    out = reflow(text)
    assert "value Experience With customers" in out
    assert "\nLocation\nVancouver" in out


def test_reflow_is_stable():
    assert reflow(reflow(FLAT)) == reflow(FLAT)


def test_job_and_stored_rows_are_reflowed(tmp_path):
    job = Job(source="adzuna", external_id="1", title="BIE", company="Amazon", location="Vancouver",
              description=FLAT)
    assert "\nBasic Qualifications\n" in job.description
    conn = connect(tmp_path / "jobs.db")
    conn.execute("INSERT INTO jobs (dedup_group_id, source, external_id, title, company, location, "
                 "description, first_seen, last_seen) "
                 "VALUES ('g', 'adzuna', '2', 'BIE', 'Amazon', 'Vancouver', ?, '2026-10-22', '2026-10-22')", (FLAT,))
    assert reflow_stored(conn) == 1
    assert reflow_stored(conn) == 0
    stored = conn.execute("SELECT description FROM jobs").fetchone()[0]
    assert stored == reflow(FLAT)


def test_markdown_bold_headings_and_star_bullets():
    text = ("**Introduction** At **IBM** , we transform. **Your role** You'll help clients. "
            "Work includes: * Run workshops. * Document requirements. "
            "*Required Skills:* * 3+ years of SQL. About the Team: We build things. ") + "Filler. " * 120
    lines = reflow(text).split("\n")
    assert lines[0] == "**Introduction**"
    assert "At **IBM** , we transform." in lines
    assert "**Your role**" in lines and "*Required Skills:*" in lines
    assert "- Run workshops." in lines and "- 3+ years of SQL." in lines
    assert "About the Team:" not in lines and "About the Team" in lines


def test_lowercase_heading_words_mid_sentence_stay():
    text = "You must meet the requirements Amazon sets for the role. " * 20
    assert reflow(text) == text
