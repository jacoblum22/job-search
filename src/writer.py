"""Write job descriptions as markdown files with YAML frontmatter."""

from __future__ import annotations

import logging
from pathlib import Path

import frontmatter
from slugify import slugify

from src.parser import (
    extract_compensation,
    extract_department,
    extract_job_category,
    html_to_markdown,
)
from src.scraper import JobDetail
from src.tier import TierResult

logger = logging.getLogger(__name__)


def job_filename(job: JobDetail, tier_result: TierResult | None = None) -> str:
    """Generate a descriptive filename with tier prefix for alphabetical sorting.

    Format: {tier_prefix}-{job_req_id}-{slugified-title}.md
    Example: A-high-JR22878-junior-software-developer.md
    """
    slug = slugify(job.title, max_length=60)
    if tier_result:
        return f"{tier_result.tier.prefix}-{job.job_req_id}-{slug}.md"
    return f"{job.job_req_id}-{slug}.md"


def job_to_post(
    job: JobDetail, tier_result: TierResult | None = None
) -> frontmatter.Post:
    """Convert a JobDetail into a frontmatter Post (metadata + body)."""
    description_md = html_to_markdown(job.description_html)

    metadata = {
        "job_id": job.job_req_id,
        "title": job.title,
        "source": job.source or "",
        "location": job.location,
        "time_type": job.time_type,
        "date_posted": job.start_date,
        "date_scraped": _today(),
        "posting_end_date": job.end_date,
        "url": job.external_url,
        "status": "new",
    }

    # Add tier info if available
    if tier_result:
        metadata["tier"] = tier_result.tier.value
        metadata["tier_reason"] = tier_result.reason

    # Extract optional structured fields from the HTML
    department = extract_department(job.description_html)
    if department:
        metadata["department"] = department

    compensation = extract_compensation(job.description_html)
    if compensation:
        metadata["compensation"] = compensation

    category = extract_job_category(job.description_html)
    if category:
        metadata["job_category"] = category

    body = f"# {job.title}\n\n{description_md}"
    return frontmatter.Post(body, **metadata)


def write_job(
    job: JobDetail,
    output_dir: str | Path,
    tier_result: TierResult | None = None,
) -> Path:
    """Write a single job to a .md file. Returns the path written."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    filename = job_filename(job, tier_result)
    filepath = output_dir / filename

    post = job_to_post(job, tier_result)
    filepath.write_text(frontmatter.dumps(post), encoding="utf-8")

    logger.info("Wrote %s", filepath)
    return filepath


def is_already_scraped(job_req_id: str, output_dir: str | Path) -> bool:
    """Check if a job has already been scraped (file exists containing the ID).

    Handles both old format (JR12345-slug.md) and new format (A-high-JR12345-slug.md).
    """
    output_dir = Path(output_dir)
    if not output_dir.exists():
        return False
    return any(output_dir.glob(f"*{job_req_id}*.md"))


def _today() -> str:
    """Return today's date as an ISO-8601 string (YYYY-MM-DD)."""
    from datetime import date

    return date.today().isoformat()
