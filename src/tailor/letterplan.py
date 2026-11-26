"""Step 3b: the cover letter's plan, saved before any of the letter is written.

The letter prompt used to plan silently inside the writing call (its "hidden diagnosis"), fix
four movements in one order and supply the sentence stems itself, so the 104 letters sent by
Nov 2026 shared a skeleton: four stock phrases each appeared in 71 to 90 of them. Now code ranks
what the posting stresses (`emphasis`), Claude pairs the top items with the vault stories that
answer them and picks a shape (`prompts/tailor/letter-plan.md` writes `letter-plan.json`), code
checks that plan (`validate`), and the letter is drafted from it and checked against it
(`plan_warnings`, called by src/tailor/letter.py).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.tailor import TailorError, appdir
from src.tailor.requirements import norm_text
from src.tailor.sources import load_index

# Recorded in app.json when a plan is accepted, so callbacks can be compared by how the letter was made.
STYLE = "planned-v1"
PLAN_FILE = "letter-plan.json"

# shape -> how many beats it carries, its paragraph range and its word range (None = the usual ranges)
SHAPES: dict[str, dict[str, Any]] = {
    "one_story": {"beats": (1, 2), "what": "one long story told in full, answering the thing the posting stresses most"},
    "two_proofs": {"beats": (2, 3), "what": "two or three short proofs, one per stressed item"},
    "problem_first": {"beats": (1, 2), "what": "the employer's problem as the posting states it, then how the "
                                               "candidate solved the same problem"},
    "short_note": {"beats": (1, 2), "paragraphs": (2, 3), "words": (110, 170),
                   "what": "a short note, for a posting that says the letter is optional or asks for a few lines"},
}
# The gap pick rule (Jake, Nov 26 2026). Blind judges on Nov 25 marked a letter down for naming a
# preferred tool it lacked ("I haven't used ThoughtSpot yet", 0-3) and up for naming the job's
# central duty ("I haven't deployed a model to production yet", 3-0) where a story led up to it.
# So a plan may allow ONE gap sentence, only for a tier-1 requirement among the GAP_TOP most
# stressed that the vault doesn't fully cover, tied to the beat whose story comes nearest, and the
# sentence must be short and plain (GAP_WORDS words at most, no "keen to learn").
GAP_TOP = 3
GAP_WORDS = 16

# Passages that are not stories: what the candidate wants from work, and their banked sentences.
_NOT_STORY = ("motivation.", "voice.")


def story_file(passage_id: str) -> str:
    """'algaecal.sql-daily' -> 'algaecal': the vault file a passage comes from."""
    return str(passage_id).split(".", 1)[0]


def _mentions(term: str, text: str) -> int:
    t = norm_text(term)
    if not t:
        return 0
    return len(re.findall(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", text))


def emphasis(app_dir: Path) -> list[dict[str, Any]]:
    """The posting's role requirements, most stressed first, each with the vault passages that
    answer it. Stress is the requirement's tier plus three things read from the posting itself:
    whether a term is in the job title, how many times its terms come up, and how early it appears."""
    req = appdir.read_json(app_dir / "requirements.json")
    posting = norm_text((app_dir / "posting.md").read_text(encoding="utf-8")) if (app_dir / "posting.md").exists() else ""
    ev_path = app_dir / "evidence.json"
    ev = {e["id"]: e for e in (appdir.read_json(ev_path).get("requirements") or [])} if ev_path.exists() else {}
    title = norm_text(str(req.get("title") or ""))
    out = []
    for r in req.get("requirements") or []:
        if not isinstance(r, dict) or r.get("weight") == "boilerplate":
            continue
        terms = [t for t in r.get("terms") or [] if isinstance(t, str)]
        at = posting.find(norm_text(str(r.get("quote") or "")))
        early = 1 - at / len(posting) if posting and at >= 0 else 0.0
        mentions = max((_mentions(t, posting) for t in terms), default=0)
        in_title = any(_mentions(t, title) for t in terms)
        tier = r.get("tier") if isinstance(r.get("tier"), int) else 2
        stress = (4 - tier) * 2 + (2 if in_title else 0) + min(max(mentions - 1, 0), 3) + 2 * early
        e = ev.get(r.get("id")) or {}
        passages = [p for p in e.get("passages") or [] if not str(p).startswith(_NOT_STORY)]
        out.append({
            "id": r.get("id"), "text": r.get("text"), "kind": r.get("kind"), "tier": tier,
            "in_title": in_title, "mentions": mentions, "early": round(early, 2), "stress": round(stress, 1),
            # A requirement that names several tools is "partial" when the vault lacks one of them
            # (SQL and Power BI, no Power BI); the tools it does have are still a story. Strength 2
            # and up means a bullet tells it, not just a skills list. (Nov 25 2026 test: the top
            # items for Cardata and PolicyMe were partial, read as "no story", and were skipped.)
            "status": e.get("status") or "missing",
            "has_story": bool(passages) and (e.get("strength") or 0) >= 2, "passages": passages[:6],
        })
    out.sort(key=lambda x: -x["stress"])
    for rank, item in enumerate(out):
        # The one gap a letter may name (see gap_rule): the job's main duty, not a tool on a list.
        item["gap_candidate"] = rank < GAP_TOP and item["tier"] == 1 and item["status"] != "covered"
    return out


def load(app_dir: Path) -> dict[str, Any] | None:
    """The checked plan, or None when the application has none (letters drafted before plans existed)."""
    path = Path(app_dir) / PLAN_FILE
    if not path.exists():
        return None
    try:
        plan = appdir.read_json(path)
    except (OSError, ValueError):
        return None
    return plan if isinstance(plan, dict) and plan.get("_checked") else None


def validate(app_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Check letter-plan.json and mark it checked; raises TailorError naming everything wrong with it."""
    from src.tailor.letter import load_company_facts

    path = app_dir / PLAN_FILE
    if not path.exists():
        raise TailorError(f"{PLAN_FILE} is missing: follow prompts/tailor/letter-plan.md first")
    plan = appdir.read_json(path)
    if not isinstance(plan, dict):
        raise TailorError(f"{PLAN_FILE} must be a JSON object")
    req = appdir.read_json(app_dir / "requirements.json")
    reqs = {r["id"]: r for r in req.get("requirements") or [] if isinstance(r, dict) and "id" in r}
    index = load_index(cfg)
    bad: list[str] = []

    shape = plan.get("shape")
    if shape not in SHAPES:
        bad.append(f"'shape' must be one of {', '.join(SHAPES)}")
    beats = plan.get("beats")
    if not isinstance(beats, list) or not all(isinstance(b, dict) for b in beats):
        bad.append("'beats' must be a list of objects")
        beats = []
    lo, hi = SHAPES.get(shape, {"beats": (1, 3)})["beats"]
    if not lo <= len(beats) <= hi:
        bad.append(f"shape {shape!r} takes {lo} to {hi} beats; the plan has {len(beats)}")
    seen: set[str] = set()
    for i, b in enumerate(beats, 1):
        rid = b.get("requirement")
        if rid not in reqs:
            bad.append(f"beat {i}: requirement {rid!r} is not in requirements.json")
        elif reqs[rid].get("weight") == "boilerplate":
            bad.append(f"beat {i}: {rid} is boilerplate, not something the role stresses")
        pids = b.get("passages")
        if not isinstance(pids, list) or not pids:
            bad.append(f"beat {i}: needs at least one vault passage; a stressed item with no story is not a beat")
            continue
        for pid in pids:
            if pid not in index:
                bad.append(f"beat {i}: passage {pid!r} is not in the vault index")
            elif index[pid].get("use", "claim") != "claim":
                bad.append(f"beat {i}: passage {pid!r} is not a claim passage")
            elif str(pid).startswith(_NOT_STORY):
                bad.append(f"beat {i}: {pid!r} is not a story; a beat rests on work or project passages")
            if pid in seen:
                bad.append(f"beat {i}: passage {pid!r} is already another beat's story")
            seen.add(pid)
        if not str(b.get("story") or "").strip():
            bad.append(f"beat {i}: 'story' (one line on what the letter will tell) is empty")
    for key in ("opener", "close"):
        if not str(plan.get(key) or "").strip():
            bad.append(f"'{key}' (what that part of the letter is about) is empty")
    gap = plan.get("gap_mention") or False
    if gap:
        if not isinstance(gap, dict):
            bad.append("'gap_mention' must be false or an object {requirement, beat, about}")
        else:
            allowed = {e["id"] for e in emphasis(app_dir) if e["gap_candidate"]}
            if gap.get("requirement") not in allowed:
                bad.append(f"gap_mention: {gap.get('requirement')!r} is not a gap the letter may name; only a tier-1 "
                           f"requirement among the {GAP_TOP} most stressed that the vault doesn't fully cover "
                           f"({', '.join(sorted(allowed)) or 'none for this posting'}). Set 'gap_mention' to false")
            if gap.get("beat") not in range(1, len(beats) + 1):
                bad.append("gap_mention 'beat' must be the number of the beat whose story leads up to the gap")
            if not str(gap.get("about") or "").strip():
                bad.append("gap_mention 'about' (the one thing not yet done, in a few words) is empty")

    company = plan.get("company")
    if company is not None:
        if not isinstance(company, dict):
            bad.append("'company' must be null or an object")
        else:
            fid = str(company.get("fact") or "")
            facts = load_company_facts(cfg, req.get("company") or appdir.load_app(app_dir).get("company", ""))
            posting_facts = req.get("company_facts") or []
            m = re.fullmatch(r"posting:(\d+)", fid)
            if not (fid in facts or (m and 1 <= int(m[1]) <= len(posting_facts))):
                bad.append(f"company fact {fid!r} is not a verified fact id or posting:<n>")
            if company.get("beat") not in range(1, len(beats) + 1):
                bad.append("company 'beat' must be the number of the beat the fact connects to; "
                           "with no real connection, set 'company' to null")
            if not str(company.get("link") or "").strip():
                bad.append("company 'link' (how the fact connects to that beat) is empty")
    if bad:
        raise TailorError(f"{PLAN_FILE} needs fixing:\n- " + "\n- ".join(bad))

    plan["gap_mention"] = gap
    plan["_checked"] = True
    appdir.write_json(path, plan)
    appdir.log(app_dir, "letter-plan", f"{shape}, {len(beats)} beat(s)", letter_style=STYLE)
    return plan


