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

import json
import re
from datetime import date, datetime, timedelta, timezone
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
    r"|applications? (?:\w+ ){0,5}?(?:accepted|received) (?:\w+ ){0,3}until"
    r"|applications? (?:close|closes|closing)|(?:posting|competition) closes"
    r"|(?<=· )closes|apply (?:online )?(?:\S+ ){0,3}(?:by|before)|submit(?:ted)? (?:your application )?(?:\S+ ){0,4}by"
    r"|application window (?:is )?expected to close(?: on)?|open until filled \(expires"
    r"|advertised until|accepting applications (?:now )?through(?: end of day)?(?: on)?"
)
# Anything between the cue and the date: markdown, "on", a weekday, a time.
_GAP = (
    r"[\s*:#_>|.,-]*(?:on\s|by\s|until\s)?"
    r"(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day,?\s?)?"
    r"(?:\d{1,2}(?::\d{2})?\s?(?:am|pm|a\.m\.|p\.m\.)(?:\s\w+)?,?\s(?:on\s)?)?"
)
# A cue starts a word, or a capitalised word glued to the one before it ("Full timeClosing Date")
# when a page's layout was flattened.
_DEADLINE = re.compile(r"(?i)(?:(?<![\w-])|(?<=[a-z])(?-i:(?=[A-Z])))(?<!internal )(?:" + _CUE + r")" + _GAP + r"(?:\*\*)?(?:" + _DATE + r")")


# A date written before its cue: "November 30, 2026 – Application Window Closes".
_DATE_FIRST = re.compile(r"(?i)(?:" + _DATE + r")[\s*\u00a0]*[–—-][\s\u00a0]*application (?:window|period) closes")
# "Our application deadline is 40 days from the date of posting."
_RELATIVE = re.compile(r"(?i)\bdeadline(?: is)? (\d{1,3}) days from (?:the )?(?:date of )?posting")


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
    # Counted from the day it was first seen, which is on or after the posting day,
    # so a posting is never closed too early.
    dates += [seen + timedelta(days=int(m[1])) for m in _RELATIVE.finditer(description or "")]
    dates += [d for m in _DATE_FIRST.finditer(description or "") if (d := _parse(m, seen))]
    # A posting can repeat its deadline; if two differ, the later one is the safe read.
    return max(dates) if dates else None


@lru_cache(maxsize=8192)
def _scan(description: str, seen: date) -> tuple[bool, date | None]:
    """The slow part of closed_reason, remembered: the dashboard asks it for every job on every load."""
    return bool(_INTERNAL.search(description)), deadline(description, seen)


_PACIFIC = timezone(timedelta(hours=-8))
# Closing dates some job sites send as data rather than in the posting text.
_RAW_KEYS = (
    ("jobPostingInfo", "endDate"),   # Workday
    ("postingExpiryTimestampUTC",),  # Dayforce
    ("validThrough",),               # schema.org JobPosting (iCIMS and other JSON-LD pages)
    ("closes",),                     # BC Public Service
    ("expiryDate",),                 # Himalayas
)


@lru_cache(maxsize=8192)
def raw_deadline(raw: str | None) -> date | None:
    """The closing date in a job's stored source data (`jobs.raw`), or None."""
    try:
        data = json.loads(raw or "null")
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    for path in _RAW_KEYS:
        value: object = data
        for key in path:
            value = value.get(key) if isinstance(value, dict) else None
        if isinstance(value, (int, float)) and value > 0:
            # A Unix time, in seconds or milliseconds.
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value, timezone.utc).date()
        if isinstance(value, str) and value.strip():
            try:
                stamp = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                continue
            if stamp.tzinfo is not None and stamp.time() != datetime.min.time():
                # Read a closing time on Pacific time: "2026-10-31T03:59:00+00:00" is Oct 30.
                stamp = stamp.astimezone(_PACIFIC)
            return stamp.date()
    return None


def due_date(description: str, seen: date | None = None, raw: str | None = None) -> date | None:
    """The posting's deadline from its text or its source data, remembered: the dashboard
    shows it for every job on every load. The later date wins if the two differ."""
    dates = [d for d in (_scan(description or "", seen or date.today())[1], raw_deadline(raw)) if d]
    return max(dates) if dates else None


def closed_reason(description: str, today: date | None = None, seen: date | None = None,
                  raw: str | None = None) -> str | None:
    """Why the posting is closed ("Filled internally", "Closed Oct 15, 2026"), or None if open."""
    today = today or date.today()
    internal = _scan(description or "", seen or today)[0]
    end = due_date(description, seen or today, raw)
    if internal:
        return "Filled internally"
    if end is not None and end < today:
        return f"Closed {end.strftime('%b')} {end.day}, {end.year}"
    return None
