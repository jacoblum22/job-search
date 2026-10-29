"""Step 7b: an outside review of the best draft, the round that acts on it, and up to two
"is this better?" passes after it.

Jake, Oct 25 2026: pasting the posting, the resume and the letter into a fresh Claude and asking
"what do you think?" caught problems the checks never look for (internal team names, filler words,
a summary that didn't read as the role, the letter missing the best evidence). So after the repair
loop stops, `review-input` writes the best round as plain text for a reviewer that has never seen
the vault or the rules; it writes `review/notes.md`; `review-round` then asks for one more round
that builds on the best round and acts on the notes the vault and the rules allow. That round
becomes the best unless it adds a critical or loses ATS points (loop._finish_letter_round), and packet shows what was
changed and what was left in check.md.

Jake, Oct 29 2026: his own claude.ai reviews (job-application-review skill) never stop after one
pass. He sends the revised PDFs back with "Is this better? Is it ready to submit?" two to four
times, the reviewer checks the company's claims, and asks him questions only he can answer. So a
review pass after the first (`review/pass<N>/`) sees its earlier notes and what was changed or left
and why, answers in that later-round shape, and gives a verdict. Another round runs only while the
verdict is "not yet", up to `loop.review_passes` passes. The verdict, the questions for Jake and the
interview questions go at the top of check.md.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from src.tailor.appdir import load_app, log, read_json, round_dir, write_json

PASSES = 3  # loop.review_passes: the first review plus two "is this better?" passes

SECTIONS = ["summary", "skills", "experience", "projects", "education", "letter"]


def review_dir(app_dir: Path) -> Path:
    return Path(app_dir) / "review"


def pass_dir(app_dir: Path, n: int) -> Path:
    """Pass 1 keeps the original review/ files; later passes get review/pass<N>/."""
    return review_dir(app_dir) if n == 1 else review_dir(app_dir) / f"pass{n}"


def _max_passes(cfg: dict[str, Any] | None) -> int:
    return int(((cfg or {}).get("loop") or {}).get("review_passes", PASSES))


def done_passes(app_dir: Path) -> list[int]:
    """Review passes that have notes, in order."""
    out = [1] if (review_dir(app_dir) / "notes.md").exists() else []
    if review_dir(app_dir).is_dir():
        for p in review_dir(app_dir).iterdir():
            m = re.fullmatch(r"pass(\d+)", p.name)
            if m and int(m.group(1)) > 1 and (p / "notes.md").exists():
                out.append(int(m.group(1)))
    return sorted(out)


_VERDICT = re.compile(r"^\W*verdict\W*:?\W*(ready|not yet)", re.IGNORECASE)
_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.*\S)")


def parse_notes(text: str) -> dict[str, Any]:
    """notes.md as {"verdict": "ready" | "not yet" | None, "verdict_text", "sections": {heading: [items]}}.
    The verdict is the first line starting "Verdict:"; its text runs to the first heading."""
    verdict, why, sections, head, in_verdict = None, [], {}, None, False
    for line in text.splitlines():
        m = _VERDICT.match(line)
        if m and verdict is None:
            verdict, in_verdict = m.group(1).lower(), True
            rest = line[m.end():].strip(" .:-*")
            if rest:
                why.append(rest)
            continue
        if line.startswith("#"):
            head, in_verdict = line.lstrip("#").strip().strip("*").lower(), False
            sections.setdefault(head, [])
            continue
        if in_verdict and line.strip():
            why.append(line.strip())
        elif head is not None:
            m = _ITEM.match(line)
            if m:
                sections[head].append(m.group(1).strip())
    return {"verdict": verdict, "verdict_text": " ".join(why).strip(), "sections": sections}


def _notes(app_dir: Path, n: int) -> dict[str, Any]:
    p = pass_dir(app_dir, n) / "notes.md"
    return parse_notes(p.read_text(encoding="utf-8")) if p.exists() else {"verdict": None, "sections": {}}


def _pass_round(app_dir: Path, n: int) -> int | None:
    """The round that acted on pass n (rounds written before passes existed count as pass 1)."""
    from src.tailor.loop import _feedback, _round_dirs

    for r in sorted(_round_dirs(Path(app_dir))):
        fb = _feedback(app_dir, r)
        if fb.get("review") and int(fb.get("review_pass") or 1) == n:
            return r
    return None


def next_pass(app_dir: Path, cfg: dict[str, Any] | None = None) -> tuple[int | None, str]:
    """The review pass to run next, or None and why not."""
    done = done_passes(app_dir)
    if not done:
        return 1, "first review"
    last = done[-1]
    if _notes(app_dir, last)["verdict"] == "ready":
        return None, f"review pass {last} said ready to submit"
    rnd = _pass_round(app_dir, last)
    if rnd is None:
        return None, f"review pass {last} has no round acting on it yet (run review-round)"
    if load_app(app_dir).get("best_round") != rnd:
        return None, f"the round acting on review pass {last} (round {rnd}) was not kept"
    if last >= _max_passes(cfg):
        return None, f"{last} review passes done"
    return last + 1, "is this better?"


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


def company_facts(app_dir: Path, cfg: dict[str, Any] | None) -> list[str]:
    """The company research's verified facts, so the reviewer can check what the letter says
    about the company (in his chats the reviewer looked those up on the web)."""
    company = load_app(app_dir).get("company")
    if not company or cfg is None:
        return []
    try:
        from src.tailor.company import company_dir

        path = company_dir(cfg, company) / "facts.json"
    except Exception:  # noqa: BLE001 - no companies folder configured
        return []
    if not path.exists():
        return []
    facts = read_json(path)
    out = []
    for f in facts if isinstance(facts, list) else []:
        if isinstance(f, dict) and f.get("verified") and f.get("fact"):
            src = f" ({f['url']})" if f.get("url") else ""
            quote = f'\n  > "{str(f["quote"]).strip()}"' if f.get("quote") else ""
            out.append(f"- {str(f['fact']).strip()}{src}{quote}")
    return out


def _response_lines(app_dir: Path, n: int) -> list[str]:
    lines = []
    for r in response(app_dir, n):
        done = "Changed" if str(r.get("action", "")).lower().startswith("change") else "Left as is"
        lines.append(f"- {done}: {r['note']}" + (f" ({r['why']})" if r.get("why") else ""))
    return lines


def review_input(app_dir: Path, rnd: int | None = None, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write the next pass's input.md: the posting, what the company's own pages say, the best
    round's resume and letter as plain text and, after the first pass, the earlier notes and what
    was done with each. Returns {"action": "stop", "reason"} when no pass is due."""
    app_dir = Path(app_dir)
    n, why = next_pass(app_dir, cfg)
    if n is None:
        return {"action": "stop", "reason": why}
    rnd = rnd or load_app(app_dir).get("best_round")
    if not rnd:
        from src.tailor import TailorError

        raise TailorError(f"{app_dir} has no best round yet; run next-round first")
    rd = round_dir(app_dir, int(rnd))
    data = yaml.safe_load((rd / "resume.yaml").read_text(encoding="utf-8"))
    letter = read_json(rd / "cover-letter.json") if (rd / "cover-letter.json").exists() else {}
    posting = (app_dir / "posting.md").read_text(encoding="utf-8")
    parts = ["# Job posting", posting.strip()]
    facts = company_facts(app_dir, cfg)
    if facts:
        parts += ["# What the company's own pages say", "\n".join(facts)]
    if n > 1:
        prev = pass_dir(app_dir, n - 1) / "notes.md"
        parts += ["# Your review of the last version", prev.read_text(encoding="utf-8").strip(),
                  "# What the candidate changed and what they left, with their reasons",
                  "\n".join(_response_lines(app_dir, n - 1)) or "(no list given)"]
    parts += ["# Resume" + (" (revised)" if n > 1 else ""), resume_text(data),
              "# Cover letter" + (" (revised)" if n > 1 else ""), letter_text(letter) if letter else "(no letter)"]
    out = pass_dir(app_dir, n) / "input.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n\n".join(parts) + "\n", encoding="utf-8")
    log(app_dir, "review-input", f"pass {n}, round {rnd}")
    return {"action": "review", "pass": n, "follow_up": n > 1, "round": int(rnd), "input": str(out),
            "notes": str(pass_dir(app_dir, n) / "notes.md")}


