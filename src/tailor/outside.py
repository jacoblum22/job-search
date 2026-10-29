"""Step 7b: an outside review of the best draft, the round that acts on it, and "is this better?"
passes after it until the reviewer says it's ready to submit.

Jake, Oct 25 2026: pasting the posting, the resume and the letter into a fresh Claude and asking
"what do you think?" caught problems the checks never look for (internal team names, filler words,
a summary that didn't read as the role, the letter missing the best evidence). So after the repair
loop stops, `review-input` writes the best round as plain text for a reviewer that has never seen
the vault or the rules; it writes `review/notes.md`; `review-round` then asks for one more round
that builds on the best round and acts on the notes the vault and the rules allow. That round
becomes the best unless it adds a critical (loop._finish_letter_round; never dropped for ATS points, Jake Oct 29 2026), and packet shows what was
changed and what was left in check.md.

Jake, Oct 29 2026: his own claude.ai reviews (job-application-review skill) never stop after one
pass. He sends the revised PDFs back with "Is this better? Is it ready to submit?" two to four
times, the reviewer checks the company's claims, and asks him questions only he can answer. So a
review pass after the first (`review/pass<N>/`) sees its earlier reviews and the revised text, never
a list of what was changed (it judges the text itself, as in his chats), answers in that
later-round shape, and gives a verdict. Another round runs only while the
verdict is "not yet" ("ready after these changes" counts as not yet), up to `loop.review_passes` passes (6: the
reviewer always has more suggestions, so the stop is it saying "ready to submit", not a count).
The verdict, the questions for Jake and the interview questions go at the top of check.md.

Jake, Oct 29 2026 (the Jobgether letter named neither the company nor the role, which each of his
own review chats made the letter's first fix): the reviewer must be his review, not a summary of
it. So it is a Claude subagent given his job-application-review skill itself
(.claude/skills/job-application-review/SKILL.md, a verbatim copy), sent exactly what he sends: "Could
you use the job-application-review skill on these? Here's the posting." with the posting and the
resume and letter PDFs attached, then, in the same conversation, "Is this better? Is it ready to
submit?" with the revised PDFs. Its reply is saved unchanged as notes.md.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.tailor.appdir import load_app, log, read_json, round_dir, write_json

PASSES = 6  # loop.review_passes: a cap; passes normally stop when the reviewer says "ready to submit"

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


_ITEM = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.*\S)")
_HEADING = re.compile(r"^\s*(?:#+\s*(.+?)|\*\*([^*]+?)\*\*:?)\s*:?\s*$")
_VERDICT_LINE = re.compile(r"^\W*verdict\W*:?\W*(.*)$", re.IGNORECASE)
_NOT_YET = re.compile(r"\bnot (?:yet|ready)\b|\bdon'?t submit\b|\bdo not submit\b|\bhold off\b", re.IGNORECASE)
_BLOCKED = re.compile(r"^\W*blocked\b", re.IGNORECASE)
_SUBMIT = re.compile(r"\bsubmit\b|\bready\b", re.IGNORECASE)
# "Submit after items 1 to 3", "ready to submit once you do the checks below": Jake, Oct 29 2026,
# only "ready to submit now" stops the passes (after those changes it often finds more).
_CONDITION = re.compile(r"\b(?:after|once|when|but|if|until|before|provided)\b|\bfix", re.IGNORECASE)


def _verdict(text: str) -> str | None:
    t = text.replace("’", "'").strip(" .*")
    if _BLOCKED.match(t):
        return "blocked"
    if _NOT_YET.search(t):
        return "not yet"
    if _SUBMIT.search(t):
        return "not yet" if _CONDITION.search(t) else "ready"
    return "not yet" if t else None


def _heading(line: str) -> str | None:
    h = _HEADING.match(line)
    return (h.group(1) or h.group(2)).strip(" *:").lower() if h else None


def _verdict_lines(lines: list[str]) -> tuple[str, list[str]] | None:
    """The last verdict in the reply and the lines after it: a "Verdict: ..." line, or a "Verdict"
    heading with the verdict on the next line (Nexthop's second round)."""
    found = None
    for i, line in enumerate(lines):
        if _heading(line) == "verdict":
            j = next((k for k in range(i + 1, len(lines)) if lines[k].strip()), None)
            if j is not None:
                found = (lines[j].replace("**", "").strip(), lines[j + 1:])
            continue
        m = _VERDICT_LINE.match(line.replace("**", ""))
        if m and m.group(1).strip():
            found = (m.group(1).strip(), lines[i + 1:])
    return found


def parse_notes(text: str) -> dict[str, Any]:
    """A reviewer's reply as {"verdict": "ready" | "not yet" | "blocked" | None, "verdict_text",
    "sections": {heading: [items]}}. The reply is the skill's own free text, as in Jake's chats: the
    verdict is its last verdict ("Verdict: Submit." is ready; "Verdict: Submit once you've fixed
    ..." is not yet), else its first line ("Yes, this is better, and ..."); a verdict that isn't
    plainly "submit" or "ready" (a first review's fit verdict) is not yet. Headings are markdown
    "#" lines or whole-line bold."""
    lines = text.splitlines()
    found = _verdict_lines(lines)
    if found:
        verdict_line, after = found
        more = []
        for nxt in after:
            if not nxt.strip() or _HEADING.match(nxt) or _ITEM.match(nxt):
                break
            more.append(nxt.strip().replace("**", ""))
        # "Verdict: not yet" on a line of its own: the reason is the lines after it.
        head = re.sub(r"^(?:not yet|ready|blocked)\W*$", "", verdict_line, flags=re.IGNORECASE)
        why = " ".join(x for x in [head, *more] if x)
    else:
        verdict_line = why = next((ln.strip().replace("**", "") for ln in lines
                                   if ln.strip() and not _HEADING.match(ln)), "")
    sections: dict[str, list[str]] = {}
    head_name = None
    for line in lines:
        h = _heading(line)
        if h is not None:
            head_name = h
            sections.setdefault(head_name, [])
            continue
        if head_name is not None:
            m = _ITEM.match(line)
            if m:
                sections[head_name].append(m.group(1).strip())
    return {"verdict": _verdict(verdict_line) if verdict_line else None, "verdict_text": why,
            "sections": sections}


def blocker(app_dir: Path, cfg: dict[str, Any] | None = None) -> str | None:
    """The posting line that makes the job impossible for Jake, else None: a required language he
    doesn't speak (score.languages, the same check the scraper's score uses). Jake, Oct 29 2026:
    CorGTA's "Spanish-speaking candidates mandatory" was drafted before that rule existed, and five
    review passes followed; a job he can't do ends right there."""
    from src.score import _language_ask

    posting = Path(app_dir) / "posting.md"
    if not posting.exists():
        return None
    lang = (((cfg or {}).get("score") or {}).get("languages")) or {}
    if lang.get("required_skip", True) is False:
        return None
    known = {str(x).lower() for x in lang.get("known") or ["english"]}
    return _language_ask(posting.read_text(encoding="utf-8"), known)


def _notes(app_dir: Path, n: int) -> dict[str, Any]:
    p = pass_dir(app_dir, n) / "notes.md"
    return parse_notes(p.read_text(encoding="utf-8")) if p.exists() else {"verdict": None, "sections": {}}


def _pass_round(app_dir: Path, n: int, fix: bool = True) -> int | None:
    """The round that acted on pass n (rounds written before passes existed count as pass 1): the
    review round, or the round that fixed a critical it added when there is one (`fix`)."""
    from src.tailor.loop import _feedback, _round_dirs

    found = None
    for r in sorted(_round_dirs(Path(app_dir))):
        fb = _feedback(app_dir, r)
        if (fb.get("review") or (fix and fb.get("review_fix"))) and int(fb.get("review_pass") or 1) == n:
            found = r
    return found


def _reviewed_round(app_dir: Path, n: int) -> int | None:
    """The round pass n read (review-input records it; older passes: the round their review round built on)."""
    p = pass_dir(Path(app_dir), n) / "reviewed.json"
    if p.exists():
        return int(read_json(p).get("round") or 0) or None
    from src.tailor.loop import _feedback

    rnd = _pass_round(app_dir, n, fix=False)
    if rnd is None:
        return None
    return int(_feedback(app_dir, rnd).get("build_on") or 0) or None


def changed_since_review(app_dir: Path) -> int | None:
    """The best round, when a round made after the last review pass (a gap or letter round that
    `pending` asked for on a later day) became the best: the reviewer never read it. Nexthop, Oct 27
    2026: two keyword rounds after the review rebuilt a bullet the review had fixed."""
    done = done_passes(app_dir)
    best = load_app(app_dir).get("best_round")
    if not done or not best:
        return None
    last = done[-1]
    seen = _pass_round(app_dir, last) or _reviewed_round(app_dir, last)
    return int(best) if seen and int(best) > seen else None


def kept(app_dir: Path, n: int) -> bool | None:
    """Whether the round that acted on pass n ships (None when no round acted on it)."""
    rnd = _pass_round(app_dir, n)
    if rnd is None:
        return None
    best = load_app(app_dir).get("best_round")
    return bool(best) and int(best) >= rnd


def next_pass(app_dir: Path, cfg: dict[str, Any] | None = None) -> tuple[int | None, str]:
    """The review pass to run next, or None and why not."""
    line = blocker(app_dir, cfg)
    if line:
        return None, f"the posting requires something Jake can't do: \"{line[:120]}\""
    done = done_passes(app_dir)
    if not done:
        return 1, "first review"
    last = done[-1]
    if _notes(app_dir, last)["verdict"] == "blocked":
        return None, f"review pass {last} says Jake can't take this job"
    later = changed_since_review(app_dir)
    if later is not None:
        if last >= _max_passes(cfg):
            return None, f"{last} review passes done (round {later}, made after the last one, wasn't reviewed)"
        return last + 1, f"round {later} changed the draft after review pass {last}"
    if _notes(app_dir, last)["verdict"] == "ready":
        return None, f"review pass {last} said ready to submit"
    rnd = _pass_round(app_dir, last)
    if rnd is None:
        return None, f"review pass {last} has no round acting on it yet (run review-round)"
    from src.tailor.loop import _feedback, unchanged
    built_on = int(_feedback(app_dir, rnd).get("build_on") or 0)
    if built_on and unchanged(app_dir, rnd, built_on):
        # Jake, Oct 29 2026: advice in, apply what is valid, "is this better?", done when the reviewer
        # says so OR nothing left is worth applying. A round that changed nothing means every note was
        # judged not worth applying; the reviewer would see the same text and repeat itself (Evismart,
        # Infoblox, Jobgether ran six passes on one text).
        return None, f"round {rnd} acted on review pass {last} and changed nothing: no note left was worth applying"
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


FIRST_MESSAGE = "Could you use the job-application-review skill on these? Here's the posting."
LATER_MESSAGE = "Is this better? Is it ready to submit?"


def _posting_body(posting: str) -> str:
    """The posting as Jake pastes it: title, company and location, then the text (no URL or date lines)."""
    keep = [ln for ln in posting.splitlines() if not re.match(r"^\s*-\s*(?:URL|Posted)\s*:", ln)]
    return "\n".join(keep).strip()


def review_input(app_dir: Path, rnd: int | None = None, cfg: dict[str, Any] | None = None,
                 render: Any = None) -> dict[str, Any]:
    """Get the next pass ready: render the best round's resume and letter PDFs into the pass's
    folder and write message.md, the message Jake would send (pass 1: his opening line and the
    posting; later passes: "Is this better? Is it ready to submit?"). Later passes continue the
    same reviewer conversation; conversation.md holds the earlier turns for a reviewer that has to
    be started fresh. Returns {"action": "stop", "reason"} when no pass is due."""
    app_dir = Path(app_dir)
    n, why = next_pass(app_dir, cfg)
    if n is None:
        return {"action": "stop", "reason": why}
    rnd = rnd or load_app(app_dir).get("best_round")
    if not rnd:
        from src.tailor import TailorError

        raise TailorError(f"{app_dir} has no best round yet; run next-round first")
    out = pass_dir(app_dir, n)
    out.mkdir(parents=True, exist_ok=True)
    if render is None:
        from src.tailor.render import render_round as render
    pdfs = render(app_dir, cfg or {}, int(rnd), out)
    attachments = [pdfs["resume"], pdfs["letter"]]
    if n == 1:
        posting = (app_dir / "posting.md").read_text(encoding="utf-8")
        message = FIRST_MESSAGE + "\n\n" + _posting_body(posting)
    else:
        message = LATER_MESSAGE
    (out / "message.md").write_text(message + "\n", encoding="utf-8")
    turns = []
    for k in range(1, n):
        msg, notes = pass_dir(app_dir, k) / "message.md", pass_dir(app_dir, k) / "notes.md"
        if msg.exists() and notes.exists():
            turns += [f"## Jake (with his resume and cover letter PDFs attached)\n\n{msg.read_text(encoding='utf-8').strip()}",
                      f"## You\n\n{notes.read_text(encoding='utf-8').strip()}"]
    if turns:
        (out / "conversation.md").write_text("\n\n".join(turns) + "\n", encoding="utf-8")
    write_json(out / "reviewed.json", {"round": int(rnd)})
    log(app_dir, "review-input", f"pass {n}, round {rnd}")
    return {"action": "review", "pass": n, "follow_up": n > 1, "round": int(rnd),
            "message": str(out / "message.md"), "attachments": attachments,
            **({"conversation": str(out / "conversation.md")} if turns else {}),
            "notes": str(out / "notes.md")}


def review_round(app_dir: Path, cfg: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """Ask for one round that acts on the latest pass's notes, building on the best round. None
    when there are no notes, a round is pending, that pass already has its round, the
    reviewer said ready to submit, or the job needs something Jake can't do."""
    from src.tailor.loop import _round_dirs, pending_round

    app_dir = Path(app_dir)
    done = done_passes(app_dir)
    best = load_app(app_dir).get("best_round")
    if not done or not best or pending_round(app_dir) is not None:
        return None
    n = done[-1]
    if n > _max_passes(cfg) or _pass_round(app_dir, n) is not None:
        return None
    from src.tailor.loop import _warnings
    if _notes(app_dir, n)["verdict"] in ("ready", "blocked") or blocker(app_dir, cfg):
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
        # Phrase warnings and Jev's doubts on the round it builds on ride along (pipeline audit, Oct 29 2026).
        "warnings": [{"code": w["code"], "message": w["message"], "path": w.get("path", "")}
                     for w in _warnings(_check(app_dir, int(best)))],
        "sections": SECTIONS,
    }
    write_json(round_dir(app_dir, nxt) / "feedback.json", feedback)
    log(app_dir, "review-round", f"round {nxt}: outside review pass {n}, on round {best}")
    return feedback


def _check(app_dir: Path, rnd: int) -> dict[str, Any]:
    p = round_dir(app_dir, rnd) / "check.json"
    return read_json(p) if p.exists() else {}


def response(app_dir: Path, n: int = 1) -> list[dict[str, Any]]:
    """A pass's response.json: what its round did with each note, for check.md and the next pass."""
    p = pass_dir(Path(app_dir), n) / "response.json"
    if not p.exists():
        return []
    data = read_json(p)
    return [r for r in (data if isinstance(data, list) else []) if isinstance(r, dict) and r.get("note")]


_QUOTE = re.compile(r'"([^"]{6,})"|“([^”]{6,})”|(?<![\w])\'([^\']{6,}?)\'(?![\w])')


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("’", "'").replace("‘", "'")).strip().lower()


