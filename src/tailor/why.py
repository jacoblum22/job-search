"""`why`: one application's state in a single read, for "why does this need fixes?".

Answering that used to mean opening app.json, check.md, the best round's check.json and
feedback.json, and the latest run-review notes one by one. This gathers what decides the
status (criticals, a wide ATS gap) first, then what is left to review, in plain words.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.resume import load_resume
from src.tailor import appdir, explain, review
from src.tailor.paths import resolve

_HEADER = re.compile(r"^\*\*(?P<head>.+?)\*\*\s*$")
# Role words many titles share: "Amazon Data Scientist" isn't "Amazon ICQA Data Analyst".
_COMMON = {"data", "analyst", "analytics", "analysis", "scientist", "science", "engineer", "engineering",
           "developer", "software", "junior", "senior", "intern", "and", "the", "business", "intelligence"}


def find(cfg: dict[str, Any], query: str) -> list[Path]:
    """Application folders matching `query`: a job id, or words that all appear in the folder name."""
    root = resolve(cfg, "applications")
    folders = sorted(p.parent for p in root.glob("*/app.json"))
    q = query.strip()
    if q.isdigit():
        out = []
        for f in folders:
            try:
                if int(appdir.load_app(f).get("job_id") or 0) == int(q):
                    out.append(f)
            except Exception:  # noqa: BLE001, S112 - a broken folder doesn't stop the search
                continue
        return out
    words = [w for w in re.split(r"\W+", q.lower()) if w]
    return [f for f in folders if all(w in f.name.lower() for w in words)]


def _shipped(app_dir: Path, rd: Path | None) -> dict[str, Any] | None:
    path = appdir.humanized(app_dir, "resume.yaml") or (rd / "resume.yaml" if rd else None)
    try:
        return load_resume(path) if path and path.exists() else None
    except Exception:  # noqa: BLE001 - the summary still helps without line text
        return None


def _say(items: list[dict[str, Any]], data: dict[str, Any] | None) -> list[str]:
    return [explain.issue(it, data)[0] for it in items]


def review_notes(cfg: dict[str, Any], app: dict[str, Any], newest: int = 3) -> list[dict[str, Any]]:
    """What the latest post-run reviews said about this job under "Look at before sending"
    (a bold header naming the company and a word of the title, then its bullets)."""
    notes_dir = resolve(cfg, "materials") / "tailor" / "run-reviews"
    company = str(app.get("company") or "").lower()
    title_words = {w for w in re.split(r"\W+", str(app.get("title") or "").lower())
                   if len(w) >= 3 and w not in _COMMON}
    out = []
    for path in sorted(notes_dir.glob("*.md"), reverse=True)[:newest]:
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            m = _HEADER.match(line.strip())
            if not m:
                continue
            head = m.group("head").lower()
            if company not in head or (title_words and not any(re.search(rf"\b{re.escape(w)}\b", head)
                                                                for w in title_words)):
                continue
            body = []
            for nxt in lines[i + 1:]:
                if nxt.startswith(("- ", "  ")):
                    body.append(nxt.strip()[2:] if nxt.startswith("- ") else nxt.strip())
                elif nxt.strip() == "" and not body:
                    continue
                else:
                    break
            out.append({"review": path.stem, "notes": body})
    return out


def summarize(app_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    app = appdir.load_app(app_dir)
    rnd = app.get("best_round")
    rd = appdir.round_dir(app_dir, int(rnd)) if rnd else None
    check = appdir.read_json(rd / "check.json") if rd and (rd / "check.json").exists() else {}
    checks_from = f"round {rnd} check.json"
    if check:
        # check.json is from the run; a hand fix or a later code fix since then only shows in a
        # fresh code-only check (nothing is written and Jev isn't asked).
        try:
            from src.tailor.checks import recheck

            check = recheck(app_dir, int(rnd), cfg)
            checks_from = "checked again now (code checks; Jev's answers from the run)"
        except Exception as e:  # noqa: BLE001 - the stored check still answers the question
            checks_from += f" (a fresh check failed: {e})"
    grade = appdir.read_json(rd / "grade.json") if rd and (rd / "grade.json").exists() else {}
    data = _shipped(app_dir, rd)

    criticals = check.get("criticals") or []
    # Without a fresh check (a shell without the project's packages), say the criticals are the run's.
    label = "Critical" if checks_from.startswith("checked again") or not check else "Critical at the run (not re-checked)"
    reasons = [f"{label}: {h}" for h in _say(criticals, data)]
    ats = (grade.get("ats") or {}).get("total")
    ceiling = grade.get("ats_ceiling")
    wide = float((cfg.get("loop") or {}).get("wide_gap", 8))
    if isinstance(ats, (int, float)) and isinstance(ceiling, (int, float)) and ats < ceiling - wide:
        reasons.append(f"Wide ATS gap: {ats:.1f} against a reachable {ceiling:.1f} (more than {wide:g} under)")

    check_md = app_dir / "check.md"
    text = check_md.read_text(encoding="utf-8") if check_md.exists() else ""
    return {
        "folder": app_dir.name,
        "job_id": app.get("job_id"),
        "status": app.get("status"),
        "why_status": reasons or ["No criticals and no wide ATS gap"],
        "checks_from": checks_from,
        "best_round": rnd,
        "rounds": app.get("rounds") or [],
        "grade": {"score": grade.get("score"), "ats": ats, "ats_ceiling": ceiling,
                  "fit_gap": grade.get("fit_gap")},
        "gate_flags": [explain.gate_flag(f)[0] for f in (app.get("gate") or {}).get("flags") or []],
        "warnings": _say(check.get("warnings") or [], data),
        "jev_flags": _say([f for f in check.get("flags") or [] if not explain.is_note(f)], data),
        "open_review_items": review.open_items(text) if text else None,
        "last_steps": [f"{h.get('step')}: {h.get('note')}" for h in (app.get("history") or [])[-6:]],
        "run_review_notes": review_notes(cfg, app),
    }
