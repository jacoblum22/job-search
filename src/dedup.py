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
import re
import sqlite3

from rapidfuzz import fuzz

from src.db import jobs_for_dedup, normalize, set_dedup_group, set_dedup_groups

logger = logging.getLogger(__name__)

COMPANY_THRESHOLD = 85
LOCATION_THRESHOLD = 80
TITLE_THRESHOLD = 85
DESCRIPTION_THRESHOLD = 95
# Two company names that differ only by a suffix word ("Pacific Reach" / "Pacific Reach Properties")
# are the same company, but big employers post many roles under one title (Apple, Amazon), so the
# text has to agree too.
SUFFIX_DESCRIPTION_THRESHOLD = 60
_COMPANY_SUFFIXES = {"inc", "ltd", "limited", "corp", "corporation", "llc", "company", "solutions", "properties",
                     "group", "technologies", "services", "canada"}
# Short descriptions (email-alert snippets) are too generic to prove two
# postings are the same job.
MIN_DESCRIPTION_CHARS = 300


# Seniority words. "Junior Software Engineer - Remote (Global), Full-Time" and "Software Engineer -
# Remote (Global), Full-Time" score 93 on the fuzzy title match, but they are different jobs, so
# two titles whose level words differ are never the same posting.
_LEVEL_WORDS = {"junior", "jr", "senior", "sr", "lead", "staff", "principal", "intern", "internship",
                "i", "ii", "iii", "iv", "v"}


_LEVEL_ALIASES = {"jr": "junior", "sr": "senior", "internship": "intern"}


def level_words(title: str | None) -> frozenset[str]:
    """The seniority words in a title ("Data Analyst II" -> {"ii"}; "Sr." -> {"sr"})."""
    words = (_LEVEL_ALIASES.get(w, w) for w in re.findall(r"[a-z]+", normalize(title or "")))
    return frozenset(w for w in words if w in _LEVEL_WORDS)


def _core_company(name: str | None) -> str:
    """The company name without punctuation or suffix words, for the suffix-only comparison."""
    words = re.sub(r"[^\w]+", " ", normalize(name or "")).split()
    core = [w for w in words if w not in _COMPANY_SUFFIXES]
    return " ".join(core or words)


def _plain_location(loc: str | None) -> str:
    """Location without punctuation, so "Vancouver, BC (On-site)" compares with "Vancouver"."""
    return re.sub(r"[^\w]+", " ", normalize(loc or "")).strip()


def _is_match(a: sqlite3.Row, b: sqlite3.Row) -> bool:
    if level_words(a["title"]) != level_words(b["title"]):
        return False
    title_score = fuzz.token_sort_ratio(normalize(a["title"]), normalize(b["title"]))
    if title_score < TITLE_THRESHOLD:
        return False

    company_score = fuzz.ratio(normalize(a["company"]), normalize(b["company"]))
    if company_score < COMPANY_THRESHOLD and _core_company(a["company"]) == _core_company(b["company"]):
        # Same company under a longer or shorter legal name. Needs the text to agree because the same
        # employer often posts different roles with one title.
        da, db_ = normalize(a["description"] or ""), normalize(b["description"] or "")
        if len(da) < MIN_DESCRIPTION_CHARS or len(db_) < MIN_DESCRIPTION_CHARS:
            return False
        if fuzz.ratio(da[:3000], db_[:3000]) < SUFFIX_DESCRIPTION_THRESHOLD:
            return False
    elif company_score < COMPANY_THRESHOLD:
        # One posting is often listed under a subsidiary's or parent's name on one
        # source and the brand on another ("Autodata Solutions Company" on Adzuna,
        # "J.D. Power" on Wellfound, same text). Same title and description is the
        # same job whatever the company field says.
        return _same_description(a["description"], b["description"])

    # token_set_ratio, not ratio: locations are often phrased at different
    # granularity across sources ("Vancouver, BC" vs "Greater Vancouver,
    # British Columbia" for the same posting) — plain ratio penalizes the
    # length difference too harshly and misses real matches.

    location_score = fuzz.token_set_ratio(_plain_location(a["location"]), _plain_location(b["location"]))
    if location_score >= LOCATION_THRESHOLD:
        return True

    # One opening is often posted once per city (AlgaeCal's Associate Data
    # Scientist came through Adzuna as Richmond, Burnaby, North Vancouver,
    # Surrey and Greater Vancouver). Same company, title and description
    # means the same job even when the locations differ.
    return _same_description(a["description"], b["description"])


def _same_description(a: str | None, b: str | None) -> bool:
    a, b = normalize(a or ""), normalize(b or "")
    if len(a) < MIN_DESCRIPTION_CHARS or len(b) < MIN_DESCRIPTION_CHARS:
        return False
    return fuzz.ratio(a[:3000], b[:3000]) >= DESCRIPTION_THRESHOLD


def split_level_mismatches(conn: sqlite3.Connection) -> int:
    """Undo old merges of rows whose level words differ (see _LEVEL_WORDS). In each group the rows
    sharing the first row's level words stay; every other level-set becomes its own group.
    Returns the number of rows moved."""
    groups: dict[str, list[sqlite3.Row]] = {}
    for row in conn.execute("SELECT id, source, external_id, title, dedup_group_id FROM jobs ORDER BY id"):
        groups.setdefault(row["dedup_group_id"], []).append(row)
    moved = 0
    for group_id, members in groups.items():
        if len(members) < 2:
            continue
        keep = level_words(members[0]["title"])
        new_ids: dict[frozenset[str], str] = {}
        for m in members[1:]:
            lw = level_words(m["title"])
            if lw == keep:
                continue
            target = new_ids.setdefault(lw, f"{m['source']}:{m['external_id']}")
            set_dedup_group(conn, m["id"], target)
            moved += 1
            logger.info("Dedup: split job %s (%s) out of group %s", m["id"], m["title"], group_id)
    return moved


def run_dedup(conn: sqlite3.Connection, since_days: int = 45) -> int:
    """Merge matching jobs (first seen within `since_days`) into shared dedup groups.

    A job that matches rows of several groups joins all of them into one: a job that only joined the
    first match left the others split (61 pairs in Oct 2026: Fortinet, Amazon, Turing, Cisco ...).
    Returns the number of jobs whose dedup_group_id was changed.
    """
    split = split_level_mismatches(conn)
    candidates = jobs_for_dedup(conn, since_days=since_days)

    # `parent` maps a group id to the group it was merged into. Every job is compared with every
    # earlier job (not one representative per group): two rows can match each other while their
    # groups' first rows don't (Fortinet, Turing: 37 pairs stayed split after the first fix).
    parent: dict[str, str] = {}

    def find(g: str) -> str:
        while parent.get(g, g) != g:
            g = parent[g]
        return g

    for i, job in enumerate(candidates):
        job_group = find(job["dedup_group_id"])
        for other in candidates[:i]:
            other_group = find(other["dedup_group_id"])
            if other_group == job_group:
                continue  # already together
            if _is_match(job, other):
                parent[job_group] = other_group  # the earlier group wins
                job_group = other_group

    # Rewrite every row of a merged group, including rows older than the candidate window.
    merged_count = 0
    for group in list(parent):
        target = find(group)
        if target == group:
            continue
        merged_count += set_dedup_groups(conn, group, target)
        logger.info("Dedup: merged group %s into %s", group, target)

    conn.commit()
    logger.info("Dedup: merged %d job(s) across %d candidate(s)", merged_count, len(candidates))
    return merged_count + split
