"""Parse the minimum years of experience a job posting asks for.

Used by ingest (src/db.py) to drop senior roles and by src/score.py for the
years penalty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Patterns like "5+ years", "5 years", "five years"
_WORD_TO_NUM = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}

# Negative lookahead: skip "years of age", "years old", "years or older", etc.
_NOT_AGE = r"(?!s?\s+(?:of\s+age|old|young|or\s+older))"

# "years", "year", or the "yrs"/"yr." abbreviation ("At least 5 yrs of professional experience").
_YEAR = r"(?:year|yr)" + _NOT_AGE + r"s?\b\.?"
# "5+", "5 plus", "three-plus"
_PLUS = r"\s*(?:\+|-?\s*plus\b)?\s*"

# Matches: "2-5 years", "2 to 5 years", "2–5 years"
_RANGE_PATTERN = re.compile(
    r"(\d+)\s*[-–to]+\s*(\d+)" + _PLUS + _YEAR,
    re.IGNORECASE,
)

# Matches: "5+ years", "5 years", "minimum 5 years", "at least 5 years"
_SINGLE_PATTERN = re.compile(
    r"(?:minimum|at\s+least|over|more\s+than)?\s*(\d+)" + _PLUS + _YEAR,
    re.IGNORECASE,
)

# Matches word-form: "five years", "three+ years"
_WORD_PATTERN = re.compile(
    r"(?:minimum|at\s+least|over|more\s+than)?\s*\b("
    + "|".join(_WORD_TO_NUM.keys())
    + r")" + _PLUS + _YEAR,
    re.IGNORECASE,
)

# Degree-conditional requirements often drop the unit on the second number: "3+ years of
# experience with a graduate degree, or 5+ with a bachelor's". The "or 5+ with a bachelor's"
# half is still a years requirement, and it's the one that applies to a bachelor's holder.
_DEGREE = (
    r"(?:bachelor|undergrad|master|graduate|post-?graduate|ph\.?\s?d|doctor|"
    r"b\.?\s?sc?\b|m\.?\s?sc?\b|b\.?a\b|m\.?a\b|mba\b|(?:university\s+|college\s+)?degree|diploma)"
)
_ELLIPTIC_PATTERN = re.compile(
    r"(?:\bor\s+|\(\s*|;\s*|,\s*)(\d+|" + "|".join(_WORD_TO_NUM.keys()) + r")" + _PLUS
    + r"(?:with|for|if\s+you\s+have)\s+"
    + r"(?:(?:candidates|applicants|those|people)\s+(?:with|holding|who\s+have)\s+)?(?:an?\s+|the\s+)?(?:relevant\s+|related\s+)?" + _DEGREE,
    re.IGNORECASE,
)

# A bare "X years" is ambiguous — company history ("35 years in business"),
# warranties, product ages, etc. all match it too. Require the word
# "experience" somewhere nearby before trusting it as a job requirement.
_EXPERIENCE_CONTEXT = re.compile(r"experience", re.IGNORECASE)
# Wide enough for "3+ years of non-internship professional software
# development experience" (66 chars between the number and "experience"),
# narrow enough to not reach into an unrelated neighboring sentence.
_CONTEXT_WINDOW = 80  # characters


# A requirement line that never says "experience": "- 5+ years in P&C insurance analytics",
# "3+ years working with SQL". It must open a list item, or carry a "+", and be followed by
# what the years were spent on; company history ("35 years in business") isn't.
_LINE_START = re.compile(r"(?:^|\n)[ \t]*(?:[-*•+▪◦·]|\d+[.)])?[ \t]*(?:minimum(?:\s+of)?|at\s+least)?\s*$", re.IGNORECASE)
_SPENT_ON = re.compile(
    r"\s+(?:of|in|as|working|doing|building|developing|leading|with|using|hands-on|professional|relevant)\b"
    r"(?!\s+(?:business|operation|history|the\s+(?:industry|market|community)|service"
    r"|post-?secondary|university|college|school|study|studies|education|age\b))",
    re.IGNORECASE,
)


def _has_experience_context(haystack: str, start: int, end: int) -> bool:
    window = haystack[max(0, start - _CONTEXT_WINDOW) : end + _CONTEXT_WINDOW]
    if _EXPERIENCE_CONTEXT.search(window):
        return True
    if not _SPENT_ON.match(haystack, end):
        return False
    lead = haystack[max(0, start - 40):start]
    return "+" in haystack[start:end] or bool(_LINE_START.search(lead))


def _year_asks(text: str) -> list[tuple[int, int]]:
    """Every years-of-experience ask in `text`, as (years, position)."""
    asks: list[tuple[int, int]] = []

    # Check ranges first (they should take priority over single matches)
    for m in _RANGE_PATTERN.finditer(text):
        if _has_experience_context(text, m.start(), m.end()):
            asks.append((int(m.group(1)), m.start()))

    # Blank out range matches to avoid double-counting (same length, so positions still line up)
    cleaned = _RANGE_PATTERN.sub(lambda m: " " * len(m.group(0)), text)

    for m in _SINGLE_PATTERN.finditer(cleaned):
        if not _has_experience_context(cleaned, m.start(), m.end()):
            continue
        val = int(m.group(1))
        # Check if this was in a "more than X" or "over X" context
        full = m.group(0).lower()
        if "over" in full or "more than" in full:
            val += 1
        asks.append((val, m.start(1)))

    for m in _WORD_PATTERN.finditer(cleaned):
        if not _has_experience_context(cleaned, m.start(), m.end()):
            continue
        val = _WORD_TO_NUM.get(m.group(1).lower())
        if val is not None:
            asks.append((val, m.start(1)))

    # "or 5+ with a bachelor's": the unit is implied by a years requirement just before it.
    for m in _ELLIPTIC_PATTERN.finditer(text):
        lead = text[max(0, m.start() - 200) : m.start()]
        if not re.search(r"(?:year|yr)s?\b", lead, re.IGNORECASE):
            continue
        if not _EXPERIENCE_CONTEXT.search(text[max(0, m.start() - 200) : m.end() + _CONTEXT_WINDOW]):
            continue
        num = m.group(1).lower()
        asks.append((int(num) if num.isdigit() else _WORD_TO_NUM[num], m.start(1)))
    return asks


def parse_min_years_experience(text: str) -> int | None:
    """Extract the minimum years of experience required from description text.

    For ranges like "2-5 years", returns 2 (the minimum).
    For "5+ years" or "minimum 5 years", returns 5.
    Returns None if no experience requirement is found.

    Requires the word "experience" to appear near the match — a bare "35
    years" elsewhere in the text (company history, warranties, etc.) is not
    treated as an experience requirement.
    """
    asks = _year_asks(text)
    # Return the maximum minimum found (the strictest stated requirement)
    # This avoids false positives from things like "1 year warranty" when
    # the actual requirement is "5 years experience"
    return max(v for v, _ in asks) if asks else None


@dataclass(frozen=True)
class YearsAsk:
    """Years a posting asks for, split by whether it requires them or only prefers them."""

    required: int | None  # strictest ask outside nice-to-have parts
    preferred: int | None  # strictest ask under "Preferred"/"Assets" or with a cue ("an asset")


def _is_preferred(sections, pos: int) -> bool:
    """Under a nice-to-have heading, or with a cue in the same part of the line: in
    "5+ years as a Systems Analyst; 4+ years of testing preferred" only the 4 is preferred,
    and "5+ years in analytics, ideally within SaaS" prefers SaaS, not the years."""
    from src.posting_sections import _CUE

    if sections.kind(pos) != "preferred":
        return False
    text = sections.text
    a = max(text.rfind(";", 0, pos), text.rfind("\n", 0, pos)) + 1
    ends = [i for i in (text.find(";", pos), text.find("\n", pos)) if i >= 0]
    b = min(ends) if ends else len(text)
    # The cue sits before the years ("Preferred: ... 6+ years") or in the same comma-part;
    # "5+ years in analytics, ideally within SaaS" prefers SaaS, not the years.
    comma = text.find(",", pos, b)
    if _CUE.search(text[a : b if comma < 0 else comma]):
        return True
    heading = "other"
    for start, kind in sections.marks:
        if start > pos:
            break
        if kind != "unknown":
            heading = kind
    return heading == "preferred"


def parse_years_ask(text: str) -> YearsAsk:
    """Like parse_min_years_experience, but a nice-to-have ask ("2+ years of SQL is an
    asset", a "Preferred Qualifications" list) is kept apart from a required one."""
    from src.posting_sections import Sections, to_markdown

    md = to_markdown(text)
    asks = _year_asks(md)
    if not asks:
        return YearsAsk(None, None)
    sections = Sections(md)
    pref_at = [_is_preferred(sections, pos) for _, pos in asks]
    req = [v for (v, _), p in zip(asks, pref_at) if not p]
    pref = [v for (v, _), p in zip(asks, pref_at) if p]
    return YearsAsk(max(req) if req else None, max(pref) if pref else None)