def limits(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Paragraph and word ranges the plan's shape sets ({} = the usual ones)."""
    shape = SHAPES.get((plan or {}).get("shape"), {})
    return {k: shape[k] for k in ("paragraphs", "words") if k in shape}


def plan_warnings(plan: dict[str, Any], paras: list[dict[str, Any]]) -> list[tuple[str, str, dict[str, Any]]]:
    """(code, message, data) for each way the letter left its plan: a beat it never told, the
    planned company fact missing, or a story from a vault file no beat names."""
    cited = {str(s) for p in paras for s in p.get("sources") or []}
    facts = {str(f) for p in paras for f in p.get("company_facts") or []}
    out: list[tuple[str, str, dict[str, Any]]] = []
    beats = [b for b in plan.get("beats") or [] if isinstance(b, dict)]
    for i, b in enumerate(beats, 1):
        if not cited & {str(p) for p in b.get("passages") or []}:
            out.append(("beat_missing", f"the letter plan's beat {i} ({b.get('story')}) is not in the letter: no "
                        f"paragraph cites {', '.join(map(str, b.get('passages') or []))}", {"term": str(b.get("story") or "")}))
    company = plan.get("company")
    if isinstance(company, dict) and str(company.get("fact")) not in facts:
        out.append(("beat_missing", f"the letter plan uses company fact {company.get('fact')}, which no paragraph cites",
                    {"term": str(company.get("link") or company.get("fact"))}))
    planned = {story_file(p) for b in beats for p in b.get("passages") or []}
    extra = sorted({story_file(s) for s in cited if not s.startswith(_NOT_STORY)} - planned)
    if extra:
        out.append(("unplanned_story", "the letter tells a story from " + ", ".join(extra) + ", which the letter plan "
                    "doesn't have; keep to the planned beats or cut it", {"term": ", ".join(extra)}))
    return out


def allowed_gap(plan: dict[str, Any] | None, paras: list[dict[str, Any]], gaps: list[tuple[int, str]],
                keen: Any) -> tuple[int, str] | None:
    """Of the letter's gap sentences (paragraph number, sentence), the one the plan allows: the
    first that sits in a paragraph telling the gap's beat and is short and plain. None when the
    plan allows no gap or no sentence qualifies."""
    gap = (plan or {}).get("gap_mention")
    if not isinstance(gap, dict):
        return None
    beats = [b for b in plan.get("beats") or [] if isinstance(b, dict)]
    n = gap.get("beat")
    if not isinstance(n, int) or not 1 <= n <= len(beats):
        return None
    want = {str(p) for p in beats[n - 1].get("passages") or []}
    for i, sent in gaps:
        cited = {str(s) for s in paras[i].get("sources") or []}
        if cited & want and len(sent.split()) <= GAP_WORDS and not keen.search(sent):
            return i, sent
    return None
