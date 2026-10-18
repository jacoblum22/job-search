"""Parse the minimum years of experience a job posting asks for.

Used by ingest (src/db.py) to drop senior roles and by src/score.py for the
years penalty.
"""

from __future__ import annotations

import re

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

# Matches: "2-5 years", "2 to 5 years", "2–5 years"
_RANGE_PATTERN = re.compile(
    r"(\d+)\s*[-–to]+\s*(\d+)\s*(?:\+\s*)?year" + _NOT_AGE + r"s?",
    re.IGNORECASE,
)

# Matches: "5+ years", "5 years", "minimum 5 years", "at least 5 years"
_SINGLE_PATTERN = re.compile(
    r"(?:minimum|at\s+least|over|more\s+than)?\s*(\d+)\s*\+?\s*year" + _NOT_AGE + r"s?",
    re.IGNORECASE,
)

# Matches word-form: "five years", "three+ years"
_WORD_PATTERN = re.compile(
    r"(?:minimum|at\s+least|over|more\s+than)?\s*("
    + "|".join(_WORD_TO_NUM.keys())
    + r")\s*\+?\s*year" + _NOT_AGE + r"s?",
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


def _has_experience_context(haystack: str, start: int, end: int) -> bool:
    window = haystack[max(0, start - _CONTEXT_WINDOW) : end + _CONTEXT_WINDOW]
    return bool(_EXPERIENCE_CONTEXT.search(window))


def parse_min_years_experience(text: str) -> int | None:
    """Extract the minimum years of experience required from description text.

    For ranges like "2-5 years", returns 2 (the minimum).
    For "5+ years" or "minimum 5 years", returns 5.
    Returns None if no experience requirement is found.

    Requires the word "experience" to appear near the match — a bare "35
    years" elsewhere in the text (company history, warranties, etc.) is not
    treated as an experience requirement.
    """
    mins: list[int] = []

    # Check ranges first (they should take priority over single matches)
    for m in _RANGE_PATTERN.finditer(text):
        if _has_experience_context(text, m.start(), m.end()):
            mins.append(int(m.group(1)))

    # Remove range matches from text to avoid double-counting
    cleaned = _RANGE_PATTERN.sub("", text)

    for m in _SINGLE_PATTERN.finditer(cleaned):
        if not _has_experience_context(cleaned, m.start(), m.end()):
            continue
        val = int(m.group(1))
        # Check if this was in a "more than X" or "over X" context
        full = m.group(0).lower()
        if "over" in full or "more than" in full:
            val += 1
        mins.append(val)

    for m in _WORD_PATTERN.finditer(cleaned):
        if not _has_experience_context(cleaned, m.start(), m.end()):
            continue
        word = m.group(1).lower()
        val = _WORD_TO_NUM.get(word)
        if val is not None:
            mins.append(val)

    if not mins:
        return None

    # Return the maximum minimum found (the strictest stated requirement)
    # This avoids false positives from things like "1 year warranty" when
    # the actual requirement is "5 years experience"
    return max(mins)
