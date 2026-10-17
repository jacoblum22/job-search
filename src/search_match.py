"""Shared keyword / seniority / location keep-logic for every source.

API boards are queried with expanded phrases; Workday and email alerts dump
whole inboxes/boards. Both paths then run the same `keep_job()` so a
"Human Resources" rule also matches "HR Coordinator". Weak words like
"recruiting" only match in the title — they appear in almost every
description.
"""

from __future__ import annotations

import re
from typing import Any

from src.location_filter import classify_location

# Extra phrases per canonical keyword from settings.yaml (lowercase keys).
# These are how real postings are titled; the canonical phrases alone miss them.
DEFAULT_ALIASES: dict[str, tuple[str, ...]] = {
    "public affairs": (
        "government relations",
        "public relations",
        "stakeholder relations",
        "corporate communications",
        "external relations",
        "communications coordinator",
        "communications intern",
        "communications assistant",
    ),
    "talent acquisition": (
        "talent attraction",
        "talent sourcing",
        "campus recruiter",
        "recruiter",
        "recruiting",
        "recruitment coordinator",
        "recruitment intern",
        "sourcer",
        "early talent",
    ),
    "indigenous relations": (
        "indigenous engagement",
        "indigenous partnership",
        "first nations relations",
        "indigenous",
    ),
    "events": (
        "event coordinator",
        "event intern",
        "event assistant",
        "event planning",
        "event planner",
        "special events",
        "events intern",
        "events coordinator",
        "events assistant",
    ),
    "market intelligence": ("competitive intelligence", "market intel"),
    "market research": (
        "consumer insights",
        "insights intern",
        "research intern",
        "market researcher",
    ),
    "business strategy": ("strategic planning", "strategy intern", "strategy analyst"),
    "business development": (
        "biz dev",
        "partnership intern",
        "partnerships intern",
        "business development intern",
        "bd intern",
    ),
    "business analyst": (
        "business analysis",
        "business systems analyst",
        "business system analyst",
        "business analyst intern",
        "business analyst co-op",
        "ba intern",
        "ba co-op",
        "ba coop",
    ),
    "human resources": (
        "human resource",
        "people operations",
        "people & culture",
        "people and culture",
        "hr intern",
        "hr coordinator",
        "hr assistant",
        "hr co-op",
        "hr coop",
        "hrbp",
        "people intern",
    ),
    "campus recruitment": (
        "campus recruiting",
        "university recruiting",
        "university recruiter",
        "campus talent",
        "early careers",
        "early talent",
    ),
}

# Bare word is too common in legal/boilerplate to search descriptions.
_NOISY_CANONICALS = frozenset({"events"})

# These match almost every posting in a description ("we are recruiting").
_TITLE_ONLY_ALIASES = frozenset(
    {
        "recruiter",
        "recruiting",
        "sourcer",
        "reconciliation",
        "indigenous",
    }
)

# Tokens that must not match as substrings ("hr" in "the", "ta" in "digital").
_BOUNDARY_PHRASES = frozenset({"hr", "ta", "pr", "ba", "bd", "hrbp"})


def _norm_key(phrase: str) -> str:
    return " ".join(phrase.lower().split())


def aliases_for(canonical: str, search: dict[str, Any] | None = None) -> tuple[str, ...]:
    key = _norm_key(canonical)
    extra: tuple[str, ...] = ()
    if search:
        override = (search.get("keyword_aliases") or {}).get(canonical) or (
            search.get("keyword_aliases") or {}
        ).get(key)
        if override:
            extra = tuple(override)
    return DEFAULT_ALIASES.get(key, ()) + extra


def all_match_phrases(canonical: str, search: dict[str, Any] | None = None) -> list[str]:
    phrases = [canonical, *aliases_for(canonical, search)]
    # De-dupe, preserve order.
    seen: set[str] = set()
    out: list[str] = []
    for p in phrases:
        k = _norm_key(p)
        if k in seen:
            continue
        seen.add(k)
        out.append(p)
    return out


def _phrase_in(haystack: str, phrase: str) -> bool:
    needle = phrase.strip()
    if not needle:
        return False
    text = haystack.lower()
    n = needle.lower()
    if n in _BOUNDARY_PHRASES or (len(n) <= 3 and " " not in n):
        return bool(re.search(rf"\b{re.escape(n)}\b", text))
    return n in text


def _is_precise_body_phrase(phrase: str) -> bool:
    """Two-word corporatese ('human resources', 'business analyst') appears in
    every employer's boilerplate. Body matches must look like a role name."""
    n = _norm_key(phrase)
    if n in _TITLE_ONLY_ALIASES:
        return False
    if any(tok in n for tok in ("intern", "co-op", "coop", "coordinator", "recruiter")):
        return True
    return len(n.split()) >= 3


def _body_phrases(canonical: str, search: dict[str, Any] | None = None) -> list[str]:
    key = _norm_key(canonical)
    if key in _NOISY_CANONICALS:
        candidates = list(aliases_for(canonical, search))
    else:
        candidates = all_match_phrases(canonical, search)
    return [
        p
        for p in candidates
        if _norm_key(p) not in _TITLE_ONLY_ALIASES and _is_precise_body_phrase(p)
    ]


def text_matches_canonical(canonical: str, title: str, body: str, search: dict[str, Any] | None = None) -> bool:
    """True if title/body mention this keyword the way a human would mean it."""
    if any(_phrase_in(title, p) for p in all_match_phrases(canonical, search)):
        return True
    if not body:
        return False
    return any(_phrase_in(body, p) for p in _body_phrases(canonical, search))


