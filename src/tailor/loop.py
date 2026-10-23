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
from src.tailor.appdir import load_app, log, read_json, round_dir, write_json
from src.tailor.grade import p_pass


def _round_dirs(app_dir: Path) -> dict[int, Path]:
    drafts = app_dir / "drafts"
    out = {}
    if drafts.is_dir():
        for p in drafts.iterdir():
            m = re.fullmatch(r"r(\d+)", p.name)
            if m and p.is_dir():
                out[int(m.group(1))] = p
    return out


def _feedback(app_dir: Path, n: int) -> dict[str, Any]:
    p = round_dir(app_dir, n) / "feedback.json"
    return read_json(p) if p.exists() else {}


def pending_round(app_dir: Path) -> int | None:
    """A round the tool asked for (its feedback.json is written) that was never graded: a run
    stopped partway, or the round was asked for outside a run (a letter round, a repair that
    `next-round` started after a fix). The daily run finishes these before new jobs."""
    waiting = [n for n, d in _round_dirs(Path(app_dir)).items()
               if (d / "feedback.json").exists() and not (d / "grade.json").exists()]
    return max(waiting) if waiting else None


def letter_round(app_dir: Path, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Ask for a letter-only round when the best round's letter fails a letter check under today's
    rules (the 250-word rule of Oct 22 2026 flagged letters drafted before it). The resume carries
    over from the best round unchanged. Writes `drafts/r<N>/feedback.json` and returns it, or None.

    One try per best round: a letter round that didn't become the best, or that is the best and
    still falls short, isn't asked for again, so a letter that can't be fixed doesn't cost a round
    every day."""
    from src.tailor.checks import recheck

    app_dir = Path(app_dir)
    best = (load_app(app_dir).get("best_round") or 0)
    if not best or pending_round(app_dir) is not None:
        return None
    dirs = _round_dirs(app_dir)
    if best not in dirs or _feedback(app_dir, best).get("letter_only"):
        return None
    if any(_feedback(app_dir, n).get("letter_only") and _feedback(app_dir, n).get("build_on") == best
           for n in dirs):
        return None
    warnings = [w for w in recheck(app_dir, best, cfg).get("warnings") or []
                if w.get("doc") == "letter" and w.get("code") in _ROUND_WARNINGS]
    if not warnings:
        return None
    nxt = max(dirs) + 1
    feedback = {
        "round": nxt,
        "build_on": best,
        "letter_only": True,
        "criticals": [],
        "failed_items": [],
        "warnings": [{"code": w["code"], "message": w["message"], "path": w.get("path", "")} for w in warnings],
        "sections": ["letter"],
    }
    write_json(round_dir(app_dir, nxt) / "feedback.json", feedback)
    log(app_dir, "letter-round", f"round {nxt}: letter only, on round {best}: "
        + "; ".join(w["code"] for w in warnings))
    return feedback


_ATS_NOTES = ("Use the posting's own words", "Open the summary's first sentence with the job title",
              "Soft skills the vault shows")


def _wide_gap(r: dict[str, Any], loop_cfg: dict[str, Any]) -> bool:
    ceiling = r["grade"].get("ats_ceiling")
    return ceiling is not None and (r["ats"] or 0) < float(ceiling) - float(loop_cfg.get("wide_gap", 10))


def gap_round(app_dir: Path, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Ask for one more repair round when the best round's ATS, scored under today's rules, is more
    than `loop.wide_gap` points under what the evidence allows and the resume leaves backed terms
    unsaid (Jake, Oct 23 2026: VCH Junior Data Developer stopped at 59.2 with about 71 reachable).
    It builds on the best round. Writes `drafts/r<N>/feedback.json` and returns it, or None. One
    try per best round, like `letter_round`."""
    from src.resume import load_resume
    from src.tailor.grade import _vault_wording, ats_gap, ats_gap_lines, ats_score, graded_evidence, title_ok

    app_dir = Path(app_dir)
    best = (load_app(app_dir).get("best_round") or 0)
    if not best or pending_round(app_dir) is not None:
        return None
    dirs = _round_dirs(app_dir)
    rdir = round_dir(app_dir, best)
    if best not in dirs or not (rdir / "grade.json").exists():
        return None
    if any(_feedback(app_dir, n).get("revisit") and _feedback(app_dir, n).get("build_on") == best for n in dirs):
        return None
    req = read_json(app_dir / "requirements.json")
    evidence = graded_evidence(app_dir, cfg, req)
    data = load_resume(rdir / "resume.yaml")
    gap = ats_gap(data, req, evidence, cfg, _vault_wording(app_dir, cfg), title_ok=title_ok(app_dir))
    total = ats_score(data, req, evidence, cfg)["total"]
    if total >= gap["ceiling"] - float((cfg.get("loop") or {}).get("wide_gap", 10)):
        return None
    grade = read_json(rdir / "grade.json")
    check = read_json(rdir / "check.json") if (rdir / "check.json").exists() else {}
    lines = ats_gap_lines(gap, evidence, data)
    old_ats = {g.get("sentence") for g in grade.get("gaps") or [] if str(g.get("id", "")).startswith("ats.")}
    grade = {**grade, "gaps": [g for g in grade.get("gaps") or [] if not str(g.get("id", "")).startswith("ats.")] + lines}
    nxt = max(dirs) + 1
    feedback = {
        "round": nxt,
        "build_on": best,
        "revisit": True,
        "criticals": check.get("criticals") or [],
        # Today's ATS notes replace the round's own (an older grade words them differently).
        "failed_items": [f for f in grade.get("feedback") or [] if f not in old_ats and not f.startswith(_ATS_NOTES)]
                        + [g["sentence"] for g in lines],
        "warnings": [{"code": w["code"], "message": w["message"], "path": w.get("path", "")} for w in _warnings(check)],
        "sections": _sections({"check": check, "grade": grade}),
    }
    write_json(round_dir(app_dir, nxt) / "feedback.json", feedback)
    log(app_dir, "gap-round", f"round {nxt}: ATS {total} is more than {(cfg.get('loop') or {}).get('wide_gap', 10)} "
        f"under the {gap['ceiling']} the evidence allows; repairing again from round {best}")
    return feedback


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
    # A fit gap (the missing part isn't in the vault) can't be repaired, so it doesn't keep the loop going.
    return [it for it in grade.get("checklist") or [] if it.get("passed") is False and not it.get("fit_gap")]


# Warnings a repair round fixes. The first set is worth a round of its own; the rest
# only ride along with a round that happens anyway.
_ROUND_WARNINGS = {"term_stuffing", "verbatim_posting_copy", "duplicate_bullets", "years_inflation",
                   "title_drift", "letter_length", "skill_name_only"}
_RIDE_WARNINGS = {"skill_only_in_list", "too_many_skills", "bullet_count", "paragraph_count"}


def _warnings(check: dict[str, Any]) -> list[dict[str, Any]]:
    return [w for w in check.get("warnings") or [] if w.get("code") in _ROUND_WARNINGS | _RIDE_WARNINGS]


def _unsure(item: dict[str, Any], sure: float) -> bool:
    """A Jev answer at or under `sure` confidence is a coin flip (Jake, Oct 21 2026)."""
    return item.get("source") == "jev" and (item.get("confidence") or 1.0) <= sure


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
        "items": {it["id"]: it for it in grade.get("checklist") or []},
    }


