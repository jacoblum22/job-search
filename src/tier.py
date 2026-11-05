"""Tier classification system for job postings.

Classifies jobs into four tiers:
  - HIGH     (A): Strong match — tech, data, research with relevant skills
  - MID-HIGH (B): Good secondary fit — children/education, easy entry-level
  - MID      (C): Neutral — worth a quick glance
  - LOW      (D): Clearly wrong fit (too senior, wrong field, too far, etc.)

Tiers are determined by (in order):
  0. Location exclusion → LOW
  1. Experience requirements (>5 years) → LOW
  2. Title/category exclusion keywords → LOW
  3. Title match for priority keywords → HIGH
  4. Description match (≥2 skill keywords) → HIGH
  5. Title match for mid-high keywords → MID-HIGH
  6. Everything else → MID
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class Tier(Enum):
    """Job fit tier, from HIGH (best match) to LOW (wrong fit)."""

    HIGH = "high"
    MID_HIGH = "midhigh"
    MID = "mid"
    LOW = "low"

    @property
    def prefix(self) -> str:
        """Filename prefix for alphabetical sorting: A > B > C > D."""
        return {
            "high": "A-high",
            "midhigh": "B-midhigh",
            "mid": "C-mid",
            "low": "D-low",
        }[self.value]

    @property
    def icon(self) -> str:
        """ASCII-safe icon for CLI output (avoids cp1252 encoding issues)."""
        return {"high": "*", "midhigh": "+", "mid": "-", "low": "."}[self.value]


@dataclass
class TierResult:
    """The result of classifying a job."""

    tier: Tier
    reason: str


# ---------------------------------------------------------------------------
# Experience parsing
# ---------------------------------------------------------------------------

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


def parse_min_years_experience(text: str) -> int | None:
    """Extract the minimum years of experience required from description text.

    For ranges like "2-5 years", returns 2 (the minimum).
    For "5+ years" or "minimum 5 years", returns 5.
    Returns None if no experience requirement is found.
    """
    mins: list[int] = []

    # Check ranges first (they should take priority over single matches)
    for m in _RANGE_PATTERN.finditer(text):
        low = int(m.group(1))
        mins.append(low)

    # Remove range matches from text to avoid double-counting
    cleaned = _RANGE_PATTERN.sub("", text)

    for m in _SINGLE_PATTERN.finditer(cleaned):
        val = int(m.group(1))
        # Check if this was in a "more than X" or "over X" context
        full = m.group(0).lower()
        if "over" in full or "more than" in full:
            val += 1
        mins.append(val)

    for m in _WORD_PATTERN.finditer(cleaned):
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


# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------


def classify_job(
    *,
    title: str,
    description_text: str,
    location: str = "",
    job_category: str | None = None,
    experience_cutoff: int = 5,
    low_location_keywords: list[str] | None = None,
    low_title_keywords: list[str] | None = None,
    low_category_keywords: list[str] | None = None,
    low_description_keywords: list[str] | None = None,
    low_description_min_matches: int = 2,
    high_title_keywords: list[str] | None = None,
    high_description_keywords: list[str] | None = None,
    high_description_min_matches: int = 2,
    midhigh_title_keywords: list[str] | None = None,
) -> TierResult:
    """Classify a job posting into HIGH, MID-HIGH, MID, or LOW tier.

    Args:
        title: Job title
        description_text: Plain text of the job description (not HTML)
        location: Job location string from Workday
        job_category: Optional category string from Workday
        experience_cutoff: Jobs requiring MORE than this many years → LOW
        low_location_keywords: Location keywords that trigger LOW (too far)
        low_title_keywords: Keywords in title that trigger LOW
        low_category_keywords: Keywords in category that trigger LOW
        low_description_keywords: Bench-science/wrong-domain keywords → LOW
        low_description_min_matches: Min LOW description matches (default 2)
        high_title_keywords: Keywords in title that trigger HIGH
        high_description_keywords: Skills in description that trigger HIGH
        high_description_min_matches: Min description keyword matches for HIGH
        midhigh_title_keywords: Keywords in title that trigger MID-HIGH
    """
    low_loc_kw = low_location_keywords or []
    low_title_kw = low_title_keywords or []
    low_cat_kw = low_category_keywords or []
    low_desc_kw = low_description_keywords or []
    high_title_kw = high_title_keywords or []
    high_desc_kw = high_description_keywords or []
    midhigh_title_kw = midhigh_title_keywords or []

    title_lower = title.lower()
    desc_lower = description_text.lower()
    cat_lower = (job_category or "").lower()
    loc_lower = location.lower()

    # --- Step 0: Location check (too far from Vancouver) ---
    for kw in low_loc_kw:
        if kw.lower() in loc_lower:
            return TierResult(
                tier=Tier.LOW,
                reason=f"location too far: '{location}' matches '{kw}'",
            )

    # --- Step 1: Experience check ---
    min_years = parse_min_years_experience(description_text)
    if min_years is not None and min_years > experience_cutoff:
        return TierResult(
            tier=Tier.LOW,
            reason=f"requires {min_years}+ years experience (cutoff: >{experience_cutoff})",
        )

    # --- Step 2: Low-tier title/category exclusions ---
    for kw in low_title_kw:
        if _word_match(kw, title_lower):
            return TierResult(
                tier=Tier.LOW,
                reason=f"title matches low-tier keyword: {kw}",
            )

    for kw in low_cat_kw:
        if kw.lower() in cat_lower:
            return TierResult(
                tier=Tier.LOW,
                reason=f"category matches low-tier keyword: {kw}",
            )

    # --- Step 2.5: Low-tier description exclusions (bench science, etc.) ---
    # This runs BEFORE the HIGH check so wet-lab "Research Assistant" roles
    # get correctly demoted instead of promoted by title match.
    low_matched = [kw for kw in low_desc_kw if _word_match(kw, desc_lower)]
    if len(low_matched) >= low_description_min_matches:
        return TierResult(
            tier=Tier.LOW,
            reason=f"description matches {len(low_matched)} wrong-domain keywords: {', '.join(low_matched[:5])}",
        )

    # --- Step 3: High-tier title match (word boundary) ---
    for kw in high_title_kw:
        if _word_match(kw, title_lower):
            return TierResult(
                tier=Tier.HIGH,
                reason=f"title matches high-tier keyword: {kw}",
            )

    # --- Step 4: High-tier description keyword match (word boundary) ---
    matched_keywords = [kw for kw in high_desc_kw if _word_match(kw, desc_lower)]
    if len(matched_keywords) >= high_description_min_matches:
        return TierResult(
            tier=Tier.HIGH,
            reason=f"description matches {len(matched_keywords)} skill keywords: {', '.join(matched_keywords[:5])}",
        )

    # --- Step 5: Mid-high title match (children, education, easy roles) ---
    for kw in midhigh_title_kw:
        if _word_match(kw, title_lower):
            return TierResult(
                tier=Tier.MID_HIGH,
                reason=f"title matches mid-high keyword: {kw}",
            )

    # --- Step 6: Default to MID ---
    return TierResult(tier=Tier.MID, reason="no strong match or exclusion")


def _word_match(keyword: str, text: str) -> bool:
    """Check if keyword appears as a whole word/phrase in text (word-boundary match).

    Allows common suffixes (s, es, ed, ing) so "nanoparticle" matches
    "nanoparticles", "mammalian cell" matches "mammalian cells", etc.
    """
    pattern = r"\b" + re.escape(keyword.lower()) + r"(?:s|es|ed|ing)?\b"
    return bool(re.search(pattern, text, re.IGNORECASE))
