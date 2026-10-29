"""Step 10: the review packet (fit-notes.md, check.md), plus approval and outcomes.

check.md is the human gate: every remaining issue is a checklist line the reviewer
ticks, and `approve` refuses until none is left unticked.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.resume import load_resume
from src.tailor import TailorError, appdir, explain, outside, rejects, review, store
from src.tailor.paths import resolve
from src.tailor.sources import load_index, load_titles

OUTCOMES = ("applied", "callback", "interview", "offer", "rejected", "no_reply")



def _opt_json(path: Path) -> Any:
    return appdir.read_json(path) if path.exists() else None


def _best_round(app_dir: Path, app: dict[str, Any]) -> int | None:
    if app.get("best_round"):
        return int(app["best_round"])
    found = [int(p.name[1:]) for p in (app_dir / "drafts").glob("r[0-9]*") if p.is_dir()]
    found += [int(r["round"]) for r in app.get("rounds") or [] if "round" in r]
    return max(found) if found else None


def _base_id(app_dir: Path, app: dict[str, Any], buckets: dict[str, Any]) -> str | None:
    plan = _opt_json(app_dir / "plan.json") or {}
    base = app.get("base_id") or plan.get("base_id")
    if base in buckets:
        return base
    return next(iter(buckets), None)


def _pct(v: Any) -> str:
    return f"{v:.1f}%" if isinstance(v, (int, float)) else "n/a"


def _fit_notes(app: dict[str, Any], evidence: dict[str, Any], reqs: dict[str, Any] | None,
               base: str | None) -> str:
    req_text = {r["id"]: r for r in (reqs or {}).get("requirements", []) if "id" in r}
    lines = [f"# Fit notes: {app.get('title', '')} at {app.get('company', '')}", ""]
    lines += ["## Requirements", ""]
    weak: list[str] = []
    for r in evidence.get("requirements", []):
        info = req_text.get(r.get("id"), {})
        text = info.get("text") or r.get("id", "?")
        kind = info.get("kind", "")
        passages = ", ".join(r.get("passages") or []) or "none"
        strength = r.get("strength", 0)
        lines.append(f"- **{text}**{f' ({kind})' if kind else ''}: {r.get('status', 'missing')}, "
                     f"strength {strength}; passages: {passages}")
        if kind == "must" and strength <= 1:
            weak.append(f"Must-have: {text} (strength {strength})")
    bucket = dict((evidence.get("buckets") or {}).get(base or "", {}))
    if "present" in evidence:
        # The buckets are from the evidence step; a plan add or a set-aside since then moves a term
        # (REW.ca, Oct 23 2026: "data accuracy" sat under "not backed" while check.md and the grade
        # counted the plan's match for it).
        present = set(evidence.get("present") or [])
        now_backed = [t for t in bucket.get("non_injectable") or [] if t in present]
        dropped = [t for t in bucket.get("injectable") or [] if t not in present]
        bucket["injectable"] = [t for t in bucket.get("injectable") or [] if t in present] + now_backed
        bucket["non_injectable"] = [t for t in bucket.get("non_injectable") or [] if t not in present] + dropped
    lines += ["", f"## Keyword buckets (base: {base or 'none'})", ""]
    for key, label in (("matched", "Already in the resume"), ("injectable", "Can be added (backed by the vault)"),
                       ("non_injectable", "Not backed by the vault")):
        lines.append(f"- {label}: {', '.join(bucket.get(key) or []) or 'none'}")
    lines += ["", f"Match: {_pct(bucket.get('current_pct'))} now, {_pct(bucket.get('potential_pct'))} potential.", ""]
    prep = [f"Term not in your record: {t}" for t in bucket.get("non_injectable") or []] + weak
    lines += ["## Interview prep", ""]
    lines += [f"- {p}" for p in prep] or ["- Nothing flagged."]
    return "\n".join(lines) + "\n"


def _final_resume(rd: Path | None, app_dir: Path) -> tuple[Path | None, dict[str, Any] | None]:
    """The resume that was rendered: the humanized one if present, else the best round's."""
    path = appdir.humanized(app_dir, "resume.yaml")
    if path is None and rd is not None:
        path = rd / "resume.yaml"
    if path is None or not path.exists():
        return None, None
    try:
        return path, load_resume(path)
    except Exception:  # a broken draft still gets a packet; the checker reports it
        return path, None


