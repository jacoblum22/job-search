"""Parse Workday job HTML descriptions into clean structured markdown."""

from __future__ import annotations

import re

from markdownify import markdownify


def html_to_markdown(html: str) -> str:
    """Convert Workday's HTML job description to clean markdown.

    Workday descriptions are deeply nested HTML with lots of empty tags,
    inline styles, and presentational markup.  This function:
      1. Converts HTML → markdown via markdownify
      2. Strips excessive blank lines
      3. Cleans up artifacts (empty headings, stray whitespace)
    """
    md = markdownify(html, heading_style="ATX", strip=["img", "script", "style"])

    # Collapse 3+ consecutive blank lines into 2
    md = re.sub(r"\n{3,}", "\n\n", md)

    # Remove headings that are empty (just "##" with no text)
    md = re.sub(r"^#{1,6}\s*$", "", md, flags=re.MULTILINE)

    # Remove lines that are only whitespace
    md = re.sub(r"^[ \t]+$", "", md, flags=re.MULTILINE)

    # Collapse again after cleanup
    md = re.sub(r"\n{3,}", "\n\n", md)

    return md.strip()


def extract_compensation(html: str) -> str | None:
    """Try to pull out a compensation range from the description HTML."""
    # Workday often has: <h2><b>Compensation Range</b></h2>$X - $Y CAD Monthly
    match = re.search(
        r"Compensation Range</b></h2>\s*(.+?)(?:<|$)",
        html,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return None


def extract_department(html: str) -> str | None:
    """Try to pull out the department from the description HTML."""
    match = re.search(
        r"Department</b></h2>\s*(.+?)(?:<|$)",
        html,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return None


def extract_job_category(html: str) -> str | None:
    """Try to pull out the job category from the description HTML."""
    match = re.search(
        r"Job Category</b></h2>\s*(.+?)(?:<|$)",
        html,
        re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    return None
