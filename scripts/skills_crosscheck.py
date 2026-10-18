"""Monthly skills cross-check: public skill lists vs. the postings in jobs.db.

Matches O*NET technology/software names (CC BY 4.0) and ESCO skill labels against every
full-description posting, and reports names that appear in >= 3% of postings (or in any A-tier
posting) but that src.tailor.taxonomy does not cover yet. Output is a markdown table, to review
by hand before adding entries (with synonyms and false-match guards) to src/tailor/taxonomy.py.

    uv run python scripts/skills_crosscheck.py                   # download O*NET, no ESCO
    uv run python scripts/skills_crosscheck.py --esco esco/skills_en.csv --out report.md
    uv run python scripts/skills_crosscheck.py --onet path/to/Technology\\ Skills.txt

O*NET: the file is called "Technology Skills" up to database 30.x and "Software Skills" from 31.0
(onetcenter.org/database.html). Download URLs are tried in order; pass --onet to use a local
copy, or --onet-url to override. Columns used: Example, Hot Technology.

ESCO: the download is a form (esco.ec.europa.eu/en/use-esco/download), so pass the CSV yourself.
Choose the "skills" CSV in English; columns used: preferredLabel, altLabels (newline separated).
ESCO files stay git-ignored until their licence terms are confirmed.

Downloads are cached in materials/tailor/skill-lists/ (git-ignored).
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import sqlite3
import sys
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CACHE_DIR = ROOT / "materials" / "tailor" / "skill-lists"
ONET_URLS = [
    "https://www.onetcenter.org/dl_files/database/db_31_0_csv/software_skills.csv",
    "https://www.onetcenter.org/dl_files/database/db_30_3_text/Technology%20Skills.txt",
]
MIN_SHARE = 0.03
MIN_LEN = 3

# Words that are ordinary English; a name made only of these is skipped unless O*NET flags it hot.
COMMON_WORDS = {
    "access", "word", "outlook", "project", "office", "excel", "swift", "go", "r", "c", "ruby",
    "spring", "express", "unity", "slack", "teams", "zoom", "box", "chrome", "edge", "visio",
    "notes", "pages", "numbers", "keynote", "maps", "photos", "mail", "calendar", "sharing",
    "drive", "cloud", "mobile", "web", "data", "system", "systems", "software", "analysis",
    "management", "planning", "training", "design", "test", "testing", "service", "services",
    "support", "report", "reports", "reporting", "sales", "marketing", "research", "security",
    "network", "networking", "database", "communication", "leadership", "language", "english",
    "french", "math", "science", "business", "finance", "accounting", "customer", "quality",
}


@dataclass
class Name:
    name: str
    source: str  # "onet" or "esco"
    hot: bool = False

    @property
    def key(self) -> str:
        return self.name.lower()


@dataclass
class Row:
    name: str
    source: str
    hot: bool
    postings: int = 0
    a_tier: int = 0
    share: float = 0.0
    example: str = ""


# ---------- loading lists ----------

def _read_table(text: str) -> list[dict[str, str]]:
    first = text.lstrip("﻿").split("\n", 1)[0]
    delim = "\t" if first.count("\t") >= first.count(",") else ","
    return list(csv.DictReader(io.StringIO(text.lstrip("﻿")), delimiter=delim))


def parse_onet(text: str) -> list[Name]:
    """O*NET Technology/Software Skills table: `Example` names with a `Hot Technology` Y/N flag."""
    out: dict[str, Name] = {}
    for row in _read_table(text):
        ex = (row.get("Example") or "").strip()
        if not ex:
            continue
        hot = (row.get("Hot Technology") or "").strip().upper() == "Y"
        cur = out.get(ex.lower())
        if cur:
            cur.hot = cur.hot or hot
        else:
            out[ex.lower()] = Name(ex, "onet", hot)
    return list(out.values())


def parse_esco(text: str) -> list[Name]:
    """ESCO skills CSV: preferredLabel plus altLabels (newline or pipe separated)."""
    out: dict[str, Name] = {}
    for row in _read_table(text):
        labels = [(row.get("preferredLabel") or "").strip()]
        labels += re.split(r"[\n|]", row.get("altLabels") or "")
        for lab in labels:
            lab = lab.strip()
            if lab and lab.lower() not in out:
                out[lab.lower()] = Name(lab, "esco")
    return list(out.values())


def fetch_onet(cache_dir: Path, urls: list[str]) -> str:
    cache_dir.mkdir(parents=True, exist_ok=True)
    for url in urls:
        dest = cache_dir / ("onet-" + url.rsplit("/", 1)[-1].replace("%20", "_"))
        if dest.exists():
            return dest.read_text(encoding="utf-8-sig")
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                data = r.read()
        except Exception as e:  # try the next URL
            print(f"download failed ({url}): {e}", file=sys.stderr)
            continue
        dest.write_bytes(data)
        return data.decode("utf-8-sig")
    raise SystemExit("could not download O*NET; pass a local copy with --onet")


# ---------- matching ----------

def usable(n: Name) -> bool:
    """Skip names under 3 chars, or common English words (unless O*NET flags them hot)."""
    name = n.name.strip()
    if len(name) < MIN_LEN:
        return False
    if not n.hot and all(w in COMMON_WORDS for w in re.findall(r"[a-z]+", name.lower())):
        return False
    return True


def phrase_regex(name: str) -> re.Pattern[str]:
    """Whole-phrase, case-insensitive: not preceded/followed by a word char, + or #."""
    return re.compile(rf"(?<![\w+#]){re.escape(name.strip())}(?![\w+#])", re.I)


