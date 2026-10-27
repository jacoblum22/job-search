"""Step 7b: an outside review of the best draft, then one round that acts on it.

Jake, Oct 25 2026: pasting the posting, the resume and the letter into a fresh Claude and asking
"what do you think?" caught problems the checks never look for (internal team names, filler words,
a summary that didn't read as the role, the letter missing the best evidence). So after the repair
loop stops, `review-input` writes the best round as plain text for a reviewer that has never seen
the vault or the rules; it writes `review/notes.md`; `review-round` then asks for one more round
that builds on the best round and acts on the notes the vault and the rules allow. That round
becomes the best unless it adds a critical or loses ATS points (loop._finish_letter_round), and packet shows what was
changed and what was left in check.md.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.tailor.appdir import load_app, log, read_json, round_dir, write_json

SECTIONS = ["summary", "skills", "experience", "projects", "education", "letter"]


def review_dir(app_dir: Path) -> Path:
    return Path(app_dir) / "review"


def resume_text(data: dict[str, Any]) -> str:
    """The resume as a reader sees it: no ids, no sources, no contact details."""
    out: list[str] = []
    for key in data.get("order") or SECTIONS[:-1]:
        part = data.get(key)
        if not part:
            continue
        out += ["", key.upper()]
        if key == "summary":
            out.append(str(part.get("text", "") if isinstance(part, dict) else part).strip())
        elif key == "skills":
            out += [f"{g.get('label', '')}: {', '.join(map(str, g.get('items') or []))}" for g in part]
        else:
            for e in part:
                head = [e.get(k) for k in ("title", "company", "name", "context", "school", "degree", "location")]
                line = ", ".join(str(h) for h in head if h)
                out.append(f"{line} ({e['dates']})" if e.get("dates") else line)
                for b in e.get("bullets") or []:
                    out.append(f"- {str(b.get('text', '')).strip()}")
                for ln in e.get("lines") or []:
                    label = f"{ln['label']}: " if ln.get("label") else ""
                    out.append(f"  {label}{str(ln.get('text', '')).strip()}")
    return "\n".join(out).strip()


def letter_text(letter: dict[str, Any]) -> str:
    paras = [str(p.get("text", "")).strip() for p in letter.get("paragraphs") or []]
    return "\n\n".join([str(letter.get("greeting", "")).strip(), *paras, str(letter.get("sign_off", "")).strip()])


def review_input(app_dir: Path, rnd: int | None = None) -> dict[str, Any]:
    """Write review/input.md: the posting, then the best round's resume and letter as plain text."""
    app_dir = Path(app_dir)
    rnd = rnd or load_app(app_dir).get("best_round")
    if not rnd:
        from src.tailor import TailorError

        raise TailorError(f"{app_dir} has no best round yet; run next-round first")
    rd = round_dir(app_dir, int(rnd))
    data = yaml.safe_load((rd / "resume.yaml").read_text(encoding="utf-8"))
    letter = read_json(rd / "cover-letter.json") if (rd / "cover-letter.json").exists() else {}
    posting = (app_dir / "posting.md").read_text(encoding="utf-8")
    text = "\n\n".join([
        "# Job posting", posting.strip(),
        "# Resume", resume_text(data),
        "# Cover letter", letter_text(letter) if letter else "(no letter)",
    ]) + "\n"
    out = review_dir(app_dir) / "input.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    log(app_dir, "review-input", f"round {rnd}")
    return {"round": int(rnd), "input": str(out), "notes": str(review_dir(app_dir) / "notes.md")}


def review_round(app_dir: Path) -> dict[str, Any] | None:
    """Ask for one round that acts on review/notes.md, building on the best round. Once per
    folder: a second review round is never asked for."""
    from src.tailor.loop import _feedback, _round_dirs, pending_round

    app_dir = Path(app_dir)
    notes = review_dir(app_dir) / "notes.md"
    best = load_app(app_dir).get("best_round")
    if not best or not notes.exists() or pending_round(app_dir) is not None:
        return None
    dirs = _round_dirs(app_dir)
    if any(_feedback(app_dir, n).get("review") for n in dirs):
        return None
    nxt = max(dirs) + 1
    feedback = {
        "round": nxt,
        "build_on": best,
        "review": True,
        "criticals": [],
        "failed_items": ["Act on the outside review in review/notes.md where the vault and the rules "
                         "allow (prompts/tailor/repair.md, 'Review round')."],
        "warnings": [],
        "sections": SECTIONS,
    }
    write_json(round_dir(app_dir, nxt) / "feedback.json", feedback)
    log(app_dir, "review-round", f"round {nxt}: outside review, on round {best}")
    return feedback


def response(app_dir: Path) -> list[dict[str, Any]]:
    """review/response.json: what the review round did with each note, for check.md."""
    p = review_dir(Path(app_dir)) / "response.json"
    if not p.exists():
        return []
    data = read_json(p)
    return [r for r in (data if isinstance(data, list) else []) if isinstance(r, dict) and r.get("note")]