def _vault_index(cfg: dict[str, Any]) -> dict[str, dict] | None:
    """Passages by id, each with its file's title for readable labels; None without an index."""
    try:
        index = load_index(cfg)
    except TailorError:
        return None
    titles = load_titles(cfg)
    return {pid: {**p, "file_title": titles.get(p.get("file", ""))} for pid, p in index.items()}


def _changes(rd: Path | None, app_dir: Path, cfg: dict[str, Any]) -> list[str]:
    """Line-by-line difference between the base resume and the final one, named in plain words."""
    from src.tailor.checks import units  # local: checks pulls in the heavier metrics stack
    from src.tailor.edits import load_base

    final_path, final_data = _final_resume(rd, app_dir)
    if final_data is None:
        return []
    try:
        base_data = load_base(app_dir, cfg)
    except TailorError:
        return []
    base = dict(units(base_data))
    final = dict(units(final_data))
    out: list[str] = []
    for path, after in final.items():
        before = base.get(path)
        label = explain.path_label(path, final_data)
        if before is None:
            out.append(f"- **{label}** (added)\n  - After: {after}")
        elif before != after:
            out.append(f"- **{label}**\n  - Before: {before}\n  - After: {after}")
    out += [f"- **{explain.path_label(path, base_data)}** (removed)\n  - Before: {before}"
            for path, before in base.items() if path not in final]
    return out


def _drop_humanized(issues: list[dict[str, Any]], app_dir: Path) -> list[dict[str, Any]]:
    """Leave out AI-style phrase warnings once the humanize pass has run. check.json judged the
    round's draft, but that pass is where these are handled: it rewrites what it can, and one it
    left alone isn't worth a review line (Jake, Oct 22 2026)."""
    if appdir.humanized(app_dir, "resume.yaml") is None:
        return issues
    return [it for it in issues if it.get("code") != "ai_phrase"]


def _note(text: str) -> list[str]:
    return [f"> {text}", ""]


def _reviewer_lines(app_dir: Path) -> list[str]:
    """The outside reviewer's verdict, questions only Jake can answer, claims to verify and the
    interview questions they invite, as his claude.ai reviews put them (Jake, Oct 29 2026). Plain
    lines, no boxes: nothing here blocks approval."""
    s = outside.summary(app_dir)
    if not s:
        return []
    verdict = {"ready": "Ready to submit", "not yet": "Not yet"}.get(s["verdict"] or "", "No verdict given")
    text = f" {s['verdict_text']}" if s.get("verdict_text") else ""
    lines = ["## Outside reviewer", ""] + _note(explain.REVIEWER)
    lines += [f"Verdict after {s['passes']} pass{'es' if s['passes'] > 1 else ''}: {verdict}.{text}", ""]
    for key, title in (("questions", "Questions only you can answer"), ("claims", "Claims to verify before sending"),
                       ("interview", "Interview questions these claims invite")):
        if s[key]:
            lines += [f"{title}:"] + [f"- {q}" for q in s[key]] + [""]
    return lines


