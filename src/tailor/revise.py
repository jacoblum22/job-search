"""Hand revisions of a finished packet (outside feedback, Jake's notes), the same way every time.

Before this, each thread did it its own way: REW (Oct 27 2026) edited final/ and humanize/ and
rendered without a history entry, so the next render would have rebuilt from humanize/ and the
log didn't say a person changed the text. `revise-start` saves final/ beside it and makes sure
humanize/ holds the copy that ships, which is the one to edit (render, recheck and regrade all read
it). `revise-done` renders, scans for AI-sounding phrases, rechecks and regrades without writing
any check or grade file, and logs the change. It never changes the status: an applied or approved
application stays so (run `packet` for a fresh review page).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from src.tailor import appdir


def _snapshot(app_dir: Path, today: str) -> Path | None:
    final = app_dir / "final"
    if not final.exists() or not any(final.iterdir()):
        return None
    dest = app_dir / f"previous-version-{today}"
    n = 2
    while dest.exists():
        dest = app_dir / f"previous-version-{today}-{n}"
        n += 1
    shutil.copytree(final, dest)
    return dest


def _same_text(a: Path, b: Path) -> bool:
    if a.suffix == ".yaml":
        load = lambda p: yaml.safe_load(p.read_text(encoding="utf-8"))
    else:
        load = appdir.read_json
    return load(a) == load(b)


def revise_start(app_dir: Path, today: str | None = None) -> dict[str, Any]:
    """Save final/ as previous-version-<date>/ and make humanize/ the editable shipped copy."""
    app_dir = Path(app_dir)
    today = today or appdir.now()[:10]
    app = appdir.load_app(app_dir)
    best = app.get("best_round")
    saved = _snapshot(app_dir, today)
    hum = app_dir / "humanize"
    notes: list[str] = []
    made = []
    for name in ("resume.yaml", "cover-letter.json"):
        if appdir.humanized(app_dir, name):
            continue
        src = appdir.round_dir(app_dir, int(best)) / name if best else None
        if not src or not src.exists():
            notes.append(f"no {name} in the best round to copy")
            continue
        hum.mkdir(exist_ok=True)
        if (hum / "round.json").exists() and int(appdir.read_json(hum / "round.json").get("round") or 0) != int(best):
            # The other file is stale too; copy it as well so both describe the best round.
            for other in ("resume.yaml", "cover-letter.json"):
                o = appdir.round_dir(app_dir, int(best)) / other
                if o.exists():
                    shutil.copy2(o, hum / other)
                    made.append(other)
        shutil.copy2(src, hum / name)
        made.append(name)
        appdir.write_json(hum / "round.json", {"round": int(best)})
    for name in ("resume.yaml", "cover-letter.json"):
        f, h = app_dir / "final" / name, hum / name
        if f.exists() and h.exists() and name == "cover-letter.json" and not _same_text(f, h):
            notes.append(f"final/{name} differs from humanize/{name}: someone edited final/ by hand; "
                         "copy those edits into humanize/ before rendering or they are lost")
        if f.exists() and h.exists() and name == "resume.yaml" and f.stat().st_mtime > h.stat().st_mtime + 60:
            notes.append("final/resume.yaml is newer than humanize/resume.yaml: check it wasn't edited by hand "
                         "(page fit can also drop bullets there)")
    appdir.log(app_dir, "revise-start", f"saved {saved.name if saved else 'nothing (no final/)'}")
    return {"saved": str(saved) if saved else None,
            "edit": [str(hum / "resume.yaml"), str(hum / "cover-letter.json")],
            "copied_from_round": sorted(set(made)), "notes": notes,
            "next": "edit those two files, then run `revise-done FOLDER --note \"what changed\"`"}


def _phrase_hits(app_dir: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    from src.tailor import phrases
    from src.tailor.humanize import _lines, _own_texts

    resume_p = appdir.humanized(app_dir, "resume.yaml")
    letter_p = appdir.humanized(app_dir, "cover-letter.json")
    if not resume_p:
        return []
    resume = yaml.safe_load(resume_p.read_text(encoding="utf-8")) or {}
    letter = appdir.read_json(letter_p) if letter_p else None
    post = app_dir / "posting.md"
    posting = post.read_text(encoding="utf-8") if post.exists() else ""
    own = _own_texts(app_dir, cfg)
    out = []
    for path, text, is_letter in _lines(resume, letter):
        for hit in phrases.scan(text, posting, own, letter=is_letter):
            out.append({"line": path, "code": hit.code, "phrase": hit.phrase})
    return out


def revise_done(app_dir: Path, cfg: dict[str, Any], note: str) -> dict[str, Any]:
    """Render the edited humanize/ copy, then report pages, parse, phrase hits, criticals and ATS."""
    from src.tailor.render import run_render

    app_dir = Path(app_dir)
    status = appdir.load_app(app_dir).get("status")
    rendered = run_render(app_dir, cfg)
    result: dict[str, Any] = {
        "pages": {"resume": rendered["resume"]["pages"], "letter": rendered["letter"]["pages"]},
        "parse_ok": rendered["ok"],
        "parse_failures": [c for k in ("resume", "letter") for c in rendered[k].get("checks") or []
                           if not c.get("ok")],
        "dropped_to_fit": rendered["dropped"],
        "files": [rendered["resume"]["pdf"], rendered["letter"]["pdf"]],
        "phrase_hits": _phrase_hits(app_dir, cfg),
    }
    rnd = appdir.load_app(app_dir).get("best_round")
    try:
        from src.tailor.checks import recheck
        from src.tailor.explain import issue

        check = recheck(app_dir, int(rnd), cfg)
        resume_p = appdir.humanized(app_dir, "resume.yaml")
        data = yaml.safe_load(resume_p.read_text(encoding="utf-8")) if resume_p else None
        result["criticals"] = [issue(c, data)[0] for c in check.get("criticals") or []]
        result["warnings"] = [issue(w, data)[0] for w in check.get("warnings") or []]
    except Exception as e:  # noqa: BLE001 - the render result still stands
        result["criticals"] = f"recheck failed: {e}"
    try:
        from src.tailor.grade import regrade

        g = regrade(app_dir, int(rnd), cfg) or {}
        result["ats"] = {"now": (g.get("ats") or {}).get("total"), "reachable": g.get("ats_ceiling")}
    except Exception as e:  # noqa: BLE001
        result["ats"] = f"regrade failed: {e}"
    # render marks a failed parse needs_fixes; otherwise an applied or approved application stays so.
    appdir.log(app_dir, "hand-edit", note, **({"status": status} if rendered["ok"] else {}))
    return result