def _shared_rate(r: dict[str, Any], shared: set[str]) -> float:
    return sum(p_pass(r["items"][i]) for i in shared) / len(shared) if shared else 1.0


def _gain(cur: dict[str, Any], ref: dict[str, Any]) -> float:
    """Score gain over the checklist items both rounds were asked. Each round can ask different
    questions, so extra easy passes would dilute the same failures: the full score rises with
    nothing fixed."""
    shared = cur["items"].keys() & ref["items"].keys()
    if not shared:
        return cur["score"] - ref["score"]

    def score(r: dict[str, Any]) -> float:
        return 0.6 * float(r["ats"] or 0) + 40.0 * _shared_rate(r, shared)

    return score(cur) - score(ref)


def _best(rounds: list[dict[str, Any]]) -> dict[str, Any]:
    """Fewest criticals first, then the best score over the checklist items every round was asked,
    each counted by Jev's probability that it passes. A 50/50 answer then weighs the same whichever
    way it fell (the Amazon BI Engineer draft, Oct 22 2026, kept round 1 over a round 2 that gained
    3.6 ATS points because round 1's coin flips came up yes). The full score breaks ties."""
    shared = set.intersection(*(set(r["items"]) for r in rounds))

    def pick(r: dict[str, Any]) -> float:
        return 0.6 * float(r["ats"] or 0) + 40.0 * _shared_rate(r, shared)

    clean = [r for r in rounds if r["criticals"] == 0]
    if clean:
        return max(clean, key=lambda r: (pick(r), r["score"], -r["round"]))
    return min(rounds, key=lambda r: (r["criticals"], -pick(r), -r["score"], r["round"]))


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

    for c in (cur["check"].get("criticals") or []) + _warnings(cur["check"]):
        add(_section_of(c.get("path", ""), c.get("doc", "")))
        for p in (c.get("data") or {}).get("paths") or []:
            add(_section_of(p, c.get("doc", "")))
    for it in _failed(cur["grade"]):
        for s in it.get("sections") or []:
            add(s)
    for g in cur["grade"].get("gaps") or []:
        for s in g.get("sections") or []:
            add(s)
    return out


