"""CLI entry point for the UBC job scraper.

Uses async concurrency (5 simultaneous requests) for speed,
with automatic retry on rate-limit errors.
"""

from __future__ import annotations

import asyncio
import logging
from collections import Counter
from pathlib import Path

import click
import yaml

from src.parser import extract_job_category, html_to_markdown
from src.scraper import AsyncWorkdayScraper, JobDetail
from src.tier import Tier, classify_job
from src.writer import is_already_scraped, write_job

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "settings.yaml"


def load_config(path: Path) -> dict:
    """Load settings.yaml and return the parsed dict."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def classify_and_write(
    detail: JobDetail,
    tier_cfg: dict,
    output_dir: Path,
    *,
    dry_run: bool = False,
) -> tuple[str, str, str]:
    """Classify a job and optionally write to disk.

    Returns (tier_value, reason, filename_or_empty).
    """
    description_text = html_to_markdown(detail.description_html)
    job_category = extract_job_category(detail.description_html)
    tier_result = classify_job(
        title=detail.title,
        description_text=description_text,
        location=detail.location,
        job_category=job_category,
        experience_cutoff=tier_cfg.get("experience_cutoff", 5),
        low_location_keywords=tier_cfg.get("low_location_keywords", []),
        low_title_keywords=tier_cfg.get("low_title_keywords", []),
        low_category_keywords=tier_cfg.get("low_category_keywords", []),
        low_description_keywords=tier_cfg.get("low_description_keywords", []),
        low_description_min_matches=tier_cfg.get("low_description_min_matches", 2),
        high_title_keywords=tier_cfg.get("high_title_keywords", []),
        high_description_keywords=tier_cfg.get("high_description_keywords", []),
        high_description_min_matches=tier_cfg.get("high_description_min_matches", 2),
        midhigh_title_keywords=tier_cfg.get("midhigh_title_keywords", []),
    )

    filename = ""
    if not dry_run:
        path = write_job(detail, output_dir, tier_result)
        filename = path.name

    return tier_result.tier.value, tier_result.reason, filename


async def run_scraper(
    cfg: dict,
    *,
    limit: int,
    dry_run: bool,
    concurrency: int,
) -> None:
    """Main async scraping workflow."""
    log = logging.getLogger("scrape")

    output_cfg = cfg.get("output", {})
    tier_cfg = cfg.get("tier", {})
    max_jobs = limit or cfg.get("scraper", {}).get("max_jobs", 0)

    output_dir = PROJECT_ROOT / output_cfg.get(
        "job_descriptions_dir", "job_descriptions"
    )

    log.info("Output directory: %s", output_dir)
    log.info("Concurrency: %d", concurrency)
    if max_jobs:
        log.info("Max jobs: %d", max_jobs)

    async with AsyncWorkdayScraper(
        concurrency=concurrency, max_jobs=max_jobs
    ) as scraper:
        # Step 1: Get all job summaries
        log.info("Fetching job listings...")
        summaries = await scraper.list_all_jobs()
        log.info("Found %d jobs on the board", len(summaries))

        # Step 2: Filter out already-scraped jobs
        new_jobs = [
            s for s in summaries if not is_already_scraped(s.job_req_id, output_dir)
        ]
        skipped = len(summaries) - len(new_jobs)
        if skipped:
            log.info("Skipping %d already-scraped jobs", skipped)
        log.info("New jobs to scrape: %d", len(new_jobs))

        if not new_jobs:
            log.info("Nothing new to scrape. Done!")
            return

        # Step 3: Fetch all details concurrently
        log.info("Fetching job details (%d concurrent)...", concurrency)
        results = await scraper.get_job_details_batch(new_jobs)

        # Step 4: Classify and write
        written = 0
        errors = 0
        tier_counts: Counter[Tier] = Counter()

        for summary, detail_or_err in results:
            if isinstance(detail_or_err, Exception):
                log.error(
                    "✗ %s: %s — %s",
                    summary.job_req_id,
                    summary.title,
                    detail_or_err,
                )
                errors += 1
                continue

            detail = detail_or_err
            tier_val, reason, filename = classify_and_write(
                detail, tier_cfg, output_dir, dry_run=dry_run
            )
            tier_counts[Tier(tier_val)] += 1

            if dry_run:
                tier_obj = Tier(tier_val)
                click.echo(
                    f"  {tier_obj.icon} [{tier_val.upper():7s}] "
                    f"{summary.job_req_id}: {summary.title} ({detail.location})"
                )
                click.echo(f"         reason: {reason}")
            else:
                log.info(
                    "  → %s [%s: %s]",
                    filename,
                    tier_val.upper(),
                    reason,
                )
                written += 1

        # Summary
        log.info("─" * 50)
        if dry_run:
            log.info("DRY RUN complete.")
        else:
            log.info("Wrote %d jobs, %d errors", written, errors)
        log.info(
            "Tiers: HIGH=%d  MID-HIGH=%d  MID=%d  LOW=%d",
            tier_counts.get(Tier.HIGH, 0),
            tier_counts.get(Tier.MID_HIGH, 0),
            tier_counts.get(Tier.MID, 0),
            tier_counts.get(Tier.LOW, 0),
        )


@click.command()
@click.option(
    "--config",
    "config_path",
    type=click.Path(exists=True, path_type=Path),
    default=DEFAULT_CONFIG,
    help="Path to settings.yaml",
)
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
@click.option("--dry-run", is_flag=True, help="List jobs but don't write files")
@click.option("--limit", type=int, default=0, help="Max jobs to scrape (0 = all)")
@click.option(
    "--concurrency",
    type=int,
    default=5,
    help="Number of concurrent requests (default: 5)",
)
def main(
    config_path: Path,
    verbose: bool,
    dry_run: bool,
    limit: int,
    concurrency: int,
) -> None:
    """Scrape UBC Workday job board and save descriptions as markdown."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = load_config(config_path)
    asyncio.run(run_scraper(cfg, limit=limit, dry_run=dry_run, concurrency=concurrency))


if __name__ == "__main__":
    main()
