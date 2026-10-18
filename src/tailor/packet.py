"""Step 10: the review packet (fit-notes.md, check.md), plus approval and outcomes.

check.md is the human gate: every remaining issue is a checklist line the reviewer
ticks, and `approve` refuses until none is left unticked.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.tailor import TailorError, appdir, rejects, store
from src.resume import load_resume
from src.tailor.paths import resolve

OUTCOMES = ("applied", "callback", "interview", "offer", "rejected", "no_reply")

_KEEP_REMOVE = re.compile(r"^- \[(?P<keep>[ xX])\] Keep\s+- \[(?P<rm>[ xX])\] Remove\b")
_REVIEWED = re.compile(r"^- \[(?P<ok>[ xX])\] Reviewed\b")


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
    bucket = (evidence.get("buckets") or {}).get(base or "", {})
    lines += ["", f"## Keyword buckets (base: {base or 'none'})", ""]
    for key, label in (("matched", "Already in the resume"), ("injectable", "Can be added (backed by the vault)"),
                       ("non_injectable", "Not backed by the vault")):
        lines.append(f"- {label}: {', '.join(bucket.get(key) or []) or 'none'}")
    lines += ["", f"Match: {_pct(bucket.get('current_pct'))} now, {_pct(bucket.get('potential_pct'))} potential.", ""]
    prep = [f"Term not in your record: {t}" for t in bucket.get("non_injectable") or []] + weak
    lines += ["## Interview prep", ""]
    lines += [f"- {p}" for p in prep] or ["- Nothing flagged."]
    return "\n".join(lines) + "\n"


def _changes(rd: Path | None, app_dir: Path, cfg: dict[str, Any]) -> list[str]:
    """Line-by-line difference between the base resume and the final one (humanized if present)."""
    from src.tailor.checks import units  # local: checks pulls in the heavier metrics stack
    from src.tailor.edits import load_base

    final_path = app_dir / "humanize" / "resume.yaml"
    if not final_path.exists() and rd is not None:
        final_path = rd / "resume.yaml"
    if not final_path.exists():
        return []
    try:
        base = dict(units(load_base(app_dir, cfg)))
    except TailorError:
        return []
    final = dict(units(load_resume(final_path)))
    out: list[str] = []
    for path, after in final.items():
        before = base.get(path)
        if before is None:
            out.append(f"- `{path}` (added): {after}")
        elif before != after:
            out.append(f"- `{path}`\n  - before: {before}\n  - after: {after}")
    out += [f"- `{path}` (removed): {before}" for path, before in base.items() if path not in final]
    return out


def _check_md(app: dict[str, Any], rd: Path | None, app_dir: Path,
              check: dict[str, Any] | None, cfg: dict[str, Any]) -> str:
    gate = app.get("gate") or {}
    gate_flags = gate.get("flags") or []
    lines = ["# Check", ""]
    if gate.get("checked") is False:
        lines += ["Gate not checked: Jev is not configured.", ""]
    if gate_flags:
        lines += ["## Gate flags: review before applying", ""]
        for f in gate_flags:
            lines.append(f"- [ ] Reviewed  {f.get('question', '?')}: {f.get('reason', '')}")
        lines.append("")
    grade = _opt_json(rd / "grade.json") if rd else None
    lines += ["## Grade", ""]
    if grade:
        ats = grade.get("ats") or {}
        comps = ", ".join(f"{k} {v}" for k, v in (ats.get("components") or {}).items())
        lines.append(f"- Score: {grade.get('score', 'n/a')} (ATS {ats.get('total', 'n/a')}"
                     f"{f': {comps}' if comps else ''})")
        if grade.get("stuffing"):
            lines.append("- Keyword stuffing suspected")
    else:
        lines.append("- No grade available")
    # Jev's "no" answers are advice; listing them lets the candidate catch a false rejection.
    said_no = [it for it in (grade or {}).get("checklist") or [] if it.get("passed") is False]
    ev_no = (_opt_json(app_dir / "evidence.json") or {}).get("jev_said_no") or []
    if said_no or ev_no:
        lines += ["", "## Jev said no: check for false rejections", ""]
        for it in said_no:
            conf = f" (confidence {it['confidence']:.2f})" if isinstance(it.get("confidence"), (int, float)) else ""
            lines.append(f"- Failed: {it.get('question', it.get('id'))}{conf}")
        for n in ev_no:
            lines.append(f"- Not counted as evidence: {n.get('term')} in {n.get('passage')}: \"{n.get('text', '')}\"")
    drops = (_opt_json(app_dir / "plan.json") or {}).get("evidence_drops") or []
    if drops:
        new = {(r["term"].lower(), r["passage"]) for r in rejects.load(cfg)
               if r.get("job_id") == app.get("job_id") and not r.get("undone")}
        lines += ["", "## Evidence matches the plan rejected", "",
                  "Tick Undo if a match was right; approving then removes it from the shared reject list.", ""]
        for d in drops:
            mark = " (new)" if (str(d.get("term", "")).lower(), d.get("passage")) in new else ""
            lines.append(f"- [ ] Undo  {d.get('term', '?')} ({d.get('passage', '?')}): {d.get('reason', '')}{mark}")
    lines += ["", "## Changes from the base", ""]
    lines += _changes(rd, app_dir, cfg) or ["- No changes"]
    lines += ["", "## Remaining issues", ""]
    n = 0
    for sev in ("criticals", "warnings", "flags"):
        for it in (check or {}).get(sev) or []:
            n += 1
            path = f" ({it['path']})" if it.get("path") else ""
            lines.append(f"- [ ] Keep  - [ ] Remove  {it.get('code', sev)}: {it.get('message', '')}{path}")
    if not n:
        lines.append("- None")
    return "\n".join(lines) + "\n"


def run_packet(app_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Write fit-notes.md and check.md and move the application to review."""
    app = appdir.load_app(app_dir)
    evidence = appdir.read_json(app_dir / "evidence.json")
    rnd = _best_round(app_dir, app)
    rd = appdir.round_dir(app_dir, rnd) if rnd else None
    check = _opt_json(rd / "check.json") if rd else None
    base = _base_id(app_dir, app, evidence.get("buckets") or {})
    (app_dir / "fit-notes.md").write_text(
        _fit_notes(app, evidence, _opt_json(app_dir / "requirements.json"), base), encoding="utf-8")
    (app_dir / "check.md").write_text(_check_md(app, rd, app_dir, check, cfg), encoding="utf-8")
    criticals = len((check or {}).get("criticals") or [])
    status = "needs_fixes" if criticals else "ready_for_review"
    app = appdir.log(app_dir, "packet", f"{status}, {criticals} critical(s)", status=status)
    _sync(app_dir, cfg, app, status)
    return {"status": status, "criticals": criticals, "round": rnd,
            "files": ["fit-notes.md", "check.md"]}


