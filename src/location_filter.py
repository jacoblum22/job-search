"""Classify a job's location as Vancouver-area, remote-eligible, or other.

Used both to decide what's worth fetching from broad/national searches (so
the aggregator doesn't pull in every on-site Toronto/Calgary posting) and
to tag every ingested job with a visible category, so nothing is silently
hidden — see AGGREGATION_PLAN.md.
"""

from __future__ import annotations

import re

# Deliberately generous — Metro Vancouver municipalities + common aliases.
# Under-matching here silently drops real local jobs, which is the failure
# mode we most want to avoid.
VANCOUVER_KEYWORDS = [
    "vancouver",
    "burnaby",
    "richmond",
    "surrey",
    "delta",
    "coquitlam",
    "port coquitlam",
    "port moody",
    "new westminster",
    "north vancouver",
    "west vancouver",
    "langley",
    "maple ridge",
    "pitt meadows",
    "white rock",
    "tsawwassen",
    "ladner",
    "anmore",
    "belcarra",
    "bowen island",
    "lions bay",
    "greater vancouver",
    "metro vancouver",
    "lower mainland",
    "tri-cities",
]

_REMOTE_PATTERN = re.compile(r"\b(remote|work from home|wfh|anywhere)\b", re.IGNORECASE)

# If the location mentions remote AND one of these, it's probably not
# actually open to a Canada-based applicant — unless "canada" is also
# explicitly mentioned (e.g. "Remote - Canada/US"). Remote US is kept: Jake
# is a US citizen living in Canada, so US work authorization is fine; roles
# that require living in the US are skipped later by the score (src/score.py).
_NON_CANADA_MARKERS = [
    "india",
    "philippines",
    "united kingdom",
    " uk ",
    "emea",
    "apac",
    "europe",
    "mexico",
]


def is_vancouver_area(location: str) -> bool:
    loc = (location or "").lower()
    return any(kw in loc for kw in VANCOUVER_KEYWORDS)


def is_remote(location: str) -> bool:
    loc = (location or "").lower()

    # Bare "Canada" with no city is how some APIs tag a nationwide remote role.
    if loc.strip().strip(".") == "canada":
        return True

    if not _REMOTE_PATTERN.search(loc):
        return False

    if "canada" in loc:
        return True

    return not any(marker in f" {loc} " for marker in _NON_CANADA_MARKERS)


def classify_location(location: str, company: str = "") -> str:
    """Return "vancouver", "remote", or "other".

    Some employers (e.g. Workday boards for municipal/regional orgs) list an
    internal facility code as the location — "LOC0049 Brookside Utilities
    Building" — with no city name at all, even though the posting is
    unambiguously local ("City of Vancouver" as the employer). Falling back
    to checking the company name for a Vancouver-area match catches these
    without needing per-org config.
    """
    if is_vancouver_area(location) or is_vancouver_area(company):
        return "vancouver"
    if is_remote(location):
        return "remote"
    return "other"


def is_relevant(location: str, company: str = "") -> bool:
    """True if the job is Vancouver-area or remote-eligible."""
    return classify_location(location, company) != "other"