def _finish_letter_round(app_dir: Path, rounds: list[dict[str, Any]], cur: dict[str, Any],
                         build_on: Any) -> dict[str, Any]:
    """A letter-only round ends the loop. It keeps the resume it built on, so it becomes the best
    unless the new letter added a critical: comparing Jev's answers on the same resume again would
    only pick between coin flips."""
    base = next((r for r in rounds if r["round"] == build_on), None) or _best(rounds[:-1])
    if cur["criticals"] <= base["criticals"]:
        best, reason = cur, f"letter round done: round {cur['round']} is round {base['round']}'s resume with the new letter"
    else:
        best, reason = base, f"letter round {cur['round']} added a critical: keeping round {base['round']}"
    summaries = [
        {"round": r["round"], "score": r["score"], "criticals": r["criticals"], "failed_items": r["failed_items"]}
        for r in rounds
    ]
    log(app_dir, "loop", f"stop: {reason}", rounds=summaries, best_round=best["round"])
    return {"action": "stop", "best_round": best["round"], "reason": reason, "next_round": None}


def next_round(app_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    app_dir = Path(app_dir)
    nums = _round_numbers(app_dir)
    if not nums:
        raise TailorError(f"no graded rounds in {app_dir / 'drafts'}")
    loop_cfg = cfg.get("loop") or {}
    # A Jev answer near 50/50 is a coin flip, not a regression (Jake, Oct 21 2026).
    sure = loop_cfg.get("regression_min_confidence", 0.6)
    rounds = [_load(app_dir, n) for n in nums]
    cur, prev = rounds[-1], rounds[:-1]
    best = _best(rounds)

    letter_only = _feedback(app_dir, cur["round"])
    if letter_only.get("letter_only") and prev:
        return _finish_letter_round(app_dir, rounds, cur, letter_only.get("build_on"))

    # Jake, Oct 23 2026: more than `wide_gap` points under what the evidence allows isn't acceptable,
    # so while the best round is that far off and the last round still raised its ATS, the loop gets
    # up to `max_rounds_wide_gap` drafts.
    max_rounds = loop_cfg.get("max_rounds", 3)
    if _wide_gap(best, loop_cfg) and (not prev or (best["ats"] or 0) > (_best(prev)["ats"] or 0)):
        max_rounds = max(max_rounds, loop_cfg.get("max_rounds_wide_gap", 5))
    min_gain = loop_cfg.get("min_gain", 2.0)
    target = cfg.get("target_score", 80)
    # A wording gap (hard skills the vault backs but the resume doesn't say) earns more rounds;
    # a fit gap doesn't, since repairing harder would only stuff keywords.
    needs_ats = cur["grade"].get("needs_ats_repair")
    if needs_ats is None:
        needs_ats = (cur["ats"] or 0) < cfg.get("ats_floor", 70)

    reason: str | None = None
    # The round the next repair builds on: normally the last one, but a round that regressed is
    # set aside and the repair starts again from the best round so far.
    src, regressed = cur, None
    if cur["criticals"] == 0 and cur["failed_items"] == 0 and (cur["ats"] or 0) >= target:
        reason = "all checks pass and the ATS score meets the target"
    elif prev:
        ref = _best(prev)
        newly_failed = {i for i in cur["failed_ids"] & ref["passed_ids"] if not _unsure(cur["items"][i], sure)}
        if cur["criticals"] > ref["criticals"]:
            regressed = f"regression: round {cur['round']} has more criticals than round {ref['round']}"
        elif newly_failed:
            regressed = f"regression: an item that passed in round {ref['round']} now fails"
        best_needs_ats = best["grade"].get("needs_ats_repair")
        if best_needs_ats is None:
            best_needs_ats = (best["ats"] or 0) < cfg.get("ats_floor", 70)
        if regressed and best_needs_ats and len(rounds) < max_rounds:
            # A wording gap is still open (Jake's ATS floor: repair until within 5 of the ceiling or
            # 70), so a bad round doesn't end the loop: the next one builds on the best round so far
            # (REW.ca Data Engineer, Oct 20 2026, stopped at ATS 57.1 with 75.3 reachable).
            src, needs_ats = best, best_needs_ats
        elif regressed:
            reason = regressed
        # With a wording gap left, a small gain still earns another round, up to the round limit.
        elif _gain(cur, ref) < min_gain and not needs_ats:
            reason = f"score gain under {min_gain} points over round {ref['round']}"
    feedback = list(src["grade"].get("feedback") or [])
    if reason is None and len(rounds) >= max_rounds:
        reason = f"round limit of {max_rounds} reached"
    # Without a wording gap the "use the posting's words" line is advice, not a reason for a round.
    ats_lines = {g.get("sentence") for g in src["grade"].get("gaps") or [] if g.get("id") in ("ats.unused", "ats.title")}
    # The soft-skill note rides along with a round that happens anyway, never starts one.
    soft_lines = {g.get("sentence") for g in src["grade"].get("gaps") or [] if g.get("id") == "ats.soft"}
    repairable = [f for f in feedback if f not in soft_lines and (needs_ats or f not in ats_lines)]
    # A skill the draft itself added to the list with no bullet behind it is worth a round too.
    round_warnings = [w for w in _warnings(src["check"]) if w.get("code") in _ROUND_WARNINGS
                      or (w.get("code") == "skill_only_in_list" and (w.get("data") or {}).get("added"))]
    if reason is None and not (src["check"].get("criticals") or repairable or round_warnings):
        reason = "nothing left to repair"

    summaries = [
        {"round": r["round"], "score": r["score"], "criticals": r["criticals"], "failed_items": r["failed_items"]}
        for r in rounds
    ]
    action = "stop" if reason else "repair"
    nxt = None if reason else cur["round"] + 1
    if not reason:
        reason = (f"round {cur['round']} regressed, but a wording gap remains: repairing again from round {src['round']}"
                  if regressed else "failed items or criticals remain and the last round still gained")
        write_json(
            round_dir(app_dir, nxt) / "feedback.json",
            {
                "round": nxt,
                "build_on": src["round"],
                "criticals": src["check"].get("criticals") or [],
                "failed_items": feedback,
                "warnings": [{"code": w["code"], "message": w["message"], "path": w.get("path", "")}
                             for w in _warnings(src["check"])],
                "sections": _sections(src),
            },
        )
    log(app_dir, "loop", f"{action}: {reason}", rounds=summaries, best_round=best["round"])
    return {"action": action, "best_round": best["round"], "reason": reason, "next_round": nxt}