def _check_md(app: dict[str, Any], rd: Path | None, app_dir: Path,
              check: dict[str, Any] | None, cfg: dict[str, Any], grade: dict[str, Any] | None) -> str:
    from src.tailor.checks import units  # local: checks pulls in the heavier metrics stack

    """check.md: every section opens with a "> " note saying what it is and what to decide, and
    every line says what it's about in plain words (explain.py). Box lines keep their fixed shape
    because approve and the dashboard server read them."""
    gate = app.get("gate") or {}
    gate_flags = gate.get("flags") or []
    reqs_json = _opt_json(app_dir / "requirements.json") or {}
    reqs = {r["id"]: r for r in reqs_json.get("requirements") or [] if "id" in r}
    _, data = _final_resume(rd, app_dir)
    index = _vault_index(cfg)
    lines = ["# Check", ""] + _note(explain.INTRO) + _reviewer_lines(app_dir)
    if gate.get("checked") is False:
        lines += ["Gate not checked: Jev is not configured.", ""]
    if gate_flags:
        lines += ["## Gate flags: review before applying", ""] + _note(explain.GATE)
        for f in gate_flags:
            head, details = explain.gate_flag(f)
            lines.append(f"- [ ] Reviewed  {head}")
            lines += [f"  - {d}" for d in details]
        lines.append("")
    dropped = ((_opt_json(app_dir / "final" / "parse.json") or {}).get("dropped")) or []
    if dropped:
        # Rendering cut these to fit one page; nobody chose to, so say so.
        texts = dict(units(data)) if data else {}
        lines += ["## Bullets cut to fit one page", ""]
        lines += _note("The resume ran past one page, so rendering left out the least relevant bullets below. "
                       "They aren't in the PDF. Check you're happy without them, or shorten other lines and render again.")
        for path in dropped:
            lines.append(f"- [ ] Reviewed  {explain.path_label(path, data)}: {texts.get(path, path)}")
        lines.append("")
    floor = float(cfg.get("ats_floor", 70))
    ats_total = ((grade or {}).get("ats") or {}).get("total")
    if isinstance(ats_total, (int, float)) and ats_total < floor:
        # Never send below the floor without a look, and say which kind of gap it is.
        unused = grade.get("unused_terms") or []
        unused_soft = grade.get("unused_soft_terms") or []
        unbacked = grade.get("unbacked_terms") or []
        ceiling = grade.get("ats_ceiling")
        if grade.get("fit_gap"):
            lines += ["## Weaker fit: review before applying", ""]
            lines += _note(f"{explain.FIT} {explain.FIT_GAP}")
            lines.append(f"- [ ] Reviewed  ATS {ats_total} out of 100. Even using every skill your vault backs, "
                         f"the best this resume could reach is about {ceiling}, under the {floor:g} minimum.")
        elif unused or grade.get("title_missing"):
            lines += [f"## ATS score below {floor:g}: review before applying", ""]
            lines += _note(f"{explain.FIT} {explain.WORDING_GAP}")
            title = grade.get("title_missing")
            lines.append(f"- [ ] Reviewed  ATS {ats_total} is below the {floor:g} minimum"
                         + (f"; your evidence could reach about {ceiling}, so the gap is wording."
                            if ceiling is not None else ".")
                         + (f' The summary doesn\'t open with the job title "{title}" yet.' if title else ""))
        else:
            # No backed term is left to work in, so calling it a wording gap would promise a fix that isn't there.
            lines += [f"## ATS score below {floor:g}: review before applying", ""]
            lines += _note(f"{explain.FIT} {explain.NO_WORDING_LEFT}")
            lines.append(f"- [ ] Reviewed  ATS {ats_total} is below the {floor:g} minimum"
                         + (f"; your evidence could reach about {ceiling}, but no backed term is left to add."
                            if ceiling is not None else "."))

        def term_list(label: str, terms: list[str]) -> None:
            lines.append(f"  - {label}:")
            lines.extend([f"    - {t}" for t in terms] or ["    - None"])

        term_list("The posting asks for these and your vault doesn't show them in these words", unbacked)
        term_list("Your vault shows these but the resume doesn't use the posting's words", unused)
        if unused_soft:
            term_list("Soft skills your vault shows that neither the resume nor the letter names (they don't "
                      "count in the ATS score; the letter is the place for the ones no line fits)", unused_soft)
        if unbacked:
            lines.append("  - If you do have something in the first list, add it to your experience vault and "
                         "rerun from the evidence step: the resume can only claim what the vault shows.")
        lines.append("")
    # Sections with buttons come first; the read-only ones (grade, changes, handled) go after them
    # so nothing to decide sits below something with nothing to decide (Jake, Oct 22 2026).
    info = ["", "## Grade", ""] + _note(explain.GRADE)
    if grade:
        ats = grade.get("ats") or {}
        comps = ", ".join(f"{k} {v}" for k, v in (ats.get("components") or {}).items())
        info.append(f"- Score: {grade.get('score', 'n/a')}")
        info.append(f"- ATS estimate: {ats.get('total', 'n/a')}{f' ({comps})' if comps else ''}")
        asked = [it for it in grade.get("checklist") or [] if it.get("passed") is not None]
        if asked:
            info.append(f"- Jev's checks passed: {sum(1 for it in asked if it['passed'])} of {len(asked)}")
        if grade.get("stuffing"):
            info.append("- Keyword stuffing suspected: the score is high only because terms repeat")
    else:
        info.append("- No grade available")
    passes = sorted({1, *outside.done_passes(app_dir)})
    if any(outside.response(app_dir, n) for n in passes):
        info += ["", "## Outside review", ""] + _note(explain.OUTSIDE)
        for n in passes:
            replies = outside.response(app_dir, n)
            if replies and len(passes) > 1:
                info.append(f"Pass {n}:")
            for r in replies:
                done = "Changed" if str(r.get("action", "")).lower().startswith("change") else "Left as is"
                why = f": {r['why']}" if r.get("why") else ""
                info.append(f"- {done}: {r['note']}{why}")
    # Jev's "no" answers are advice; listing them lets the candidate catch a false rejection.
    said_no = [it for it in (grade or {}).get("checklist") or [] if it.get("passed") is False]
    ev_no = (_opt_json(app_dir / "evidence.json") or {}).get("jev_said_no") or []
    if said_no or ev_no:
        lines += ["", "## Jev said no: check for false rejections", ""] + _note(explain.JEV_NO)
        for it in said_no:
            head, details = explain.jev_item(it, reqs, data, str(reqs_json.get("title") or app.get("title") or ""),
                                             str(reqs_json.get("company") or app.get("company") or ""))
            lines.append(f"- [ ] Reviewed  {head}")
            lines += [f"  - {d}" for d in details]
        if ev_no:
            lines += [""] + _note(explain.JEV_NO_EVIDENCE)
            lines += [f"- {explain.evidence_no(n, index)}" for n in ev_no]
    drops = (_opt_json(app_dir / "plan.json") or {}).get("evidence_drops") or []
    if drops:
        new = {(r["term"].lower(), r["passage"]) for r in rejects.load(cfg)
               if r.get("job_id") == app.get("job_id") and not r.get("undone")}
        lines += ["", "## Evidence set aside", ""] + _note(explain.DROPS)
        for d in drops:
            term, pid = str(d.get("term", "?")), str(d.get("passage", "?"))
            head, details = explain.drop(d, index, (term.lower(), pid) in new)
            lines.append(f"- [ ] Set aside  - [ ] Undo  {head} <!-- undo: {term} | {pid} -->")
            lines += [f"  - {x}" for x in details]
    lines += _suggestions(app_dir, reqs, index, cfg)
    base_id = app.get("base_id") or (_opt_json(app_dir / "plan.json") or {}).get("base_id") or "chosen"
    info += ["", "## Changes from the base", ""] + _note(explain.CHANGES.format(base=base_id))
    info += _changes(rd, app_dir, cfg) or ["- No changes"]
    issues = [it for sev in ("criticals", "warnings", "flags") for it in (check or {}).get(sev) or []]
    issues = _drop_humanized(issues, app_dir)
    # A skill already in the base's list was approved with the base; only one the draft added
    # needs a look (older check.json files don't say, so those stay).
    issues = [it for it in issues if not (it.get("code") == "skill_only_in_list"
                                          and (it.get("data") or {}).get("added") is False)]
    lines += ["", "## Remaining issues", ""] + _note(explain.ISSUES)
    boxed = [it for it in issues if not explain.is_note(it)]
    for it in boxed:
        head, details = explain.issue(it, data, index)
        lines.append(f"- [ ] Keep  - [ ] Remove  {head}")
        lines += [f"  - {d}" for d in details]
    if not boxed:
        lines.append("- None")
    notes = [it for it in issues if explain.is_note(it)]
    if notes:
        info += ["", "## Already handled", ""] + _note(explain.NOTES)
        info += [f"- {explain.note(it, data, index)}" for it in notes]
    lines += info
    return "\n".join(lines) + "\n"