def load_postings(db: Path) -> list[tuple[str, str]]:
    """(description, tier) for every job with a full description."""
    con = sqlite3.connect(db)
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(jobs)")}
        desc = "description" if "description" in cols else None
        if desc is None:
            raise SystemExit("jobs table has no description column")
        tier = "tier" if "tier" in cols else "''"
        rows = con.execute(
            f"SELECT {desc}, {tier} FROM jobs WHERE {desc} IS NOT NULL AND length({desc}) > 200"
        ).fetchall()
    finally:
        con.close()
    return [(r[0], (r[1] or "")) for r in rows]


def covered(name: str) -> bool:
    """True when the existing taxonomy already recognises this name."""
    from src.tailor import taxonomy

    return bool(taxonomy.canonical(name)) or bool(taxonomy.find(name))


def crosscheck(
    names: list[Name],
    postings: list[tuple[str, str]],
    *,
    min_share: float = MIN_SHARE,
    is_covered=covered,
) -> list[Row]:
    """Names matching >= min_share of postings (or any A-tier posting) that the taxonomy lacks."""
    total = len(postings)
    if not total:
        return []
    rows: list[Row] = []
    seen: set[str] = set()
    for n in names:
        if n.key in seen or not usable(n):
            continue
        seen.add(n.key)
        rx = phrase_regex(n.name)
        count = a = 0
        example = ""
        for text, tier in postings:
            m = rx.search(text)
            if not m:
                continue
            count += 1
            if str(tier).upper() == "A":
                a += 1
            if not example:
                s = max(0, m.start() - 40)
                example = re.sub(r"\s+", " ", text[s : m.end() + 40]).strip()
        share = count / total
        if count and (share >= min_share or a) and not is_covered(n.name):
            rows.append(Row(n.name, n.source, n.hot, count, a, share, example))
    rows.sort(key=lambda r: (-r.postings, r.name.lower()))
    return rows


def render_table(rows: list[Row], total: int) -> str:
    lines = [
        f"# Skills cross-check ({total} postings)",
        "",
        "Names from the public lists that match >= 3% of postings or any A-tier posting and are not in "
        "`src/tailor/taxonomy.py`. Review by hand; add entries with synonyms and false-match guards.",
        "",
        "| Name | Source | Hot | Postings | % | A-tier | Example |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        ex = r.example.replace("|", "/")
        lines.append(
            f"| {r.name} | {r.source} | {'yes' if r.hot else ''} | {r.postings} | {r.share:.1%} | {r.a_tier} | {ex} |"
        )
    if not rows:
        lines.append("| (none) | | | | | | |")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--onet", type=Path, help="local O*NET Technology/Software Skills file (.txt/.csv)")
    ap.add_argument("--onet-url", help="override the O*NET download URL")
    ap.add_argument("--esco", type=Path, help="local ESCO skills CSV (download is a form; see docstring)")
    ap.add_argument("--db", type=Path, default=ROOT / "jobs.db")
    ap.add_argument("--min-share", type=float, default=MIN_SHARE)
    ap.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    ap.add_argument("--out", type=Path, help="write the markdown report here instead of stdout")
    args = ap.parse_args(argv)

    names: list[Name] = []
    if args.onet:
        names += parse_onet(args.onet.read_text(encoding="utf-8-sig"))
    else:
        urls = [args.onet_url] if args.onet_url else ONET_URLS
        names += parse_onet(fetch_onet(args.cache_dir, urls))
    if args.esco:
        names += parse_esco(args.esco.read_text(encoding="utf-8-sig"))
    postings = load_postings(args.db)
    report = render_table(crosscheck(names, postings, min_share=args.min_share), len(postings))
    if args.out:
        args.out.write_text(report, encoding="utf-8")
    else:
        sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
