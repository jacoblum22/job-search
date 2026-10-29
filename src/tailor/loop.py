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


LETTER_SOFT = ("Name these soft skills in the letter, in the posting's own word, inside a story the letter "
               "already tells or one a cited vault passage shows (never as an adjective about the candidate, "
               "never a sentence that only names it): ")


def soft_for_letter(app_dir: Path, rnd: int, cfg: dict[str, Any]) -> list[str]:
    """Soft skills the posting asks for and the vault shows, that neither the resume nor the letter
    of round `rnd` names (Jake, Oct 23 2026: REW.ca's letter told teamwork stories but never said
    "teamwork", and with its rounds used up nothing asked for it)."""
    from src.tailor.grade import regrade

    return list((regrade(app_dir, rnd, cfg) or {}).get("unused_soft_terms") or [])


def soft_in_letter(app_dir: Path, rnd: int, cfg: dict[str, Any]) -> list[str]:
    """Soft skills the posting asks for and the vault shows that only round `rnd`'s letter names: a
    letter round rewriting it must keep them (REW.ca, Oct 23 2026: working "teamwork" in dropped
    "knowledge sharing", and nothing said so)."""
    from src.tailor.grade import regrade

    return list((regrade(app_dir, rnd, cfg) or {}).get("letter_soft_terms") or [])


LETTER_KEEP = "Keep naming these soft skills the letter already names, in the same word: "


