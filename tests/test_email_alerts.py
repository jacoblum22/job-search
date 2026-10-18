"""Alert-email parsers, on synthetic emails shaped like the real ones
(checked against real Indeed, Glassdoor, Jobright and Wellfound alerts on
2026-10-18). No real tracking tokens or addresses here: the repo is public."""

import base64
import gzip
import json
from datetime import UTC, datetime

from src.sources import glassdoor_email, indeed_email, jobright_email, wellfound_email
from src.sources.email_common import EmailMessage


def _msg(plain: str = "", html: str = "", subject: str = "Alert") -> EmailMessage:
    return EmailMessage("m1", subject, datetime(2026, 10, 18, tzinfo=UTC), plain, html)


INDEED_DIGEST = """Indeed Job Alert
2 new data analyst opportunities in Vancouver, BC

Jobs 1-2 of 2 new jobs
See matching results on Indeed: https://ca.indeed.com/jobs?q=data+analyst&from=ja

Junior Data Analyst
Example Corp - Vancouver, BC
$60,000–$70,000 a year
Easily apply
Build dashboards in SQL and Python for the operations team.
2 days ago
https://ca.indeed.com/rc/clk/dl?jk=0123456789abcdef&from=ja&tk=abc

Reporting Analyst
Sample Co. - Ops - Burnaby, BC
Responsive employer
Own weekly reports.
Just posted
https://ca.indeed.com/pagead/clk/dl?mo=r&ad=xyz&from=ja

Unsubscribe: https://ca.indeed.com/unsubscribe
"""


def test_indeed_digest_blocks():
    jobs = indeed_email.parse_message(_msg(INDEED_DIGEST))
    assert [j.title for j in jobs] == ["Junior Data Analyst", "Reporting Analyst"]
    first, ad = jobs
    assert first.external_id == "0123456789abcdef"
    assert first.company == "Example Corp"
    assert first.location == "Vancouver, BC"
    assert first.url == "https://ca.indeed.com/viewjob?jk=0123456789abcdef"
    assert first.description.startswith("Salary: $60,000–$70,000 a year")
    assert "dashboards" in first.description
    assert (
        "2 days ago" not in first.description
        and "Easily apply" not in first.description
    )
    # Sponsored: no job key, stable hashed id; company keeps its own " - ".
    assert ad.external_id.startswith("ad-")
    assert ad.company == "Sample Co. - Ops"
    assert ad.location == "Burnaby, BC"
    assert ad.url.startswith("https://ca.indeed.com/pagead/clk")
    assert (
        ad.external_id == indeed_email.parse_message(_msg(INDEED_DIGEST))[1].external_id
    )


def _cts(url: str) -> str:
    raw = gzip.compress(json.dumps({"u": url, "m": {}}).encode())
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def test_indeed_match_email():
    token = _cts("https://ca.indeed.com/rc/clk?jk=fedcba9876543210&from=jobmatch")
    plain = f"""Hi there,

This role could be a match.

Junior Machine Learning Engineer
Example Labs
Vancouver, BC V6B 1A1
Salary: $70,000–$80,000 a year
Job type: Permanent

Benefits:
  - Dental care

View job: https://cts.indeed.com/v3/{token}/sig
Apply now: https://cts.indeed.com/v3/{token}/sig
"""
    (job,) = indeed_email.parse_message(_msg(plain))
    assert job.external_id == "fedcba9876543210"
    assert job.title == "Junior Machine Learning Engineer"
    assert job.company == "Example Labs"
    assert job.location == "Vancouver, BC V6B 1A1"
    assert job.location_category == "vancouver"
    assert "Salary: $70,000–$80,000 a year" in job.description


def _gd_card(job_id: str, *pieces: str) -> str:
    inner = "".join(f"<span>{p}</span>" for p in pieces)
    return (
        f'<a href="https://www.glassdoor.ca/partner/x.htm?jobListingId={job_id}&uido=X"><img src="l.png"></a>'
        f'<a href="https://www.glassdoor.ca/partner/x.htm?jobListingId={job_id}&uido=X">{inner}</a>'
    )