def review_round(app_dir: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Ask for one round that acts on the latest pass's notes, building on the best round. None
    when there are no notes, a round is pending, that pass already has its round, or the
    reviewer said ready to submit."""
    from src.tailor.loop import _round_dirs, pending_round

    app_dir = Path(app_dir)
    done = done_passes(app_dir)
    best = load_app(app_dir).get("best_round")
    if not done or not best or pending_round(app_dir) is not None:
        return None
    n = done[-1]
    if n > _max_passes(cfg) or _pass_round(app_dir, n) is not None:
        return None
    if _notes(app_dir, n)["verdict"] == "ready":
        return None
    nxt = max(_round_dirs(app_dir)) + 1
    notes = (pass_dir(app_dir, n) / "notes.md").relative_to(app_dir).as_posix()
    resp = (pass_dir(app_dir, n) / "response.json").relative_to(app_dir).as_posix()
    feedback = {
        "round": nxt,
        "build_on": best,
        "review": True,
        "review_pass": n,
        "notes": notes,
        "response": resp,
        "criticals": [],
        "failed_items": [f"Act on the outside review in {notes} where the vault and the rules "
                         "allow (prompts/tailor/repair.md, 'Review round')."],
        "warnings": [],
        "sections": SECTIONS,
    }
    write_json(round_dir(app_dir, nxt) / "feedback.json", feedback)
    log(app_dir, "review-round", f"round {nxt}: outside review pass {n}, on round {best}")
    return feedback


def response(app_dir: Path, n: int = 1) -> list[dict[str, Any]]:
    """A pass's response.json: what its round did with each note, for check.md and the next pass."""
    p = pass_dir(Path(app_dir), n) / "response.json"
    if not p.exists():
        return []
    data = read_json(p)
    return [r for r in (data if isinstance(data, list) else []) if isinstance(r, dict) and r.get("note")]


def summary(app_dir: Path) -> dict[str, Any] | None:
    """For the top of check.md: the latest verdict, and the questions for Jake, the claims to
    verify and the interview questions from every pass (latest first, each once)."""
    done = done_passes(Path(app_dir))
    if not done:
        return None
    last = _notes(app_dir, done[-1])
    out: dict[str, Any] = {"passes": len(done), "verdict": last["verdict"],
                           "verdict_text": last.get("verdict_text", ""),
                           "questions": [], "claims": [], "interview": []}
    for n in reversed(done):
        for head, items in _notes(app_dir, n)["sections"].items():
            key = ("questions" if "only you" in head or head.startswith("question")
                   else "interview" if "interview" in head
                   else "claims" if "claim" in head or "verify" in head else None)
            for it in items if key else []:
                if it not in out[key]:
                    out[key].append(it)
    return out