def letter_round(app_dir: Path, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Ask for a letter-only round when the best round's letter fails a letter check under today's
    rules (the 250-word rule of Oct 22 2026 flagged letters drafted before it), or when neither draft
    names a soft skill the posting asks for and the vault shows (`soft_for_letter`). The resume carries
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
    soft = soft_for_letter(app_dir, best, cfg)
    if not warnings and not soft:
        return None
    keep = soft_in_letter(app_dir, best, cfg)
    nxt = max(dirs) + 1
    feedback = {
        "round": nxt,
        "build_on": best,
        "letter_only": True,
        "criticals": [],
        "failed_items": ([LETTER_SOFT + ", ".join(soft) + "."] if soft else [])
                        + ([LETTER_KEEP + ", ".join(keep) + "."] if keep else []),
        "warnings": [{"code": w["code"], "message": w["message"], "path": w.get("path", "")} for w in warnings],
        "sections": ["letter"],
        "keep_soft": keep,
    }
    write_json(round_dir(app_dir, nxt) / "feedback.json", feedback)
    log(app_dir, "letter-round", f"round {nxt}: letter only, on round {best}: "
        + "; ".join([w["code"] for w in warnings] + (["soft skills: " + ", ".join(soft)] if soft else [])))
    return feedback


_ATS_NOTES = ("Use the posting's own words", "Open the summary's first sentence with the job title",
              "Soft skills the vault shows", "These required terms are only in the summary")


def _wide_gap(r: dict[str, Any], loop_cfg: dict[str, Any]) -> bool:
    ceiling = r["grade"].get("ats_ceiling")
    return ceiling is not None and (r["ats"] or 0) < float(ceiling) - float(loop_cfg.get("wide_gap", 8))


def gap_round(app_dir: Path, cfg: dict[str, Any]) -> dict[str, Any] | None:
    """Ask for one more repair round when the best round's ATS, scored under today's rules, is more
    than `loop.wide_gap` points under what the evidence allows and the resume leaves backed terms
    unsaid (Jake, Oct 23 2026: VCH Junior Data Developer stopped at 59.2 with about 71 reachable).
    It builds on the best round. Writes `drafts/r<N>/feedback.json` and returns it, or None. One
    try per best round, like `letter_round`."""
    from src.resume import load_resume
    from src.tailor.grade import (_vault_wording, ats_gap, ats_gap_lines, ats_score, graded_evidence, title_ok,
                                  unsaid_soft)

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
    total = ats_score(data, req, evidence, cfg, title_ok(app_dir))["total"]
    if total >= gap["ceiling"] - float((cfg.get("loop") or {}).get("wide_gap", 8)):
        return None
    grade = read_json(rdir / "grade.json")
    check = read_json(rdir / "check.json") if (rdir / "check.json").exists() else {}
    letter = read_json(rdir / "cover-letter.json") if (rdir / "cover-letter.json").exists() else None
    unsaid_soft(gap, grade.get("checklist") or [], req, letter)
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
    log(app_dir, "gap-round", f"round {nxt}: ATS {total} is more than {(cfg.get('loop') or {}).get('wide_gap', 8)} "
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
                   "title_drift", "letter_length", "skill_name_only", "directed_opener", "test_count"}
# Pipeline audit, Oct 29 2026: AI-style phrases, a term the base covered that the draft lost, and
# Jev's doubt about a line were shown every round and never reached a repair round (PointClickCare
# carried 3 phrase warnings through all 3 rounds; humanize found them only after the outside review).
_RIDE_WARNINGS = {"skill_only_in_list", "too_many_skills", "bullet_count", "paragraph_count",
                  "ai_phrase", "keyword_coverage_dropped", "jev_unsupported"}


def _warnings(check: dict[str, Any]) -> list[dict[str, Any]]:
    doubts = [f for f in check.get("flags") or [] if f.get("code") == "jev_unsupported"]
    return [w for w in (check.get("warnings") or []) + doubts if w.get("code") in _ROUND_WARNINGS | _RIDE_WARNINGS]


def _unsure(item: dict[str, Any], sure: float) -> bool:
    """A Jev answer at or under `sure` confidence is a coin flip (Jake, Oct 21 2026)."""
    return item.get("source") == "jev" and (item.get("confidence") or 1.0) <= sure


def _todays_ats(app_dir: Path, cfg: dict[str, Any]):
    """A function giving round n's ATS scored under today's rules, or None when it can't be.

    Each grade.json keeps the ATS of the day it was graded, and the rules and the ceilings move
    (VCH Junior Data Developer's gap round changed 2 resume words and "gained" 10.5 ATS points,
    mostly from newer rules; pipeline audit, Oct 29 2026), so rounds are compared on today's."""
    try:
        from src.resume import load_resume
        from src.tailor.grade import ats_score, graded_evidence, title_ok

        req = read_json(app_dir / "requirements.json")
        evidence = graded_evidence(app_dir, cfg, req)
        title = title_ok(app_dir)
    except Exception:  # noqa: BLE001 - missing inputs: keep each round's own number
        return lambda n: None

    def score(n: int) -> float | None:
        try:
            return ats_score(load_resume(round_dir(app_dir, n) / "resume.yaml"), req, evidence, cfg, title)["total"]
        except Exception:  # noqa: BLE001
            return None

    return score


def _draft_text(app_dir: Path, n: int) -> str | None:
    """Round n's resume and letter as plain text (no ids or sources), or None when unreadable."""
    from src.resume import load_resume
    from src.tailor.grade import letter_text, resume_text

    d = round_dir(app_dir, n)
    try:
        letter = read_json(d / "cover-letter.json") if (d / "cover-letter.json").exists() else None
        return resume_text(load_resume(d / "resume.yaml")) + "\n---\n" + (letter_text(letter) if letter else "")
    except Exception:  # noqa: BLE001
        return None


def unchanged(app_dir: Path, n: int, on: int) -> bool:
    """True when round n left the resume and letter as round `on` had them (four repair rounds in
    October changed nothing and were graded again, two of them winning on Jev's coin flips)."""
    a, b = _draft_text(app_dir, n), _draft_text(app_dir, on)
    return a is not None and a == b


def _load(app_dir: Path, n: int, today=None) -> dict[str, Any]:
    d = round_dir(app_dir, n)
    check = read_json(d / "check.json")
    grade = read_json(d / "grade.json")
    failed = _failed(grade)
    ats = (grade.get("ats") or {}).get("total")
    score = float(grade.get("score", 0))
    now = today(n) if today else None
    if now is not None and ats is not None:
        items = grade.get("checklist") or []
        rate = sum(p_pass(it) for it in items) / len(items) if items else 1.0
        ats, score = now, round(0.6 * now + 0.4 * rate * 100, 1)
    return {
        "round": n,
        "score": score,
        "ats": ats,
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
                         feedback: dict[str, Any], review: bool = False) -> dict[str, Any]:
    """A letter-only round ends the loop. It keeps the resume it built on, so it becomes the best
    unless the new letter added a critical: comparing Jev's answers on the same resume again would
    only pick between coin flips. A review round (outside.py) ends it the same way, whatever its
    ATS estimate: Jake, Oct 29 2026, in his own review chats the revision always goes back to the
    reviewer, so a review round that cost ATS points is never thrown away. A soft skill the old
    letter named that the new one dropped is named in the reason, so the run reports it."""
    from src.tailor import wording
    from src.tailor.grade import letter_text

    # A review fix round builds on the review round but is judged against the round the review read.
    build_on = feedback.get("compare_to", feedback.get("build_on"))
    base = next((r for r in rounds if r["round"] == build_on), None) or _best(rounds[:-1])
    if (review and feedback.get("review") and cur["criticals"] > base["criticals"]
            and not unchanged(app_dir, cur["round"], base["round"])):
        return _review_fix(app_dir, rounds, cur, base, feedback)
    if cur["criticals"] <= base["criticals"]:
        what = "the outside review acted on" if review else "round {0}'s resume with the new letter".format(base["round"])
        best, reason = cur, f"{'review' if review else 'letter'} round done: round {cur['round']} is {what}"
    else:
        best, reason = base, f"{'review' if review else 'letter'} round {cur['round']} added a critical: keeping round {base['round']}"
    path = round_dir(app_dir, cur["round"]) / "cover-letter.json"
    said = letter_text(read_json(path)) if path.exists() else ""
    lost = [t for t in feedback.get("keep_soft") or [] if not wording.same(t, said)]
    if lost:
        reason += f"; the new letter no longer names {', '.join(lost)}, which round {base['round']}'s did"
    summaries = [
        {"round": r["round"], "score": r["score"], "criticals": r["criticals"], "failed_items": r["failed_items"]}
        for r in rounds
    ]
    log(app_dir, "loop", f"stop: {reason}", rounds=summaries, best_round=best["round"])
    return {"action": "stop", "best_round": best["round"], "reason": reason, "next_round": None}


def _review_fix(app_dir: Path, rounds: list[dict[str, Any]], cur: dict[str, Any], base: dict[str, Any],
                feedback: dict[str, Any]) -> dict[str, Any]:
    """A review round that added a critical gets one round fixing only the flagged lines, built on
    it, instead of losing every change it made (Infoblox, Oct 28 2026: "AI agent" wording drew two
    invented_skill criticals and about 240 words of review fixes were thrown away). The fix round is
    judged against the round the review read, like the review round itself."""
    crit = cur["check"].get("criticals") or []
    nxt = cur["round"] + 1
    fb = {
        "round": nxt,
        "build_on": cur["round"],
        "compare_to": base["round"],
        "review_fix": True,
        "review_pass": feedback.get("review_pass", 1),
        "criticals": crit,
        "failed_items": [],
        "warnings": [],
        "sections": _sections({"check": {"criticals": crit}, "grade": {}}),
    }
    write_json(round_dir(app_dir, nxt) / "feedback.json", fb)
    reason = (f"review round {cur['round']} added {cur['criticals'] - base['criticals']} critical(s): "
              f"round {nxt} fixes only those lines and keeps the rest of the review's changes")
    summaries = [{"round": r["round"], "score": r["score"], "criticals": r["criticals"], "failed_items": r["failed_items"]}
                 for r in rounds]
    log(app_dir, "loop", f"repair: {reason}", rounds=summaries, best_round=base["round"])
    return {"action": "repair", "best_round": base["round"], "reason": reason, "next_round": nxt}


def next_round(app_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    app_dir = Path(app_dir)
    nums = _round_numbers(app_dir)
    if not nums:
        raise TailorError(f"no graded rounds in {app_dir / 'drafts'}")
    loop_cfg = cfg.get("loop") or {}
    # A Jev answer near 50/50 is a coin flip, not a regression (Jake, Oct 21 2026).
    sure = loop_cfg.get("regression_min_confidence", 0.6)
    today = _todays_ats(app_dir, cfg)
    rounds = [_load(app_dir, n, today) for n in nums]
    cur, prev = rounds[-1], rounds[:-1]
    best = _best(rounds)

    side = _feedback(app_dir, cur["round"])
    if (side.get("letter_only") or side.get("review") or side.get("review_fix")) and prev:
        return _finish_letter_round(app_dir, rounds, cur, side, review=bool(side.get("review") or side.get("review_fix")))

    # Jake, Oct 23 2026: more than `wide_gap` points under what the evidence allows isn't acceptable,
    # so while the best round is that far off and the last round still raised its ATS, the loop gets
    # up to `max_rounds_wide_gap` drafts. Jake, Oct 28 2026: 8 points, not 10 (Nexthop new grad
    # stopped at the 3-draft limit 8.5 under, after a round that gained 3.2).
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
    built = int(side.get("build_on") or cur["round"] - 1)
    if prev and unchanged(app_dir, cur["round"], built):
        # Repair found nothing it could honestly change; another round would only tinker.
        reason = f"round {cur['round']} left the resume and letter as round {built} had them"
    elif cur["criticals"] == 0 and cur["failed_items"] == 0 and (cur["ats"] or 0) >= target:
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
        # A round `pending` asked for (gap_round, letter_round) can take a folder past the limit.
        reason = f"round limit of {max_rounds} reached" + (
            f" ({len(rounds)} drafts with the one pending asked for)" if len(rounds) > max_rounds else "")
    # Without a wording gap the "use the posting's words" line is advice, not a reason for a round.
    ats_lines = {g.get("sentence") for g in src["grade"].get("gaps") or [] if g.get("id") in ("ats.unused", "ats.summary_only", "ats.title")}
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