def _sync(app_dir: Path, cfg: dict[str, Any], app: dict[str, Any], status: str, **fields: Any) -> None:
    conn = store.connect(resolve(cfg, "db"))
    try:
        if store.get_app(conn, app["job_id"]) is None:
            store.upsert_app(conn, app, app_dir)
        store.set_status(conn, app["job_id"], status, **fields)
    finally:
        conn.close()


def unresolved_lines(check_md: str) -> list[str]:
    """Lines of check.md that still need a decision."""
    bad = []
    for line in check_md.splitlines():
        m = _KEEP_REMOVE.match(line)
        if m and m["keep"] == " " and m["rm"] == " ":
            bad.append(line)
            continue
        m = _REVIEWED.match(line)
        if m and m["ok"] == " ":
            bad.append(line)
    return bad


def approve(app_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    path = app_dir / "check.md"
    if not path.exists():
        raise TailorError("check.md is missing: run the packet step first")
    bad = unresolved_lines(path.read_text(encoding="utf-8"))
    if bad:
        raise TailorError(f"{len(bad)} line(s) in check.md still need a decision:\n" + "\n".join(bad))
    undone = rejects.apply_undos(path.read_text(encoding="utf-8"), cfg)
    app = appdir.log(app_dir, "approve", "all check.md lines resolved", status="approved")
    _sync(app_dir, cfg, app, "approved")
    return {"status": "approved", "rejects_undone": len(undone)}


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
