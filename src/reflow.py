"""Give a posting flattened onto one line its lines back.

Some job boards (most Adzuna detail pages) hand over the description as one long line of plain
text with HTML entities left in: headings run into the sentence after them and " - " bullets sit
mid-line. That is hard to read on the details page and hides the "Basic Qualifications" /
"Preferred Qualifications" headings that src/posting_sections.py relies on. `reflow` decodes the
entities and puts known headings and dash bullets back on their own lines. Text that already has
line breaks is left alone.
"""

from __future__ import annotations

import html
import re

# Headings postings commonly use, in the case they're written in. Only matched where a capital
# letter follows, so "the requirements of the role" mid-sentence is left alone.
HEADINGS = (
    "Job Description", "Description", "About the job", "About the role", "About the team",
    "About the position", "About us", "About you", "Who we are", "Who you are", "The role",
    "The opportunity", "Overview", "Summary", "Key job responsibilities", "Key responsibilities",
    "Responsibilities", "Duties", "What you'll do", "What you will do", "What you’ll do",
    "A day in the life", "Requirements", "Qualifications", "Basic Qualifications",
    "Minimum Qualifications", "Required Qualifications", "Preferred Qualifications",
    "Nice to have", "Nice-to-have", "Bonus points", "Assets", "What we're looking for",
    "What we’re looking for", "What you'll bring", "What you bring", "What you’ll bring",
    "Skills and experience", "What we offer", "How to apply", "Working conditions",
)
# Everyday words that are only a heading when a colon says so ("Location: Vancouver").
COLON_HEADINGS = (
    "Experience", "Education", "Benefits", "Perks", "Compensation", "Salary", "Location",
    "Overview", "Summary", "Duties", "Assets",
)


def _alts(words) -> str:
    return "|".join(re.escape(h) for h in sorted(words, key=len, reverse=True))


# A heading starts the text or follows a space or sentence end, and is followed by a capital,
# digit or dash bullet.
_NEXT = r"\s+(?=[A-Z0-9\"“(]|[-*+•▪]\s+[A-Z0-9])"
_HEADING = re.compile(
    rf"(?:(?<=^)|(?<=[\s.!?]))(?:((?i:{_alts(HEADINGS)})):?|({_alts(COLON_HEADINGS)}):){_NEXT}"
)
# A bold line that opens a sentence ("market. **Your role and responsibilities** You're") is a
# heading; bold inside a sentence ("At **Quadient** , we") isn't.
_BOLD_HEADING = re.compile(
    r"(?:(?<=^)|(?<=[.!?:]\s))(\*\*[^*\n]{2,80}\*\*|\*[^*\n]{2,60}:\*)\s+(?=[A-Z0-9_*+\"“(-])"
)
# " - Build dashboards": a bullet run into the line. A capital or digit must follow, so a dash
# inside a sentence ("brands - customer obsession") stays.
_BULLET = re.compile(r"\s+[-*+•▪]\s+(?=[A-Z0-9\"“(]|\*\*)")


def _heading_line(m: re.Match) -> str:
    heading = m[1] or m[2]
    # "About the Team" matches "About the team", but a lowercase "requirements" is mid-sentence.
    return f"\n\n{heading}\n" if heading[0].isupper() else m[0]


def is_flat(text: str, min_chars: int = 800) -> bool:
    """A long description with (almost) no line breaks."""
    return len(text) >= min_chars and text.count("\n") < 3


_TAG = re.compile(r"<(?:p|div|br|ul|ol|li|h[1-6]|strong|b|span)\b[^>]*>", re.IGNORECASE)


def reflow(text: str) -> str:
    """Line breaks and decoded entities for a flattened description; anything else unchanged."""
    if not text or not is_flat(text):
        return text
    original = text
    if "&" in text:
        text = html.unescape(text)
    if _TAG.search(text):
        from src.parser import html_to_markdown

        return html_to_markdown(text).strip()
    text = _BOLD_HEADING.sub(lambda m: f"\n\n{m[1]}\n", text)
    text = _HEADING.sub(_heading_line, text)
    text = _BULLET.sub("\n- ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.split("\n")).strip()
    return original if text == original.strip() else text
