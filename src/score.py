"""Deterministic fit score for aggregated jobs.

A points system, tuned by the `score:` section of config/settings.yaml:

  + title matches a target role family (best match only)
  + title / description say the job is entry-level
  + description mentions skills Jake has evidence for (capped), more when
    it asks for a key combo (Python + SQL) or names nothing he lacks
  - description leans on tools Jake hasn't used (capped)
  - title says senior / level II-III, or the posting asks for 3-5 years

Some things are hard skips rather than penalties (more than 5 years
required, wrong-field title, US residence required). A skipped job gets
tier "skip" and no score.

Every point comes with a reason string, so the dashboard can show why a job
ranked where it did. Scores are recomputed for every row on each aggregator
run (cheap: plain regex), so editing weights and re-running rescores all of
history, including descriptions filled in later by enrichment.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from src.tier import parse_min_years_experience

@dataclass
class ScoreResult:
    score: int | None  # None when skipped
    tier: str  # "A".."D" or "skip"
    reasons: list[str] = field(default_factory=list)

    @property
    def reasons_text(self) -> str:
        return "; ".join(self.reasons)


@lru_cache(maxsize=1024)
def _phrase_re(phrase: str) -> re.Pattern[str]:
    """Word-boundary, case-insensitive match that also accepts a plural "s"
    ("dashboard" matches "dashboards") on phrases of 4+ letters; short tokens
    like "i", "ii" or "hr" stay exact so "is" and "hrs" don't match. `\\b`
    breaks on phrases that end in punctuation ("c++", "sr."), so use
    look-arounds on word chars instead."""
    plural = "s?" if len(phrase) >= 4 and phrase[-1].isalpha() else ""
    return re.compile(rf"(?<!\w){re.escape(phrase)}{plural}(?!\w)", re.IGNORECASE)


def _first_match(text: str, phrases: list[str]) -> str | None:
    for p in phrases:
        if _phrase_re(p).search(text):
            return p
    return None


def score_job(
    *,
    title: str,
    description: str,
    location_category: str | None,
    years_experience: int | None,
    cfg: dict[str, Any],
) -> ScoreResult:
    title = title or ""
    description = description or ""
    reasons: list[str] = []

    # ── Hard skips ────────────────────────────────────────────────────
    skip_years = cfg.get("skip_years_over", 5)
    if years_experience is not None and years_experience > skip_years:
        return ScoreResult(None, "skip", [f"asks for {years_experience}+ years"])

    hit = _first_match(title, cfg.get("skip_title_terms") or [])
    if hit:
        return ScoreResult(None, "skip", [f"title: {hit}"])
    # Student-only roles are out, unless the title also opens them to new
    # grads ("Student / New Grad Positions").
    hit = _first_match(title, cfg.get("student_title_terms") or [])
    if hit and not _first_match(title, cfg.get("new_grad_title_terms") or []):
        return ScoreResult(None, "skip", [f"title: {hit}"])

    for pattern in cfg.get("skip_description_patterns") or []:
        if re.search(pattern, description, re.IGNORECASE):
            return ScoreResult(None, "skip", ["requires living in the US"])

    if location_category == "other" and cfg.get("skip_other_locations", True):
        return ScoreResult(None, "skip", ["location outside Vancouver / remote"])

    # ── Points ────────────────────────────────────────────────────────
    score = 0

    skills = cfg.get("skills", {})
    text = f"{title}\n{description}"
    have_hits = [kw for kw in (skills.get("have") or {}) if _phrase_re(kw).search(text)]
    gap_hits = [kw for kw in (skills.get("gaps") or {}) if _phrase_re(kw).search(text)]

    best_family: tuple[int, str, str] | None = None
    for fam in cfg.get("title_families") or []:
        # A broad family ("engineer", "developer") only counts when the
        # posting backs it up with skills Jake has.
        if len(have_hits) < fam.get("min_skill_hits", 0):
            continue
        hit = _first_match(title, fam.get("keywords") or [])
        if hit and (best_family is None or fam["points"] > best_family[0]):
            best_family = (fam["points"], fam["name"], hit)
    if best_family:
        score += best_family[0]
        reasons.append(f"+{best_family[0]} {best_family[1]} title ({best_family[2]})")

    entry = cfg.get("entry_level", {})
    hit = _first_match(title, entry.get("title_keywords") or [])
    if hit:
        score += entry.get("title_points", 0)
        reasons.append(f"+{entry.get('title_points', 0)} entry-level title ({hit})")
    else:
        hit = _first_match(description, entry.get("description_keywords") or [])
        if hit:
            score += entry.get("description_points", 0)
            reasons.append(f"+{entry.get('description_points', 0)} entry-level wording ({hit})")

    seniority = cfg.get("seniority", {})
    for rule in seniority.get("title_penalties") or []:
        hit = _first_match(title, rule.get("keywords") or [])
        if hit:
            score += rule["points"]
            reasons.append(f"{rule['points']} title level ({hit})")
            break

    if years_experience is not None:
        for rule in seniority.get("years_penalties") or []:
            if rule["min"] <= years_experience <= rule["max"]:
                score += rule["points"]
                sign = "+" if rule["points"] >= 0 else ""
                reasons.append(f"{sign}{rule['points']} asks for {years_experience} years")
                break

    have_pts = min(sum(skills["have"][kw] for kw in have_hits), skills.get("have_cap", 40))
    if have_pts:
        score += have_pts
        reasons.append(f"+{have_pts} skills ({', '.join(have_hits)})")

    gap_pts = max(sum(skills["gaps"][kw] for kw in gap_hits), -abs(skills.get("gap_cap", 15)))
    if gap_pts:
        score += gap_pts
        reasons.append(f"{gap_pts} gaps ({', '.join(gap_hits)})")

    for combo in skills.get("combos") or []:
        if all(kw in have_hits for kw in combo["skills"]):
            score += combo["points"]
            reasons.append(f"+{combo['points']} asks for {' + '.join(combo['skills'])}")

    no_gaps = skills.get("no_gaps_bonus") or {}
    if (
        no_gaps
        and not gap_hits
        and len(have_hits) >= no_gaps.get("min_have_hits", 3)
        and len(description) >= cfg.get("short_description_chars", 300)
    ):
        score += no_gaps["points"]
        reasons.append(f"+{no_gaps['points']} no skill gaps")

    loc_pts = (cfg.get("location_points") or {}).get(location_category or "", 0)
    if loc_pts:
        score += loc_pts
        reasons.append(f"+{loc_pts} {location_category}")

    min_desc = cfg.get("short_description_chars", 300)
    if len(description) < min_desc:
        reasons.append("snippet only, score is partial")

    tier = "D"
    for band in cfg.get("tiers") or []:
        if score >= band["min"]:
            tier = band["tier"]
            break
    return ScoreResult(score, tier, reasons)


def rescore_all(conn: sqlite3.Connection, cfg: dict[str, Any]) -> dict[str, int]:
    """Recompute score/tier for every row. Returns a count per tier."""
    counts: dict[str, int] = {}
    rows = conn.execute(
        "SELECT id, title, description, location_category, years_experience FROM jobs"
    ).fetchall()
    updates = []
    for row in rows:
        desc = row[2] or ""
        # Re-parse: years_experience is stored from the description at insert
        # time and goes stale once enrichment fills in the full posting.
        years = parse_min_years_experience(desc) if desc else row[4]
        result = score_job(
            title=row[1],
            description=desc,
            location_category=row[3],
            years_experience=years,
            cfg=cfg,
        )
        counts[result.tier] = counts.get(result.tier, 0) + 1
        updates.append((result.score, result.tier, result.reasons_text, row[0]))
    conn.executemany(
        "UPDATE jobs SET score = ?, tier = ?, score_reasons = ? WHERE id = ?", updates
    )
    conn.commit()
    return counts
