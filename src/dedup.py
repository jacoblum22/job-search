"""Cross-source dedup pass.

The same real-world posting often shows up on multiple sources (or even
twice within one source — CareerJet returned the same "Teck Resources -
Data Scientist III" posting under two different tracking URLs in testing).
This groups matching jobs under a shared `dedup_group_id` instead of
creating duplicate rows in the dashboard.

Matching is a compound rapidfuzz score over normalized (title, company,
location) rather than a single blended string — company and location need
to be a strong match on their own; title match alone (or a blend that lets
shared location words like "Vancouver, BC" inflate the score) isn't enough.
"""

from __future__ import annotations

import logging
import sqlite3

from rapidfuzz import fuzz

from src.db import jobs_for_dedup, normalize, set_dedup_group

logger = logging.getLogger(__name__)

COMPANY_THRESHOLD = 85
LOCATION_THRESHOLD = 80
TITLE_THRESHOLD = 85


def _is_match(a: sqlite3.Row, b: sqlite3.Row) -> bool:
    company_score = fuzz.ratio(normalize(a["company"]), normalize(b["company"]))
    if company_score < COMPANY_THRESHOLD:
        return False

    # token_set_ratio, not ratio: locations are often phrased at different
    # granularity across sources ("Vancouver, BC" vs "Greater Vancouver,
    # British Columbia" for the same posting) — plain ratio penalizes the
    # length difference too harshly and misses real matches.
    location_score = fuzz.token_set_ratio(normalize(a["location"]), normalize(b["location"]))
    if location_score < LOCATION_THRESHOLD:
        return False

    title_score = fuzz.token_sort_ratio(normalize(a["title"]), normalize(b["title"]))
    return title_score >= TITLE_THRESHOLD


def run_dedup(conn: sqlite3.Connection, since_days: int = 45) -> int:
    """Merge matching jobs (first seen within `since_days`) into shared dedup groups.

    Returns the number of jobs whose dedup_group_id was changed.
    """
    candidates = jobs_for_dedup(conn, since_days=since_days)

    # One representative row per known cluster, keyed by that cluster's dedup_group_id.
    representatives: list[sqlite3.Row] = []
    merged_count = 0

    for job in candidates:
        match = next((rep for rep in representatives if _is_match(job, rep)), None)

        if match is None:
            representatives.append(job)
            continue

        if job["dedup_group_id"] != match["dedup_group_id"]:
            set_dedup_group(conn, job["id"], match["dedup_group_id"])
            logger.info(
                "Dedup: merged %s [%s] into group of %s [%s]",
                job["title"],
                job["source"],
                match["title"],
                match["source"],
            )
            merged_count += 1

    conn.commit()
    logger.info("Dedup: merged %d job(s) across %d candidate(s)", merged_count, len(candidates))
    return merged_count