def _confirm_line(key: str, pid: str, head: str) -> str:
    # The pair in the comment is what approve records (rejects.apply_confirms).
    return f"- [ ] Doesn't show it  - [ ] This shows it  {head} <!-- confirm: {key} | {pid} -->"


def _suggestions(app_dir: Path, reqs: dict[str, dict], index: dict[str, dict] | None,
                 cfg: dict[str, Any]) -> list[str]:
    """The plan's evidence adds, and passages Jev came close to accepting for requirements the
    vault backs badly: each a "Doesn't show it" / "This shows it" pair."""
    lines: list[str] = []
    adds = (_opt_json(app_dir / "plan.json") or {}).get("evidence_adds") or []
    adds = [d for d in adds if isinstance(d, dict) and d.get("term") and d.get("passage")]
    # Another job's plan add counts here too (the grade's rejects.confirmed), so the repair can lean
    # on it; until the candidate decides it, ask here as well (REW.ca Data Engineer, Oct 22 2026: a
    # term from another job's plan was pushed into a bullet with no line here).
    mine = {(rejects.key(d["term"]), str(d["passage"])) for d in adds}
    reqs_json = _opt_json(app_dir / "requirements.json") or {}
    asked = {rejects.key(t) for r in reqs.values() for t in r.get("terms") or [] if isinstance(t, str)}
    asked |= {rejects.key(k["term"]) for k in reqs_json.get("keywords") or [] if isinstance(k, dict) and k.get("term")}
    adds += [c for k, c in rejects.confirmed(cfg, app_dir).items()
             if c.get("source") == "plan" and k not in mine and k[0] in asked]
    if adds:
        lines += ["", "## Evidence the plan added", ""] + _note(explain.ADDS)
        for d in adds:
            head, details = explain.add(d, index)
            lines.append(_confirm_line(rejects.key(d["term"]), str(d["passage"]), head))
            lines += [f"  - {x}" for x in details]
    done = {(rejects.key(d["term"]), str(d["passage"])) for d in adds}
    done |= set(rejects.pairs(cfg, app_dir)) | set(rejects.confirmed(cfg, app_dir))  # already decided
    sugg = []
    for e in (_opt_json(app_dir / "evidence.json") or {}).get("requirements") or []:
        key = e.get("confirm_key")
        for c in e.get("candidates") or [] if key else []:
            if (key, c.get("passage")) not in done:
                done.add((key, c["passage"]))
                sugg.append((key, c, reqs.get(e.get("id"), {}).get("text", "")))
    if sugg:
        lines += ["", "## Could these show it?", ""] + _note(explain.SUGGESTED)
        for key, c, req_text in sugg:
            head, details = explain.suggestion(key, c["passage"], c.get("value"), req_text, index)
            lines.append(_confirm_line(key, c["passage"], head))
            lines += [f"  - {x}" for x in details]
    return lines


