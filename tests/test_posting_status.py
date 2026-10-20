from datetime import date

import pytest

from src.posting_status import closed_reason, deadline

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
])
def test_reads_the_deadline(text, end):
    assert deadline(text, SEEN) == end


@pytest.mark.parametrize("text", [
    "Able to manage multiple deadlines. Start date: October 1, 2026.",
    "The internal job posting expires on October 2, 2026 and will no longer be accessible.",
    "Job End Date\n\nAugust 31, 2027",
    "Review of applications will begin on October 1, 2026.",
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