def job_matches_keywords(job: Any, search: dict[str, Any], *, include_description: bool) -> bool:
    keywords = list(search.get("keywords") or [])
    if not keywords:
        return True
    title = job.title or ""
    body = ""
    if include_description:
        body = job.description or ""
        raw = getattr(job, "raw", None) or {}
        if isinstance(raw, dict):
            body = f"{body} {raw.get('subject') or ''}"
    return any(text_matches_canonical(kw, title, body, search) for kw in keywords)


# Extra API `what` strings that are not canonical×level. Adzuna has no phrase-OR
# for multi-word aliases (`what_or` is word-OR and would match "event" or
# "coordinator" separately). These are the titles we actually see in the wild.
PRIORITY_API_QUERIES = (
    "HR intern",
    "HR co-op",
    "HR coordinator",
    "event coordinator intern",
    "events intern",
    "campus recruiter intern",
    "recruiter intern",
    "business analyst co-op",
    "BA intern",
    "people operations intern",
    "government relations intern",
    "public relations intern",
    "market research intern",
    "competitive intelligence intern",
    "early talent intern",
    "indigenous relations intern",
)


def api_queries(search: dict[str, Any], *, level_variants: bool = True) -> list[str]:
    """Canonical keyword × every level_term, plus a short list of alias queries.

    `level_variants=False` drops the keyword × level_term searches (the
    extras keep their own "junior ..." phrasings).

    Expanding every alias × every level is hundreds of Adzuna calls (rate limits).
    Workday/email still use the full alias table in `keep_job()`.
    """
    levels = [str(lv) for lv in (search.get("level_terms") or [""])] if level_variants else []
    queries: list[str] = []
    seen: set[str] = set()

    def add(q: str) -> None:
        # The APIs match every word anywhere, so word order doesn't make a new
        # search: "junior data analyst" is the same call as "Data Analyst junior".
        k = " ".join(sorted(_norm_key(q).split()))
        if not k or k in seen:
            return
        seen.add(k)
        queries.append(q)

    for kw in search.get("keywords") or []:
        add(kw)
        for lvl in levels:
            add(f"{kw} {lvl}".strip())
    extras = search.get("extra_api_queries")
    for extra in extras if extras is not None else PRIORITY_API_QUERIES:
        add(str(extra))
    return queries


def keep_job(
    job: Any,
    search: dict[str, Any],
    *,
    match_keywords: bool,
    include_description: bool = True,
    require_relevant_location: bool | None = None,
) -> bool:
    """Return True if this job should be stored.

    `match_keywords` is True for Workday/email (unfiltered dumps) and also for
    API results after fetch — Adzuna's relevance ranking is looser than our
    phrase table, so we re-check instead of trusting the search hit.
    """
    title = job.title or ""
    if company_excluded(getattr(job, "company", "") or "", search):
        return False
    if match_keywords and not job_matches_keywords(
        job, search, include_description=include_description
    ):
        return False
    if any(
        re.search(rf"\b{re.escape(t.lower())}\b", title.lower())
        for t in search.get("exclude_title_terms") or []
    ):
        return False
    max_years = search.get("max_years_experience")
    years = getattr(job, "years_experience", None)
    if max_years is not None and years is not None and years > max_years:
        return False
    if require_relevant_location is None:
        require_relevant_location = bool(search.get("require_relevant_location", True))
    if require_relevant_location:
        company = getattr(job, "company", "") or ""
        location = getattr(job, "location", "") or ""
        if classify_location(location, company) == "other":
            return False
    return True


def company_excluded(company: str, search: dict[str, Any]) -> bool:
    """True if `company` matches an `exclude_companies` entry (e.g. a past employer)."""
    lowered = company.lower()
    return any(
        re.search(rf"\b{re.escape(c.lower())}\b", lowered) for c in search.get("exclude_companies") or []
    )


INTERNSHIP_TITLE_RE = re.compile(
    r"\b(interns?|internships?|co-?ops?|students?|undergraduate|practicum|work[- ]term|work placement"
    r"|stagiaires?|stage crédité|étudiant(?:e|s|es)?)\b",
    re.IGNORECASE,
)

# Not "assistant" or "coordinator": they pulled in Pharmacy Assistant and
# Events Coordinator listings that never matched a keyword after the fetch.
_EARLY_CAREER_TITLE_RE = re.compile(
    r"\b(junior|new[\s-]?grad|graduates?|entry[\s-]level|analyst)\b",
    re.IGNORECASE,
)


def should_hydrate_record(title: str, search: dict[str, Any], *, company: str = "", location: str = "") -> bool:
    """True if we should spend a details/HTML fetch on this listing.

    Title already matching the phrase table is enough. So is any word from
    the deliberately broad `fetch_title_terms` (data, analytics, software, …)
    in a title without an excluded term, and any early-career title
    (intern/co-op/junior/graduate/…), in case the keyword is only in the
    description. HVAC / mortgage / VP listings do not.
    """
    from types import SimpleNamespace

    if company_excluded(company, search):
        return False
    probe = SimpleNamespace(
        title=title,
        company=company,
        location=location,
        description="",
        years_experience=None,
        raw=None,
    )
    if keep_job(
        probe,
        search,
        match_keywords=True,
        include_description=False,
        require_relevant_location=False,
    ):
        return True
    lowered = title.lower()
    excluded = any(
        re.search(rf"\b{re.escape(t.lower())}\b", lowered) for t in search.get("exclude_title_terms") or []
    )
    if not excluded and any(
        re.search(rf"\b{re.escape(t.lower())}\b", lowered) for t in search.get("fetch_title_terms") or []
    ):
        return True
    return bool(INTERNSHIP_TITLE_RE.search(title) or _EARLY_CAREER_TITLE_RE.search(title))