def test_glassdoor_cards():
    html = (
        "<table>"
        + _gd_card(
            "111",
            "Example Corp",
            "3.5 ★",
            "Data Analyst",
            "Richmond",
            "$60K - $70K",
            "(",
            "Employer Est.",
            ")",
            "Easy Apply",
            "2d",
        )
        + _gd_card(
            "222",
            "No Rating Inc",
            "Business Systems Analyst",
            "Vancouver",
            "$43",
            "(",
            "Employer Est.",
            ")",
            "11d",
        )
        + "</table>"
    )
    jobs = glassdoor_email.parse_message(_msg(html=html))
    assert [(j.external_id, j.company, j.title, j.location) for j in jobs] == [
        ("111", "Example Corp", "Data Analyst", "Richmond"),
        ("222", "No Rating Inc", "Business Systems Analyst", "Vancouver"),
    ]
    assert jobs[0].url == "https://www.glassdoor.ca/job-listing/j?jl=111"
    assert jobs[0].description == "Salary: $60K - $70K (employer estimate)"


def _jr_card(job_id: str, company: str, title: str, *tags: str) -> str:
    tag_html = "".join(f'<p id="job-tag">{t}</p>' for t in tags)
    return (
        f'<table><tr><td><p id="job-company-name">{company}</p>'
        f'<p id="job-title"><a href="https://jobright.ai/jobs/info/{job_id}?utm_source=1">{title}</a></p>'
        f'{tag_html}<span id="job-time-posted">1 hour ago</span></td></tr></table>'
    )


def test_jobright_cards():
    html = (
        "<div>"
        + _jr_card(
            "a" * 24,
            "Example (EX)",
            "Software Engineer Intern",
            "CA$65K/yr - CA$70K/yr",
            "Vancouver, BC",
            "11+ referrals",
        )
        + _jr_card("b" * 24, "Remote Co", "Data Analyst", "Remote", "2+ referrals")
        + "</div>"
    )
    jobs = jobright_email.parse_message(_msg(html=html))
    assert [(j.title, j.company, j.location) for j in jobs] == [
        ("Software Engineer Intern", "Example (EX)", "Vancouver, BC"),
        ("Data Analyst", "Remote Co", "Remote"),
    ]
    assert jobs[0].url == f"https://jobright.ai/jobs/info/{'a' * 24}"
    assert jobs[0].description == "Salary: CA$65K/yr - CA$70K/yr"
    assert jobs[1].description == ""


def _wf_card(title: str, company: str, *rest: str) -> str:
    spans = "".join(f"<span>{r}</span>" for r in rest)
    return (
        f'<table><tr><td><div style="font-weight:700;color:#000">{title}</div>'
        f'<span style="color:#541142">{company}</span>{spans}'
        f'<a href="https://links.wellfound.com/s/c/redirect">Learn more</a></td></tr></table>'
    )


WF_HTML = (
    "<div>"
    + _wf_card(
        "Data Engineer",
        "Example Data",
        "/ 501-1000 Employees",
        "$90k – $100k",
        "|",
        "Miami, Troy",
        "|",
        "2 years of exp",
        "Actively Hiring",
        "Our take",
        "Example Data is hiring a remote Data Engineer in Canada to build pipelines.",
    )
    + _wf_card(
        "Data Analyst",
        "Sample Startup",
        "/ 1-10 Employees",
        "Vancouver",
        "|",
        "0 years of exp",
        "Actively Hiring",
    )
    + "</div>"
)
WF_PLAIN = """Learn more
<https://wellfound.com/jobs/1000001-data-engineer?email_uid=1>

Learn more
<https://wellfound.com/jobs/1000002-data-analyst?email_uid=1>
"""


def test_wellfound_cards_pair_with_plaintext_links():
    jobs = wellfound_email.parse_message(_msg(WF_PLAIN, WF_HTML))
    first, second = jobs
    assert (first.external_id, first.title, first.company) == (
        "1000001",
        "Data Engineer",
        "Example Data",
    )
    assert first.url == "https://wellfound.com/jobs/1000001-data-engineer"
    # The summary says remote in Canada, so the location filter keeps it.
    assert first.location == "Miami, Troy; Remote, Canada"
    assert first.location_category == "remote"
    assert "Salary: $90k – $100k" in first.description
    assert (second.external_id, second.location) == ("1000002", "Vancouver")
    assert second.description == "0 years of exp"


def test_wellfound_falls_back_to_hashed_ids():
    jobs = wellfound_email.parse_message(_msg("", WF_HTML))
    assert all(j.external_id.startswith("h-") for j in jobs)
    assert jobs[0].url == "https://links.wellfound.com/s/c/redirect"
