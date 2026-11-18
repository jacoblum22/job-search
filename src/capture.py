"""Job links captured from any web page by the Job Autofill extension.

The extension finds links to job postings on the page you are looking at (a LinkedIn or Glassdoor
list, a company careers page, "more jobs like this") and posts them to /api/autofill/capture. For
each link this module decides, without fetching anything:

  in_dashboard  the same posting is already stored (same source id, same link, or the same
                title at the same company from another source)
  added         new: stored now with whatever the page showed, so it appears on the dashboard
  skipped       not stored, with the reason (closed earlier, excluded company, not a fit, ...)

Stored listings use the same (source, external_id) the scrapers use for that board
(`greenhouse:<slug>`, `lever:<slug>`, `linkedin`, ...), so a later scrape updates the row instead of
adding a second one; links from sites we have no scraper for are stored as source `web`. A listing
without a full description is finished afterwards, off the request (`finish`): sites that allow a
plain fetch are fetched by src/enrich.py, and LinkedIn / Indeed / Glassdoor are left for the Chrome
description task (scripts/browser_queue.py), exactly as for listings from alert emails.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import yaml
from rapidfuzz import fuzz

from src.db import Job, _now, normalize, upsert_job
from src.dedup import _core_company, level_words
from src.enrich import SNIPPET_MAX_CHARS, enrich_descriptions, worth_keeping
from src.retention import pruned_keys
from src.search_match import keep_job, should_hydrate_record

logger = logging.getLogger(__name__)

SETTINGS = Path(__file__).resolve().parent.parent / "config" / "settings.yaml"
MAX_LINKS = 200
TITLE_MATCH = 92
# Parameters that only track where a click came from; two links differing in them are the same page.
_TRACKING = re.compile(r"^(utm_.*|gclid|fbclid|mc_.*|trk.*|ref|referrer|source|src|lang|locale|jr_id|gh_src|"
                       r"refid|trackingid|eBP|lipi|midtoken|midsig|trkemail|otptoken|rcm|tk|from|vjs)$", re.I)

_GREENHOUSE_HOSTS = ("boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io",
                     "job-boards.eu.greenhouse.io")


@dataclass
class Target:
    """Where a link points, in the terms the scrapers store it under."""

    source: str
    external_id: str
    url: str


def _clean(s: Any, limit: int) -> str:
    return " ".join(str(s or "").split())[:limit]


def classify(url: str) -> Target | None:
    """The stored identity of a posting link: known boards keep their own ids, anything else is `web`."""
    try:
        u = urlparse(url)
    except ValueError:
        return None
    if u.scheme not in ("http", "https") or not u.netloc:
        return None
    host = u.netloc.lower().removeprefix("www.")
    q = {k: v[0] for k, v in parse_qs(u.query).items() if v}
    path = u.path

    if host.endswith("linkedin.com"):
        m = re.search(r"/jobs/view/(?:[^/?#]*-)?(\d{6,})", path)
        job_id = m.group(1) if m else (q.get("currentJobId") or "")
        if job_id.isdigit():
            return Target("linkedin", job_id, f"https://www.linkedin.com/jobs/view/{job_id}/")
        return None
    if "indeed." in host:
        jk = q.get("jk") or q.get("vjk") or ""
        if re.fullmatch(r"[0-9a-f]{8,40}", jk):
            return Target("indeed", jk, f"https://{host}/viewjob?jk={jk}")
        return None
    if "glassdoor." in host:
        jl = q.get("jl") or q.get("jobListingId") or q.get("jlid") or ""
        if jl.isdigit():
            return Target("glassdoor", jl, f"https://www.glassdoor.ca/job-listing/j?jl={jl}")
        return None
    if host in _GREENHOUSE_HOSTS:
        m = re.match(r"/([^/]+)/jobs/(\d+)", path)
        if m:
            return Target(f"greenhouse:{m[1]}", m[2], f"https://{host}/{m[1]}/jobs/{m[2]}")
    if host == "jobs.lever.co":
        m = re.match(r"/([^/]+)/([0-9a-f-]{36})", path)
        if m:
            return Target(f"lever:{m[1]}", m[2], f"https://jobs.lever.co/{m[1]}/{m[2]}")
    if host == "jobs.ashbyhq.com":
        m = re.match(r"/([^/]+)/([0-9a-f-]{36})", path)
        if m:
            return Target(f"ashby:{m[1]}", m[2], f"https://jobs.ashbyhq.com/{m[1]}/{m[2]}")
    if host == "apply.workable.com":
        m = re.match(r"/([^/]+)/j/([0-9A-Za-z]+)", path)
        if m:
            return Target(f"workable:{m[1]}", m[2], f"https://apply.workable.com/{m[1]}/j/{m[2]}/")
    key = url_key(url)
    return Target("web", hashlib.sha1(key.encode()).hexdigest()[:16], url)


def url_key(url: str) -> str:
    """The link without scheme, `www.`, tracking parameters, fragment or trailing slash."""
    try:
        u = urlparse(url or "")
    except ValueError:
        return ""
    query = sorted(f"{k}={v[0]}" for k, v in parse_qs(u.query).items() if v and not _TRACKING.match(k))
    base = u.netloc.lower().removeprefix("www.") + u.path.rstrip("/").lower()
    return base + ("?" + "&".join(query) if query else "")


def load_settings() -> dict[str, Any]:
    with SETTINGS.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _same_posting(a_title: str, a_company: str, b_title: str, b_company: str) -> bool:
    """Same company and (nearly) the same title at the same level: one posting seen on two sites."""
    if not a_title or not b_title or not a_company or not b_company:
        return False
    ca, cb = _core_company(a_company), _core_company(b_company)
    if not ca or not cb or fuzz.ratio(ca, cb) < 85:
        return False
    if level_words(a_title) != level_words(b_title):
        return False
    return fuzz.ratio(normalize(a_title), normalize(b_title)) >= TITLE_MATCH


def process(conn, items: list[dict], settings: dict[str, Any]) -> tuple[list[dict], list[Job]]:
    """Check each captured link against what is stored and store the new ones that fit.

    Returns the per-link answer (same order as `items`) and the Jobs that were added.
    """
    search = settings.get("search") or {}
    existing = conn.execute("SELECT id, source, external_id, url, title, company FROM jobs").fetchall()
    by_id = {(r[1], r[2]): r[0] for r in existing}
    by_url = {}
    for r in existing:
        if r[3]:
            by_url.setdefault(url_key(r[3]), r[0])
    by_company: dict[str, list] = {}
    for r in existing:
        by_company.setdefault(_core_company(r[5])[:4], []).append(r)
    gone = pruned_keys(conn)
    # Companies seen per board, so a link on a board we scrape takes the company name we already use.
    known_company = {r[1]: r[5] for r in existing if r[5] and ":" in (r[1] or "")}

    results: list[dict] = []
    added: list[Job] = []
    seen: set[tuple[str, str]] = set()
    for item in items[:MAX_LINKS]:
        url = _clean(item.get("url"), 1000)
        title = _clean(item.get("title"), 200)
        res: dict[str, Any] = {"url": url, "title": title}
        results.append(res)
        t = classify(url)
        if t is None or not title:
            res.update(status="skipped", reason="not a posting link" if t is None else "no title")
            continue
        key = (t.source, t.external_id)
        if key in seen:
            res.update(status="skipped", reason="listed twice")
            continue
        seen.add(key)
        company = _clean(item.get("company"), 120) or known_company.get(t.source, "")
        location = _clean(item.get("location"), 120)
        hit = by_id.get(key) or by_url.get(url_key(url)) or by_url.get(url_key(t.url))
        if not hit and company:
            for r in by_company.get(_core_company(company)[:4], []):
                if _same_posting(title, company, r[4], r[5]):
                    hit = r[0]
                    break
        if hit:
            res.update(status="in_dashboard", job_id=hit)
            continue
        if key in gone:
            res.update(status="skipped", reason="removed earlier (expired or too old)")
            continue
        job = Job(
            source=t.source, external_id=t.external_id, title=title, company=company, location=location,
            description=str(item.get("description") or "")[:20000], url=t.url,
            posted_date=_clean(item.get("posted"), 40) or None,
            raw={"captured_from": _clean(item.get("page"), 300), "captured_at": _now()},
        )
        # Cards often carry no location; an unknown one must not sink a posting the full page may place later.
        require_location = bool(search.get("require_relevant_location", True)) and bool(location)
        wanted = lambda j: should_hydrate_record(j.title, search, company=j.company, location=j.location)  # noqa: E731
        if not worth_keeping(job, wanted):
            res.update(status="skipped", reason="title not relevant")
            continue
        if not keep_job(job, search, match_keywords=False, require_relevant_location=require_location):
            res.update(status="skipped", reason="excluded company, level or location")
            continue
        job_id, was_new = upsert_job(conn, job)
        res.update(status="added" if was_new else "in_dashboard", job_id=job_id)
        if was_new:
            added.append(job)
    conn.commit()
    return results, added


def finish(conn, jobs: list[Job], settings: dict[str, Any]) -> list[int]:
    """The slow half, run after the answer is sent: fetch full postings where a plain request can,
    store them, drop postings that turn out to be closed, and score everything new.

    Returns the ids of the rows that changed.
    """
    from src.score import rescore_all

    search = settings.get("search") or {}
    enrich = settings.get("enrich") or {}
    todo = [j for j in jobs if len(j.description or "") < SNIPPET_MAX_CHARS]
    if todo:
        try:
            enrich_descriptions(
                todo, conn=conn,
                should_fetch=lambda j: should_hydrate_record(j.title, search, company=j.company, location=j.location),
                host_pause=enrich.get("host_pause_seconds", 1.0), max_fetches=len(todo), workers=3,
            )
        except Exception:
            logger.exception("Capture: description fetch failed; keeping what the page showed")
    ids = []
    for j in jobs:
        # A posting that answered 404/410 was deleted and tombstoned by enrich_descriptions (and left `todo`).
        row = conn.execute("SELECT id FROM jobs WHERE source = ? AND external_id = ?", (j.source, j.external_id)).fetchone()
        if row is None:
            continue
        upsert_job(conn, j)  # keeps the longer description, refreshes years and location
        ids.append(row[0])
    conn.commit()
    if ids:
        rescore_all(conn, settings.get("score") or {})
        conn.commit()
    return ids