def run_packet(app_dir: Path, cfg: dict[str, Any], recheck: bool = False) -> dict[str, Any]:
    """Write fit-notes.md and check.md and move the application to review. With `recheck`
    (repacket), the code-only checks and the ATS score run again under today's rules instead of
    being read back."""
    app = appdir.load_app(app_dir)
    evidence = appdir.read_json(app_dir / "evidence.json")
    rnd = _best_round(app_dir, app)
    rd = appdir.round_dir(app_dir, rnd) if rnd else None
    check = _opt_json(rd / "check.json") if rd else None
    if recheck and check is not None:
        from src.tailor.checks import recheck as run_recheck

        check = run_recheck(app_dir, rnd, cfg)
    grade = _opt_json(rd / "grade.json") if rd else None
    if recheck and grade is not None:
        from src.tailor.grade import regrade

        grade = regrade(app_dir, rnd, cfg) or grade
    base = _base_id(app_dir, app, evidence.get("buckets") or {})
    from src.tailor.grade import graded_evidence

    reqs = _opt_json(app_dir / "requirements.json")
    # Fit notes read the evidence as the grade and check.md do: set-asides out, plan adds in.
    (app_dir / "fit-notes.md").write_text(
        _fit_notes(app, graded_evidence(app_dir, cfg, reqs or {}), reqs, base), encoding="utf-8")
    text = _check_md(app, rd, app_dir, check, cfg, grade)
    if (app_dir / "check.md").exists():  # a rebuild keeps the decisions already made
        text = review.carry_over((app_dir / "check.md").read_text(encoding="utf-8"), text)
    (app_dir / "check.md").write_text(text, encoding="utf-8")
    criticals = len((check or {}).get("criticals") or [])
    ats_total = ((grade or {}).get("ats") or {}).get("total")
    ceiling = (grade or {}).get("ats_ceiling")
    # Jake, Oct 23 2026: more than loop.wide_gap under what the evidence allows isn't acceptable, so
    # it needs a fix (a line reworded by hand, or another round) before it is sent.
    wide_gap = (isinstance(ats_total, (int, float)) and isinstance(ceiling, (int, float))
                and ats_total < ceiling - float((cfg.get("loop") or {}).get("wide_gap", 8)))
    status = "needs_fixes" if criticals or wide_gap else "ready_for_review"
    below_floor = isinstance(ats_total, (int, float)) and ats_total < float(cfg.get("ats_floor", 70))
    weaker_fit = bool(below_floor and (grade or {}).get("fit_gap"))
    # What the dashboard shows next to the status, so a review problem is visible without
    # opening the folder.
    flags = (["weaker_fit"] if weaker_fit else ["ats_below_floor"] if below_floor else []) + (["wide_gap"] if wide_gap else [])
    app = appdir.log(app_dir, "packet", f"{status}, {criticals} critical(s)", status=status)
    _sync(app_dir, cfg, app, status, review_flags=json.dumps(flags))
    return {"status": status, "criticals": criticals, "round": rnd, "below_ats_floor": below_floor,
            "weaker_fit": weaker_fit, "files": ["fit-notes.md", "check.md"]}


