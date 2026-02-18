"""CLI entry point for the job scraper.

Scrapes one or more Workday job boards (configured in settings.yaml),
classifies each posting into fit tiers, and saves structured markdown files.
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


async def _scrape_source(
    source: dict,
    *,
    tier_cfg: dict,
    output_dir: Path,
    max_jobs: int,
    dry_run: bool,
    concurrency: int,
) -> tuple[int, int, Counter[Tier]]:
    """Scrape a single Workday source. Returns (written, errors, tier_counts)."""
    log = logging.getLogger("scrape")
    name = source["name"]
    location_filter = source.get("location_filter", "").lower()

    log.info("━━━ %s ━━━", name)

    async with AsyncWorkdayScraper(
        tenant=source["tenant"],
        site=source["site"],
        wd=source.get("wd", "wd10"),
        source_name=name,
        concurrency=concurrency,
        max_jobs=max_jobs,
    ) as scraper:
        # Step 1: Get all job summaries
        summaries = await scraper.list_all_jobs()

        # Step 2: Filter out already-scraped jobs
        new_jobs = [
            s for s in summaries if not is_already_scraped(s.job_req_id, output_dir)
        ]
        skipped = len(summaries) - len(new_jobs)
        if skipped:
            log.info("%s: skipping %d already-scraped jobs", name, skipped)
        log.info("%s: %d new jobs to scrape", name, len(new_jobs))

        if not new_jobs:
            return 0, 0, Counter()

        # Step 3: Fetch all details concurrently
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

            # Optional location filter (e.g. only Vancouver jobs from global boards)
            if location_filter and location_filter not in detail.location.lower():
                log.debug(
                    "  ⊘ %s: skipped (location '%s' doesn't match filter '%s')",
                    summary.job_req_id,
                    detail.location,
                    source.get("location_filter", ""),
                )
                continue

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
                click.echo(f"         source: {name}  reason: {reason}")
            else:
                log.info(
                    "  → %s [%s: %s]",
                    filename,
                    tier_val.upper(),
                    reason,
                )
                written += 1

    return written, errors, tier_counts


async def run_scraper(
    cfg: dict,
    *,
    limit: int,
    dry_run: bool,
    concurrency: int,
    source_filter: str,
) -> None:
    """Main async scraping workflow — iterates over all enabled sources."""
    log = logging.getLogger("scrape")

    output_cfg = cfg.get("output", {})
    tier_cfg = cfg.get("tier", {})
    max_jobs = limit or cfg.get("scraper", {}).get("max_jobs", 0)
    sources = cfg.get("sources", [])

    output_dir = PROJECT_ROOT / output_cfg.get(
        "job_descriptions_dir", "job_descriptions"
    )

    # Filter to enabled sources (and optionally by name)
    active = [s for s in sources if s.get("enabled", True)]
    if source_filter:
        active = [s for s in active if source_filter.lower() in s["name"].lower()]

    if not active:
        log.warning("No matching enabled sources found.")
        return

    log.info("Output directory: %s", output_dir)
    log.info("Sources: %s", ", ".join(s["name"] for s in active))
    if max_jobs:
        log.info("Max jobs per source: %d", max_jobs)

    # Scrape all sources in parallel (each is a different server)
    source_results = await asyncio.gather(
        *[
            _scrape_source(
                source,
                tier_cfg=tier_cfg,
                output_dir=output_dir,
                max_jobs=max_jobs,
                dry_run=dry_run,
                concurrency=concurrency,
            )
            for source in active
        ]
    )

    total_written = 0
    total_errors = 0
    total_tiers: Counter[Tier] = Counter()
    for written, errors, tier_counts in source_results:
        total_written += written
        total_errors += errors
        total_tiers += tier_counts

    # Summary
    log.info("═" * 50)
    if dry_run:
        log.info("DRY RUN complete (%d sources).", len(active))
    else:
        log.info(
            "Done: %d jobs written, %d errors across %d source(s)",
            total_written,
            total_errors,
            len(active),
        )
    log.info(
        "Tiers: HIGH=%d  MID-HIGH=%d  MID=%d  LOW=%d",
        total_tiers.get(Tier.HIGH, 0),
        total_tiers.get(Tier.MID_HIGH, 0),
        total_tiers.get(Tier.MID, 0),
        total_tiers.get(Tier.LOW, 0),
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
@click.option("--limit", type=int, default=0, help="Max jobs per source (0 = all)")
@click.option(
    "--concurrency",
    type=int,
    default=10,
    help="Number of concurrent requests per source (default: 10)",
)
@click.option(
    "--source",
    "source_filter",
    default="",
    help="Only scrape sources whose name contains this string",
)
def main(
    config_path: Path,
    verbose: bool,
    dry_run: bool,
    limit: int,
    concurrency: int,
    source_filter: str,
) -> None:
    """Scrape Workday job boards and save descriptions as markdown."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    cfg = load_config(config_path)
    asyncio.run(
        run_scraper(
            cfg,
            limit=limit,
            dry_run=dry_run,
            concurrency=concurrency,
            source_filter=source_filter,
        )
    )


if __name__ == "__main__":
    main()