def _quotes_gone(item: str, shipped: str) -> bool:
    """True when the item quotes the documents and none of its quotes is in the shipped text any
    more (a quote may skip words with "..."). Items quoting nothing are never gone."""
    quotes = [next(g for g in m.groups() if g) for m in _QUOTE.finditer(item)]
    if not quotes:
        return False
    for q in quotes:
        parts = [_norm(x) for x in re.split(r"\.\.\.|…", q) if len(x.strip()) >= 6]
        if parts and all(x in shipped for x in parts):
            return False
    return True


def shipped_text(resume: dict[str, Any] | None, letter: dict[str, Any] | None) -> str:
    return _norm((resume_text(resume) if resume else "") + "\n" + (letter_text(letter) if letter else ""))


def summary(app_dir: Path, shipped: str | None = None) -> dict[str, Any] | None:
    """For the top of check.md: the latest verdict, and the questions for Jake, the claims to
    verify and the interview questions that still apply. Jake, Oct 29 2026: Jobgether listed 8
    questions, 12 claims and 20 interview questions from all three passes, some about lines
    long gone ("41 of 54", "the team returned to"). So: the last pass's items, plus an earlier
    pass's items only when they quote the documents, and never an item whose every quote is
    gone from `shipped` (the resume and letter as sent, `shipped_text`)."""
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
                if it in out[key]:
                    continue
                if n != done[-1] and not _QUOTE.search(it):
                    continue
                if shipped is not None and _quotes_gone(it, shipped):
                    continue
                out[key].append(it)
    return out
