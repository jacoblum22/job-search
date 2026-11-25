"""Find public job boards for companies that keep showing up in aggregator results.

Read-only: lists companies from aggregator/email sources (tier A/B, seen N+ times) that are
not in config/ats_boards.yaml or settings.yaml, probes the public Greenhouse / Lever / Ashby /
SmartRecruiters / Workable feeds for a matching slug, and prints candidate YAML lines.
Nothing is written; review the output, then paste lines into config/ats_boards.yaml.

    uv run python scripts/find_boards.py [--min-jobs 2] [--limit 80]
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.db import connect  # noqa: E402

AGGREGATORS = ("adzuna", "himalayas", "jobicy", "careerjet", "linkedin", "glassdoor", "indeed", "jobright", "wellfound")
SUFFIX = re.compile(r"\b(inc|ltd|llc|lp|corp|corporation|limited|canada|group|company|co|job on t-net|technologies|technology|systems)\b\.?", re.I)
PROBES = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{s}/jobs",
    "lever": "https://api.lever.co/v0/postings/{s}",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{s}",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{s}/postings?limit=1",
}


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def configured_names() -> set[str]:
    names = set()
    for f in ("config/ats_boards.yaml", "config/settings.yaml"):
        text = (ROOT / f).read_text(encoding="utf8")
        for m in re.finditer(r'name:\s*"([^"]+)"', text):
            names.add(norm(m.group(1)))
    return names


def slugs(company: str) -> list[str]:
    base = re.sub(r"[^a-z0-9 ]", "", SUFFIX.sub("", company).lower()).split()
    out = ["".join(base), "-".join(base), "".join(re.sub(r"[^a-z0-9]", "", company.lower()).split())]
    return [s for i, s in enumerate(out) if s and s not in out[:i]]


def probe(client: httpx.Client, kind: str, slug: str) -> int | None:
    """Job count for a live board, else None."""
    try:
        r = client.get(PROBES[kind].format(s=slug))
        if r.status_code != 200:
            return None
        d = r.json()
    except (httpx.HTTPError, ValueError):
        return None
    if kind == "greenhouse":
        return len(d.get("jobs", []))
    if kind == "lever":
        return len(d) if isinstance(d, list) else None
    if kind == "ashby":
        return len(d.get("jobs", []))
    return d.get("totalFound", 0) or None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-jobs", type=int, default=2)
    ap.add_argument("--limit", type=int, default=80)
    args = ap.parse_args()
    conn = connect(ROOT / "jobs.db")
    have = configured_names()
    rows = conn.execute(
        "SELECT company, source FROM jobs WHERE tier IN ('A','B')").fetchall()
    count: Counter = Counter()
    display: dict[str, str] = {}
    for r in rows:
        if r["source"].split(":")[0] not in AGGREGATORS or norm(r["company"]) in have:
            continue
        count[norm(r["company"])] += 1
        display.setdefault(norm(r["company"]), r["company"])
    todo = [display[k] for k, n in count.most_common() if n >= args.min_jobs][: args.limit]
    print(f"# {len(todo)} companies seen {args.min_jobs}+ times with no board configured", file=sys.stderr)
    client = httpx.Client(timeout=15, headers={"User-Agent": "Mozilla/5.0 job-search board finder"})
    for company in todo:
        hits = []
        for kind in PROBES:
            for s in slugs(company):
                n = probe(client, kind, s)
                time.sleep(0.2)
                if n:
                    hits.append((kind, s, n))
                    break
        print(f"{company} ({count[norm(company)]} jobs): " + (", ".join(f"{k}:{s} [{n} jobs]" for k, s, n in hits) or "-"))


if __name__ == "__main__":
    main()
