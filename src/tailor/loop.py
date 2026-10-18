"""Step 7: decide between stopping and a repair round, and keep the best draft.

Reads each round's check.json and grade.json, records a one-line summary per
round in app.json, and picks `best_round`: the highest score among rounds with
no criticals, else the round with the fewest criticals (then highest score).
A round that adds a critical is therefore never the best while a cleaner round
exists. On "repair" it writes `drafts/r<N+1>/feedback.json`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.tailor import TailorError
from src.tailor.appdir import log, read_json, round_dir, write_json


def _round_numbers(app_dir: Path) -> list[int]:
    drafts = app_dir / "drafts"
    nums = []
    if drafts.is_dir():
        for p in drafts.iterdir():
            m = re.fullmatch(r"r(\d+)", p.name)
            if m and (p / "grade.json").exists():
                nums.append(int(m.group(1)))
    return sorted(nums)


def _failed(grade: dict[str, Any]) -> list[dict[str, Any]]:
    return [it for it in grade.get("checklist") or [] if it.get("passed") is False]


def _load(app_dir: Path, n: int) -> dict[str, Any]:
    d = round_dir(app_dir, n)
    check = read_json(d / "check.json")
    grade = read_json(d / "grade.json")
    failed = _failed(grade)
    return {
        "round": n,
        "score": float(grade.get("score", 0)),
        "ats": (grade.get("ats") or {}).get("total"),
        "criticals": len(check.get("criticals") or []),
        "failed_items": len(failed),
        "check": check,
        "grade": grade,
        "passed_ids": {it["id"] for it in grade.get("checklist") or [] if it.get("passed") is True},
        "failed_ids": {it["id"] for it in failed},
    }


def _best(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    clean = [r for r in rounds if r["criticals"] == 0]
    if clean:
        return max(clean, key=lambda r: (r["score"], -r["round"]))
    return min(rounds, key=lambda r: (r["criticals"], -r["score"], r["round"]))


def _section_of(path: str, doc: str) -> str | None:
    if doc == "letter" or path.startswith("letter"):
        return "letter"
    if not path:
        return None
    parts = path.split("/")
    return "summary" if parts[0] == "summary" else "/".join(parts[:2])


def _sections(cur: dict[str, Any]) -> list[str]:
    out: list[str] = []

    def add(s: str | None) -> None:
        if s and s not in out:
            out.append(s)

    for c in cur["check"].get("criticals") or []:
        add(_section_of(c.get("path", ""), c.get("doc", "")))
    for it in _failed(cur["grade"]):
        for s in it.get("sections") or []:
            add(s)
    for g in cur["grade"].get("gaps") or []:
        for s in g.get("sections") or []:
            add(s)
    return out


def next_round(app_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    app_dir = Path(app_dir)
    nums = _round_numbers(app_dir)
    if not nums:
        raise TailorError(f"no graded rounds in {app_dir / 'drafts'}")
    rounds = [_load(app_dir, n) for n in nums]
    cur, prev = rounds[-1], rounds[:-1]
    best = _best(rounds)

    loop_cfg = cfg.get("loop") or {}
    max_rounds = loop_cfg.get("max_rounds", 3)
    min_gain = loop_cfg.get("min_gain", 2.0)
    target = cfg.get("target_score", 80)
    floor = cfg.get("ats_floor", 70)
    below_floor = (cur["ats"] or 0) < floor

    reason: str | None = None
    feedback = list(cur["grade"].get("feedback") or [])
    if cur["criticals"] == 0 and cur["failed_items"] == 0 and (cur["ats"] or 0) >= target:
        reason = "all checks pass and the ATS score meets the target"
    elif prev:
        ref = _best(prev)
        newly_failed = cur["failed_ids"] & ref["passed_ids"]
        if cur["criticals"] > ref["criticals"]:
            reason = f"regression: round {cur['round']} has more criticals than round {ref['round']}"
        elif newly_failed:
            reason = f"regression: an item that passed in round {ref['round']} now fails"
        # Below the ATS floor a small gain still earns another round, up to the round limit.
        elif cur["score"] - ref["score"] < min_gain and not below_floor:
            reason = f"score gain under {min_gain} points over round {ref['round']}"
    if reason is None and len(rounds) >= max_rounds:
        reason = f"round limit of {max_rounds} reached"
    if reason is None and not (cur["check"].get("criticals") or feedback):
        reason = "nothing left to repair"

    summaries = [
        {"round": r["round"], "score": r["score"], "criticals": r["criticals"], "failed_items": r["failed_items"]}
        for r in rounds
    ]
    action = "stop" if reason else "repair"
    nxt = None if reason else cur["round"] + 1
    if not reason:
        reason = "failed items or criticals remain and the last round still gained"
        write_json(
            round_dir(app_dir, nxt) / "feedback.json",
            {
                "round": nxt,
                "criticals": cur["check"].get("criticals") or [],
                "failed_items": feedback,
                "sections": _sections(cur),
            },
        )
    log(app_dir, "loop", f"{action}: {reason}", rounds=summaries, best_round=best["round"])
    return {"action": action, "best_round": best["round"], "reason": reason, "next_round": nxt}
