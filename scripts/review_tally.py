"""Running tally of what each post-run review found, by area (docs/run-review-task.md).

The goal is fewer fixes over time. Each review tags its problems by area; this
keeps them in one CSV so a review (and Jake) can see when an area keeps coming
back, which means the earlier fixes were patches, not the source.

    uv run python scripts/review_tally.py add .run-review-tally.json materials/tailor/run-reviews/tally.csv 2026-10-21_1252
    uv run python scripts/review_tally.py show materials/tailor/run-reviews/tally.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

AREAS = (
    "wording-match",      # does the draft/vault/posting use the same words (evidence, check, grade)
    "job-selection",      # which jobs are queued: score, tier, location, closed postings
    "company-research",   # finding, saving and verifying company facts
    "resume-check",       # truth checks on the resume draft
    "letter",             # cover-letter drafting and its checks
    "ats-grade",          # ATS score, ceiling, repair targets
    "repair-loop",        # rounds, regressions, when to stop
    "review-file",        # check.md wording and layout
    "runbook-prompt",     # the run's instructions and prompts
    "tooling",            # command output, wrappers, permissions, crashes
    "other",
)
STATUSES = ("fixed", "left", "question")
FIELDS = ("run", "area", "status", "problem")


def add(entries: list[dict], csv_path: Path, run: str) -> int:
    """Append one review's problems; unknown areas or statuses become "other" / "left"."""
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    new = not csv_path.exists()
    n = 0
    with csv_path.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, FIELDS)
        if new:
            w.writeheader()
        for e in entries:
            if not isinstance(e, dict) or not str(e.get("problem", "")).strip():
                continue
            area = e.get("area") if e.get("area") in AREAS else "other"
            status = e.get("status") if e.get("status") in STATUSES else "left"
            w.writerow({"run": run, "area": area, "status": status,
                        "problem": " ".join(str(e["problem"]).split())[:300]})
            n += 1
    return n


def summary(csv_path: Path, last: int = 8) -> str:
    """Problems per area across the last `last` reviewed runs, oldest run first."""
    if not csv_path.exists():
        return "No reviews tallied yet.\n"
    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    runs = sorted({r["run"] for r in rows})[-last:]
    by_area: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r["run"] in runs:
            by_area[r["area"]][r["run"]] += 1
    lines = [f"Problems found per review, last {len(runs)} runs ({runs[0]} to {runs[-1]}):", ""]
    lines.append("| area | " + " | ".join(r[5:] for r in runs) + " | total |")
    lines.append("|---" * (len(runs) + 2) + "|")
    for area in sorted(by_area, key=lambda a: -sum(by_area[a].values())):
        counts = [by_area[area][r] for r in runs]
        lines.append(f"| {area} | " + " | ".join(str(c) for c in counts) + f" | {sum(counts)} |")
    totals = [sum(by_area[a][r] for a in by_area) for r in runs]
    lines.append("| **all** | " + " | ".join(str(c) for c in totals) + f" | {sum(totals)} |")
    repeat = [a for a in by_area if sum(1 for r in runs if by_area[a][r]) >= 3]
    if repeat:
        lines += ["", "Found in 3 or more of these runs (look for a source fix): " + ", ".join(sorted(repeat))]
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("tally_json", type=Path)
    a.add_argument("csv", type=Path)
    a.add_argument("run")
    s = sub.add_parser("show")
    s.add_argument("csv", type=Path)
    s.add_argument("--last", type=int, default=8)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    if args.cmd == "add":
        entries = json.loads(args.tally_json.read_text(encoding="utf-8-sig"))
        print(f"tallied {add(entries if isinstance(entries, list) else [], args.csv, args.run)} problems")
    else:
        sys.stdout.write(summary(args.csv, args.last))


if __name__ == "__main__":
    main()