def _sync(app_dir: Path, cfg: dict[str, Any], app: dict[str, Any], status: str, **fields: Any) -> None:
    conn = store.connect(resolve(cfg, "db"))
    try:
        if store.get_app(conn, app["job_id"]) is None:
            store.upsert_app(conn, app, app_dir)
        store.set_status(conn, app["job_id"], status, **fields)
        if status == "applied":
            store.mark_applied(conn, app["job_id"])
    finally:
        conn.close()


def unresolved_lines(check_md: str) -> list[str]:
    """Lines of check.md that still need a decision (the same rule the review page uses)."""
    return review.undecided(check_md)


def approve(app_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    path = app_dir / "check.md"
    if not path.exists():
        raise TailorError("check.md is missing: run the packet step first")
    if appdir.load_app(app_dir).get("status") == "needs_fixes":
        raise TailorError("the check found critical problems: fix them and rerun packet before approving")
    bad = unresolved_lines(path.read_text(encoding="utf-8"))
    if bad:
        raise TailorError(f"{len(bad)} line(s) in check.md still need a decision:\n" + "\n".join(bad))
    text = path.read_text(encoding="utf-8")
    undone = rejects.apply_undos(text, cfg)
    picks = rejects.apply_confirms(text, cfg, appdir.load_app(app_dir).get("job_id"))
    app = appdir.log(app_dir, "approve", "all check.md lines resolved", status="approved")
    _sync(app_dir, cfg, app, "approved")
    return {"status": "approved", "rejects_undone": len(undone), "confirmed": len(picks["confirmed"]),
            "not_shown": len(picks["rejected"])}


def record_outcome(app_dir: Path, cfg: dict[str, Any], outcome: str) -> dict[str, Any]:
    if outcome not in OUTCOMES:
        raise TailorError(f"outcome must be one of {', '.join(OUTCOMES)}")
    at = appdir.now()
    fields: dict[str, Any] = {"outcome": outcome, "outcome_at": at}
    if outcome == "applied":
        fields["status"] = "applied"
    app = appdir.log(app_dir, "outcome", outcome, **fields)
    _sync(app_dir, cfg, app, app["status"], outcome=outcome, outcome_at=at)
    return {"status": app["status"], "outcome": outcome, "outcome_at": at}
