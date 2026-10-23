"""Is a posting still open? Finds postings that say they're filled internally
and postings whose application deadline has passed.

Used by the tailoring queue (closed postings are never drafted) and the
dashboard (closed postings get a "Closed" badge). Worked out on the posting
text each time, so a deadline counts from the day it is checked.

Deadlines are read only after a closing cue ("Posting End Date",
"Application deadline", "apply by", "Applications close"...). A posting's
deadline for internal applicants ("The internal job posting expires on")
is not its closing date and is ignored. Applications are accepted until the
end of the deadline day, so a posting closes the day after.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from functools import lru_cache

_INTERNAL = re.compile(
    r"(?i)\b(?:will be|is being|to be) filled internally"
    r"|posted for informational purposes(?: only)?"
    r"|\b(?:open|available) (?:only )?to internal (?:applicants|candidates|employees) only"
    r"|\binternal (?:applicants|candidates) only\b"
)

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
_MON = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE = (
    r"(?P<iso>\d{4}-\d{2}-\d{2})"
    r"|(?P<num>\d{1,2}/\d{1,2}/\d{4})"
    r"|(?P<mdy>" + _MON + r"\s\d{1,2}(?:st|nd|rd|th)?(?:,?\s\d{4})?)"
    r"|(?P<dmy>\d{1,2}\s" + _MON + r"(?:,?\s\d{4})?)"
)
_CUE = (
    r"(?:job )?posting end date|application (?:closing )?deadline(?: is)?|(?:application )?closing date"
    r"|deadline (?:for|to) (?:applications?|apply)(?: is)?"
    r"|applications? (?:will be )?(?:accepted|received) (?:\w+ ){0,3}until"
    r"|applications? (?:close|closes|closing)|(?:posting|competition) closes"
    r"|(?<=· )closes|apply (?:online )?(?:\S+ ){0,3}by|submit(?:ted)? (?:your application )?(?:\S+ ){0,4}by"
    r"|application window is expected to close on"
)
# Anything between the cue and the date: markdown, "on", a weekday, a time.
_GAP = (
    r"[\s*:#_>|.,-]*(?:on\s|by\s|until\s)?"
    r"(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s?)?"
    r"(?:\d{1,2}(?::\d{2})?\s?(?:am|pm|a\.m\.|p\.m\.)(?:\s\w+)?,?\s(?:on\s)?)?"
)
_DEADLINE = re.compile(r"(?i)(?<![\w-])(?<!internal )(?:" + _CUE + r")" + _GAP + r"(?:\*\*)?(?:" + _DATE + r")")


def _parse(m: re.Match[str], seen: date) -> date | None:
    try:
        if m["iso"]:
            y, mo, d = (int(x) for x in m["iso"].split("-"))
            return date(y, mo, d)
        if m["num"]:
            a, b, y = (int(x) for x in m["num"].split("/"))
            # 13/10/2026 is day first, 10/13/2026 month first. When both read as
            # a date, take the later one so a posting is never closed too early.
            options = [date(y, mo, d) for mo, d in ((a, b), (b, a)) if mo <= 12 and d <= 31 and _valid(y, mo, d)]
            return max(options) if options else None
        text = (m["mdy"] or m["dmy"]).lower().replace(",", " ").replace(".", " ")
        words = text.split()
        month = next(_MONTHS[w[:3]] for w in words if w[:3] in _MONTHS and not w[0].isdigit())
        nums = [int(re.sub(r"\D", "", w)) for w in words if w[0].isdigit()]
        day = nums[0]
        if len(nums) > 1:
            return date(nums[1], month, day)
        # No year: the first such date on or after the posting was seen (with a week's slack).
        found = date(seen.year, month, day)
        return found if found >= seen - timedelta(days=7) else date(seen.year + 1, month, day)
    except (ValueError, StopIteration, IndexError):
        return None


def _valid(y: int, mo: int, d: int) -> bool:
    try:
        date(y, mo, d)
        return True
    except ValueError:
        return False


def seen_date(first_seen: str | None) -> date | None:
    """The day a job was first seen, from its stored first_seen timestamp."""
    try:
        return date.fromisoformat((first_seen or "")[:10])
    except ValueError:
        return None


def deadline(description: str, seen: date | None = None) -> date | None:
    """The posting's application deadline, or None when it states none.
    `seen` (when the posting was first seen) supplies a year the text leaves out."""
    seen = seen or date.today()
    dates = [d for m in _DEADLINE.finditer(description or "") if (d := _parse(m, seen))]
    # A posting can repeat its deadline; if two differ, the later one is the safe read.
    return max(dates) if dates else None


@lru_cache(maxsize=8192)
def _scan(description: str, seen: date) -> tuple[bool, date | None]:
    """The slow part of closed_reason, remembered: the dashboard asks it for every job on every load."""
    return bool(_INTERNAL.search(description)), deadline(description, seen)


def due_date(description: str, seen: date | None = None) -> date | None:
    """deadline(), remembered: the dashboard shows it for every job on every load."""
    return _scan(description or "", seen or date.today())[1]


def closed_reason(description: str, today: date | None = None, seen: date | None = None) -> str | None:
    """Why the posting is closed ("Filled internally", "Closed Oct 15, 2026"), or None if open."""
    today = today or date.today()
    internal, end = _scan(description or "", seen or today)
    if internal:
        return "Filled internally"
    if end is not None and end < today:
        return f"Closed {end.strftime('%b')} {end.day}, {end.year}"
    return None
