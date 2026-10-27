from datetime import date

import pytest

import json

from src.posting_status import closed_reason, deadline, due_date, raw_deadline

TODAY = date(2026, 10, 20)
SEEN = date(2026, 10, 1)


@pytest.mark.parametrize("text, end", [
    ("## **Posting End Date**\n\nOctober 15, 2026\n\n**Note:** Applications will be accepted", date(2026, 10, 15)),
    ("**Posting End Date:**\n\n13/10/2026", date(2026, 10, 13)),          # day first
    ("The application window is expected to close on: 11/14/2026", date(2026, 11, 14)),  # month first
    ("**Application Deadline:**  2026-10-09  **Note**", date(2026, 10, 9)),
    ("**Closing Date:**  Friday, October 16 2026", date(2026, 10, 16)),
    ("please apply online by **4pm on October 26, 2026**.", date(2026, 10, 26)),
    ("Please submit your application via Workday by October 22nd, 2026.", date(2026, 10, 22)),
    ("$90,000 · Applications close **Nov 15, 2026**", date(2026, 11, 15)),
    ("Base salary: $100,000 · Posting closes 2026-10-23", date(2026, 10, 23)),
    ("Deadline for applications is on November 8, 2026 at 11:59 PM PST.", date(2026, 11, 8)),
    ("Applications accepted until Oct 21, 2026", date(2026, 10, 21)),
    ("Application deadline: October 30", date(2026, 10, 30)),               # no year: after first seen
    ("Applications for this position will be accepted until **Oct. 15, 2026** **Expo", date(2026, 10, 15)),
    ("Business UnitRegular, Full timeClosing Date: October 23, 2026  The", date(2026, 10, 23)),  # flattened page
    ("Open until filled (expires Dec 31, 2026)", date(2026, 12, 31)),
    ("Application window expected to close 11/14/2026.", date(2026, 11, 14)),
    ("regular posting (APTPUO) · **Apply before 2026-11-07** **Pay:**", date(2026, 11, 7)),
    ("Our application deadline is 40 days from the date of posting.", date(2026, 11, 10)),  # from first seen
    ("- Application deadline 40 days from posting.", date(2026, 11, 10)),
    ("Show how to apply  ### Advertised until  2026-10-29  **Important notice", date(2026, 10, 29)),  # Job Bank
    ("We're accepting applications now through end of day onFriday, October 2, 2026.", date(2026, 10, 2)),
    ("* August 2026 – Application Window Opens  * November 30, 2026\u00a0– Application Window Closes",
     date(2026, 11, 30)),
])
def test_reads_the_deadline(text, end):
    assert deadline(text, SEEN) == end


@pytest.mark.parametrize("text", [
    "Able to manage multiple deadlines. Start date: October 1, 2026.",
    "The internal job posting expires on October 2, 2026 and will no longer be accessible.",
    "Job End Date\n\nAugust 31, 2027",
    "Review of applications will begin on October 1, 2026.",
    "the internal job posting will no longer be accessible after the expiry date of October 23, 2026.",
    "Temporary, Full-Time (Until December 27, 2027) Salary",
    "Investigates incorrect invoices and expiry dates of contracts. Start May 2027.",
])
def test_ignores_dates_that_are_not_the_closing_date(text):
    assert deadline(text, SEEN) is None


def test_ambiguous_numeric_date_takes_the_later_reading():
    assert deadline("Posting End Date: 05/11/2026", SEEN) == date(2026, 11, 5)


def test_closed_after_the_deadline_day_only():
    text = "Posting End Date: October 20, 2026"
    assert closed_reason(text, TODAY) is None
    assert closed_reason(text, date(2026, 10, 21)) == "Closed Oct 20, 2026"


def test_filled_internally():
    text = "This position will be filled internally. It is posted for informational purposes only."
    assert closed_reason(text, TODAY) == "Filled internally"
    assert closed_reason("We recommend that all internal applicants advise their manager.", TODAY) is None


def test_open_posting():
    assert closed_reason("SQL and dashboards. Apply by November 30, 2026.", TODAY) is None


@pytest.mark.parametrize("raw, end", [
    ({"jobPostingInfo": {"endDate": "2026-10-19"}, "similarJobs": [{"endDate": "2026-12-01"}]}, date(2026, 10, 19)),
    ({"postingExpiryTimestampUTC": "2026-10-31T03:59:00+00:00"}, date(2026, 10, 30)),  # Dayforce, Pacific time
    ({"validThrough": "2026-11-30T00:00:00-05:00"}, date(2026, 11, 30)),
    ({"closes": "2026-11-05"}, date(2026, 11, 5)),
    ({"expiryDate": 1793836800}, date(2026, 11, 5)),  # Unix seconds
    ({"postingExpiryTimestampUTC": None}, None),
    ({"id": 1}, None),
])
def test_reads_the_closing_date_in_source_data(raw, end):
    assert raw_deadline(json.dumps(raw)) == end


def test_source_data_deadline_closes_the_posting():
    raw = json.dumps({"jobPostingInfo": {"endDate": "2026-10-19"}})
    assert due_date("SQL and dashboards.", SEEN, raw) == date(2026, 10, 19)
    assert closed_reason("SQL and dashboards.", TODAY, SEEN, raw) == "Closed Oct 19, 2026"
    assert closed_reason("SQL and dashboards.", TODAY, SEEN, None) is None


def test_source_data_date_a_year_out_is_no_deadline():
    # iCIMS sends validThrough as a year from the day the page was fetched.
    raw = json.dumps({"validThrough": "2027-10-27T00:00:00-07:00"})
    assert due_date("SQL and dashboards.", date(2026, 10, 16), raw) is None
    near = json.dumps({"validThrough": "2027-01-15T00:00:00-08:00"})
    assert due_date("SQL and dashboards.", date(2026, 10, 16), near) == date(2027, 1, 15)
