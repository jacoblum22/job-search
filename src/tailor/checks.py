"""Step 5: truth and quality checks on the round's resume and cover letter.

Criticals (code only, block the draft) protect the facts. Warnings are style and
ATS-quality problems the repair round can fix. Flags are Jev's second opinion and
are never blocking. Check ideas adapted from AI Job Hunter (Apache-2.0, ATS
keyword and hallucination checks), Resume-Matcher (Apache-2.0, stuffing checks)
and ResumeFlow (MIT, alignment metrics).

Critical codes:
  invented_number, dropped_employer, invented_employer, invented_project,
  invented_skill, unknown_source, non_claim_source, missing_source,
  unsupported_date, locked_changed, letter_shape,
  greeting_unverified, unverified_company_fact (letter; see letter.py)
Warning codes:
  years_inflation, title_drift, keyword_coverage_dropped, term_stuffing,
  skill_only_in_list, verbatim_posting_copy, too_many_skills, bullet_count,
  bullet_long, duplicate_bullets, ai_phrase, resume_invalid, rejected_edit_note,
  no_company_fact, paragraph_count, familiar_absent_term, keen_to_grow (letter)
Flag codes (source "jev"): jev_unsupported, jev_citation_gap
"""

from __future__ import annotations

import copy
import math
import re
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from rapidfuzz import fuzz

from src.resume import iter_bullets, load_resume, validate
from src.tailor import metrics, phrases, taxonomy
from src.tailor.appdir import log, read_json, round_dir, write_json
from src.tailor.edits import LOCKED_FIELDS, load_base, load_index, norm
from src.tailor.jev import Question
from src.tailor.letter import run_letter_checks

DEFAULT_SIMILARITY_REVERT = 0.4

# ---------------------------------------------------------------------------
# Numbers and years
# ---------------------------------------------------------------------------

_SCALE = {
    "k": 1e3, "thousand": 1e3, "m": 1e6, "mm": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9,
}
_NUM = re.compile(
    r"(?<![\w.])(?P<dollar>\$\s?)?"
    r"(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?:\s?(?P<unit>%|percent\b|[x×](?!\w)|million\b|billion\b|thousand\b)|(?P<sfx>bn|mm|k|m|b)(?!\w))?"
    r"(?![\w])",
    re.I,
)
_YEAR = re.compile(r"(?<![\w.,$])(19[9]\d|20[3]\d|20[0-2]\d)(?![\w%]|,\d|\.\d)")


def _scan_numbers(text: str):
    """Yield (raw, key, material) per number; `material` False for 1-2 digit integers and years."""
    for m in _NUM.finditer(text):
        value = float(m.group("num").replace(",", ""))
        unit = (m.group("unit") or "").lower()
        sfx = (m.group("sfx") or "").lower()
        if unit in ("%", "percent"):
            key = ("pct", round(value, 6))
        elif unit in ("x", "×"):
            key = ("x", round(value, 6))
        else:
            scale = _SCALE.get(unit or sfx, 1)
            key = ("num", round(value * scale, 6))
        plain_int = not (m.group("dollar") or unit or sfx or "." in m.group("num"))
        is_year = plain_int and "," not in m.group("num") and 1990 <= value <= 2039 and len(m.group("num")) == 4
        material = not (plain_int and (value < 100 or is_year))
        yield m.group(0).strip(), key, material


def number_keys(text: str) -> set[tuple[str, float]]:
    """Normalized forms of every number in `text` (10k, 10,000 and 10000 are one key)."""
    return {key for _, key, _ in _scan_numbers(text)}


def extract_numbers(text: str, allowed: set[tuple[str, float]]) -> list[str]:
    """Material numbers in `text` (percents, multipliers, money, k/M/bn, decimals, 3+ digits) not in `allowed`."""
    return [raw for raw, key, material in _scan_numbers(text) if material and key not in allowed]


def years_in(text: str) -> set[str]:
    return set(_YEAR.findall(text))


# ---------------------------------------------------------------------------
# Resume text units
# ---------------------------------------------------------------------------


def flatten(obj: Any) -> str:
    """Every string in a nested structure, joined (used for the 'allowed' text of the base)."""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return "\n".join(flatten(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return "\n".join(flatten(v) for v in obj)
    return "" if obj is None else str(obj)


def units(data: dict[str, Any]) -> list[tuple[str, str]]:
    """(path, text) for every piece of editable text in a resume."""
    out: list[tuple[str, str]] = []
    if data.get("summary"):
        out.append(("summary", str(data["summary"].get("text", ""))))
    for g in data.get("skills") or []:
        out.append((f"skills/{g.get('id')}", ", ".join(str(x) for x in g.get("items") or [])))
    for path, b in iter_bullets(data):
        out.append((path, str(b.get("text", ""))))
    for e in data.get("education") or []:
        for line in e.get("lines") or []:
            out.append((f"education/{e.get('id')}/{line.get('id')}", str(line.get("text", ""))))
    return out


def _bullet_map(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return dict(iter_bullets(data))


def _wording_in(words: str, text: str) -> bool:
    """`words` appears in `text` as a phrase, ignoring a plural s/es on the last word."""
    stem = re.sub(r"(?:es|s)$", "", words.strip(), flags=re.I) if len(words.strip()) > 3 else words.strip()
    return bool(re.search(rf"(?<![\w+#]){re.escape(stem)}(?:s|es)?(?![\w+#])", text, re.I))


def _norm_dash(s: str) -> str:
    return re.sub(r"[–—]", "-", s)


_MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def _parse_ym(tok: str) -> int | None:
    tok = tok.strip().lower()
    if tok in ("present", "current", "now"):
        t = date.today()
        return t.year * 12 + t.month - 1
    m = re.match(r"(?:([a-z]{3})[a-z]*\.?\s+)?(\d{4})$", tok)
    if not m:
        return None
    return int(m.group(2)) * 12 + (_MONTHS.get((m.group(1) or "jan")[:3], 1) - 1)


def supported_years(base: dict[str, Any]) -> float:
    """Years of work the base's experience dates support (union of the date ranges)."""
    spans: list[tuple[int, int]] = []
    for e in base.get("experience") or []:
        parts = re.split(r"\s*-\s*", _norm_dash(str(e.get("dates", ""))))
        if len(parts) != 2:
            continue
        a, b = _parse_ym(parts[0]), _parse_ym(parts[1])
        if a is not None and b is not None and b >= a:
            spans.append((a, b + 1))
    total, end = 0, -1
    for a, b in sorted(spans):
        a = max(a, end)
        if b > a:
            total += b - a
            end = b
    return total / 12


# ---------------------------------------------------------------------------
# Individual resume checks
# ---------------------------------------------------------------------------

_YEARS_EXP = re.compile(
    r"(?<![\w.])(\d+)\+?(?:\s*(?:-|to)\s*\d+)?\s+years?\b(?:\s+of)?(?:\s+[\w-]+){0,3}?\s+experience", re.I
)
_SENIOR = re.compile(r"\b(senior|sr\.?|lead|principal|staff|director|head of|vp|chief)\b", re.I)


def _terms(req: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for r in req.get("requirements") or []:
        out += [t for t in r.get("terms") or [] if isinstance(t, str)]
    out += [k["term"] for k in req.get("keywords") or [] if isinstance(k, dict) and k.get("term")]
    return list(dict.fromkeys(t.strip() for t in out if t.strip()))


def _covered(term: str, text: str) -> bool:
    if taxonomy.exact(term, text):
        return True
    canon = taxonomy.canonical(term)
    return bool(canon and taxonomy.mentions(canon, text))


def _count(term: str, text: str) -> int:
    return len(re.findall(rf"(?<![\w+#]){re.escape(term)}(?![\w+#])", text, re.I))


def _similarity(text: str, passages: list[str]) -> float:
    t = norm(text)
    best = 0.0
    for p in [*passages, " ".join(passages)] if len(passages) > 1 else passages:
        q = norm(p)
        best = max(best, (fuzz.token_set_ratio(t, q) + fuzz.ratio(t, q)) / 200)
    return best


def _jaccard(a: str, b: str) -> float:
    wa, wb = set(re.findall(r"\w+", a.lower())), set(re.findall(r"\w+", b.lower()))
    return len(wa & wb) / len(wa | wb) if wa | wb else 0.0


def _runs(words: list[str], n: int) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def check_resume(
    draft: dict[str, Any], base: dict[str, Any], ctx: dict[str, Any]
) -> tuple[list[dict], list[dict], list[str]]:
    """Run every resume check on `draft` (already reverted); returns (criticals, warnings, [])."""
    crit: list[dict] = []
    warn: list[dict] = []

    def c(code: str, msg: str, path: str = "") -> None:
        crit.append({"code": code, "message": msg, "path": path, "doc": "resume"})

    def w(code: str, msg: str, path: str = "") -> None:
        warn.append({"code": code, "message": msg, "path": path, "doc": "resume"})

    base_text = ctx["base_text"]
    allowed_text = base_text + "\n" + "\n".join(ctx["claim_texts"])
    allowed_nums = number_keys(allowed_text)
    allowed_years = years_in(allowed_text)
    allowed_skills = taxonomy.find(allowed_text)
    d_units = units(draft)
    base_bullets = {k: v.get("text") for k, v in _bullet_map(base).items()}

    # Locked fields, entries, employers.
    base_entries = {s: {e["id"]: e for e in base.get(s) or []} for s in ("experience", "projects", "education")}
    for section in ("experience", "projects", "education"):
        seen = set()
        for e in draft.get(section) or []:
            seen.add(e.get("id"))
            be = base_entries[section].get(e.get("id"))
            if be is None:
                if section == "experience":
                    c("invented_employer", f"experience entry {e.get('company')!r} is not in the base", f"experience/{e.get('id')}")
                elif section == "projects":
                    c("invented_project", f"project {e.get('name')!r} is not in the base", f"projects/{e.get('id')}")
                else:
                    c("locked_changed", "education entry is not in the base", f"education/{e.get('id')}")
                continue
            for f in sorted(LOCKED_FIELDS - {"id", "contact"}):
                if f in be or f in e:
                    if norm(e.get(f) or "") != norm(be.get(f) or ""):
                        c("locked_changed", f"{section}/{e.get('id')} {f}: {be.get(f)!r} became {e.get(f)!r}", f"{section}/{e.get('id')}/{f}")
            if section == "education":
                bl = {x["id"]: x for x in be.get("lines") or []}
                for line in e.get("lines") or []:
                    b = bl.get(line.get("id"))
                    if b and str(b.get("label", "")).lower() != "coursework" and norm(b["text"]) != norm(line["text"]):
                        c("locked_changed", "education line changed", f"education/{e['id']}/{line['id']}")
        for bid in base_entries[section]:
            if bid not in seen and section != "projects":
                be = base_entries[section][bid]
                if section == "experience":
                    c("dropped_employer", f"{be.get('company')!r} is missing from the draft", f"experience/{bid}")
                else:
                    c("locked_changed", "education entry removed", f"education/{bid}")
    for f in ("name", "contact", "id"):
        if f in base and flatten(draft.get(f)) != flatten(base.get(f)) and f != "id":
            c("locked_changed", f"top-level {f} changed", f)

    # Sources.
    index = ctx["index"]
    for path, item in [("summary", draft.get("summary") or {})] + list(iter_bullets(draft)):
        if not item:
            continue
        srcs = item.get("sources") or []
        if not srcs and path != "summary":
            c("missing_source", "no source passage ids", path)
        for sid in srcs:
            if sid not in index:
                c("unknown_source", f"cites unknown passage id {sid!r}", path)
            elif index[sid].get("use", "claim") != "claim":
                c("non_claim_source", f"cites {sid!r}, which is {index[sid].get('use')}, not a resume claim", path)

    # Numbers, dates, skills.
    for path, text in d_units:
        for raw in extract_numbers(text, allowed_nums):
            c("invented_number", f"{raw!r} appears in no vault passage or the base", path)
        for y in sorted(years_in(text) - allowed_years):
            c("unsupported_date", f"year {y} appears in no vault passage or the base", path)
        # A skill counts as backed only when the draft's own wording for it is in the
        # vault or base: "experimentation" in a passage doesn't back "A/B testing".
        for skill, words in sorted(taxonomy.find_wordings(text).items()):
            if taxonomy.is_hard(skill) and (
                    skill not in allowed_skills or not any(_wording_in(w, allowed_text) for w in words)):
                c("invented_skill", f"{skill} appears in no vault passage or the base", path)

    full = "\n".join(t for _, t in d_units)
    req = ctx["req"]
    posting = ctx["posting"]

    # Warnings.
    span = supported_years(base)
    for m in _YEARS_EXP.finditer(full):
        n = int(m.group(1))
        if n > -(-span // 1) and not re.search(re.escape(m.group(0)), base_text, re.I):
            w("years_inflation", f"'{m.group(0)}' but dates support about {span:.1f} years")
    for m in _SENIOR.finditer(full):
        if not re.search(rf"\b{re.escape(m.group(1))}\b", allowed_text, re.I):
            w("title_drift", f"'{m.group(0)}' is not in the vault or base (title drift)")

    terms = _terms(req)
    lost = [t for t in terms if _covered(t, base_text) and not _covered(t, full)]
    if lost:
        w("keyword_coverage_dropped", "terms covered by the base but not the draft: " + ", ".join(lost))

    words_n = max(len(re.findall(r"\w+", full)), 1)
    for t in terms:
        n = _count(t, full)
        pn = _count(t, posting)
        if n and (n / words_n > 0.03 or n > 6):
            w("term_stuffing", f"'{t}' appears {n} times in {words_n} words (posting: {pn})")
    prose = "\n".join(t for p, t in d_units if not p.startswith("skills/"))
    skills_text = "\n".join(t for p, t in d_units if p.startswith("skills/"))
    for t in terms:
        canon = taxonomy.canonical(t)
        if canon and taxonomy.is_hard(canon) and _covered(t, skills_text) and not _covered(t, prose):
            w("skill_only_in_list", f"'{t}' appears only in the skills list", "skills")
    if posting:
        pw = [x for x in re.findall(r"[a-z0-9']+", norm(posting))]
        post_runs = _runs(pw, 8)
        for path, text in d_units:
            if path.startswith("skills/"):
                continue
            tw = re.findall(r"[a-z0-9']+", norm(text))
            if _runs(tw, 8) & post_runs:
                w("verbatim_posting_copy", "8 or more consecutive words copied from the posting", path)
    n_skills = sum(len(g.get("items") or []) for g in draft.get("skills") or [])
    if n_skills > 30:
        w("too_many_skills", f"{n_skills} skill items (limit 30)", "skills")

    for section in ("experience", "projects"):
        for e in draft.get(section) or []:
            bl = e.get("bullets") or []
            if not 1 <= len(bl) <= 6:
                w("bullet_count", f"{len(bl)} bullets (want 1-6)", f"{section}/{e.get('id')}")
            for i, b in enumerate(bl):
                # Base bullets are already approved; only judge the length of rewritten ones.
                if len(str(b.get("text", ""))) > 200 and b.get("text") != base_bullets.get(f"{section}/{e.get('id')}/{b.get('id')}"):
                    w("bullet_long", f"{len(b['text'])} characters (limit 200)", f"{section}/{e.get('id')}/{b.get('id')}")
                for b2 in bl[i + 1 :]:
                    if _jaccard(b["text"], b2["text"]) >= 0.8:
                        w("duplicate_bullets", f"{b.get('id')} and {b2.get('id')} are near-duplicates", f"{section}/{e.get('id')}/{b.get('id')}")

    for path, text in d_units:
        if path.startswith("skills/"):
            continue
        for h in phrases.scan(text, posting, ctx["own_texts"]):
            w("ai_phrase", f"{h.code}: {h.phrase!r}", path)
    return crit, warn, []


# ---------------------------------------------------------------------------
# Revert, Jev, entry point
# ---------------------------------------------------------------------------


def _revert_low_similarity(
    draft: dict[str, Any], base: dict[str, Any], index: dict[str, Any], threshold: float
) -> list[str]:
    """Revert changed bullets that don't resemble their cited passages; return the reverted paths."""
    base_b = _bullet_map(base)
    reverted: list[str] = []
    for section in ("experience", "projects"):
        for e in draft.get(section) or []:
            for b in list(e.get("bullets") or []):
                path = f"{section}/{e.get('id')}/{b.get('id')}"
                old = base_b.get(path)
                if old is not None and norm(old["text"]) == norm(b["text"]):
                    continue
                srcs = list(b.get("sources") or [])
                texts = [index[s]["text"] for s in srcs if s in index]
                if not texts or _similarity(b["text"], texts) >= threshold:
                    continue
                # A missed citation isn't a weak line: if related passages close the gap, cite them.
                extra = related_passages(b["text"], srcs, index)
                if extra and _similarity(b["text"], texts + [index[x]["text"] for x in extra]) >= threshold:
                    b["sources"] = srcs + extra
                    continue
                if old is not None:
                    b["text"], b["sources"] = old["text"], list(old.get("sources") or [])
                else:
                    e["bullets"].remove(b)
                reverted.append(path)
    return reverted


def _changed_lines(draft: dict[str, Any], base: dict[str, Any]) -> list[tuple[str, str, list[str]]]:
    base_b = _bullet_map(base)
    out = []
    bs = (base.get("summary") or {}).get("text", "")
    ds = draft.get("summary") or {}
    if ds and norm(ds.get("text", "")) != norm(bs):
        out.append(("summary", ds["text"], ds.get("sources") or []))
    for path, b in iter_bullets(draft):
        old = base_b.get(path)
        if old is None or norm(old["text"]) != norm(b["text"]):
            out.append((path, b["text"], b.get("sources") or []))
    return out


_STOP = frozenset(["a", "an", "and", "the", "of", "to", "for", "in", "on", "at", "by", "with", "from", "into", "that", "this", "these", "those", "was", "were", "is", "are", "be", "been", "it", "its", "as", "or", "each", "every", "other", "their", "them", "they", "our", "we", "i", "my", "me", "who", "which", "what", "using", "used", "use", "than", "then"])


def _content_words(text: str) -> set[str]:
    words = (w for w in re.findall(r"[a-z0-9+#]+", text.lower()) if len(w) > 2 and w not in _STOP)
    return {w[:-1] if w.endswith("s") and len(w) > 4 else w for w in words}  # "dashboards" ~ "dashboard"


def related_passages(text: str, srcs: list[str], index: dict[str, Any], per_clause: int = 3, limit: int = 12) -> list[str]:
    """Claim passages the line doesn't cite, from the same vault entries as its cited passages
    (algaecal.*, soft.*): the evidence a citation may have missed. Each clause of the line gets the
    passages sharing its rarest words, so every claim in a long summary is covered. "Maintained the
    dashboards" finds "Fixed dashboard problems" through "dashboard", which few passages use, even
    though "maintained" and "fixed" share nothing."""
    prefixes = {s.split(".", 1)[0] for s in srcs}
    claims = {pid: _content_words(p.get("text", "")) for pid, p in index.items() if p.get("use", "claim") == "claim"}
    df: dict[str, int] = {}
    for ws in claims.values():
        for w in ws:
            df[w] = df.get(w, 0) + 1
    n = max(len(claims), 1)
    idf = {w: math.log(n / c) for w, c in df.items()}
    pool = {pid: ws for pid, ws in claims.items() if pid not in srcs and pid.split(".", 1)[0] in prefixes}
    floor = math.log(n / 20) * 1.5  # one rare word, or a few common ones
    out: list[str] = []
    for clause in re.split(r"[,;:]| and ", text):
        words = _content_words(clause)
        scored = sorted((-sum(idf.get(w, 0.0) for w in words & ws), pid) for pid, ws in pool.items())
        out += [pid for score, pid in scored[:per_clause] if -score >= floor and pid not in out]
    return out[:limit]


def _ask_supported(jev: Any, path: str, text: str, srcs: list[str], index: dict[str, Any]) -> float | None:
    passages = [index[s]["text"] for s in srcs if s in index]
    if not passages:
        return None
    state = "Passages:\n" + "\n".join(f"- {p}" for p in passages)
    q = Question(id=f"supported:{path}", type="yesno",
                 text=f"Is this sentence supported by these passages? Sentence: {text}")
    try:
        ans = jev.ask(state, [q])[0]
    except Exception:  # noqa: BLE001 - Jev is advice; any failure means unchecked
        return None
    return float(ans.value) if ans.ok and isinstance(ans.value, (int, float)) else None


def _prune_extra(jev: Any, path: str, text: str, srcs: list[str], extra: list[str], p: float,
                 index: dict[str, Any]) -> tuple[list[str], float]:
    """Keep only the added passages Jev needs: drop each in turn (weakest match first) and keep the
    drop while Jev still says yes, so a summary isn't padded with every passage that shared a word."""
    keep = list(extra)
    for pid in reversed(extra):
        trial = [x for x in keep if x != pid]
        if not trial:
            continue
        v = _ask_supported(jev, path, text, [*srcs, *trial], index)
        if v is not None and v >= 0.5:
            keep, p = trial, v
    return keep, p


def _jev_flags(jev: Any, lines: list[tuple[str, str, list[str]]], index: dict[str, Any]) -> tuple[list[dict], dict[str, list[str]]]:
    """Ask Jev whether each changed line is supported by its cited passages.

    A "no" can mean the line overclaims, or only that its citations miss the evidence (a summary
    that cites "every team used the dashboards" but not the passage where Jake fixed them). So a
    "no" is asked again with the related passages the line doesn't cite: a "yes" then is a citation
    gap, fixed by adding those passages to the line's sources; a second "no" is a real doubt."""
    flags: list[dict] = []
    added: dict[str, list[str]] = {}
    if jev is None:
        return flags, added
    for path, text, srcs in lines:
        first = _ask_supported(jev, path, text, srcs, index)
        if first is None or first >= 0.5:
            continue
        extra = related_passages(text, srcs, index)
        second = _ask_supported(jev, path, text, [*srcs, *extra], index) if extra else None
        if second is not None and second >= 0.5:
            extra, second = _prune_extra(jev, path, text, srcs, extra, second, index)
            added[path] = extra
            flags.append({
                "code": "jev_citation_gap",
                "message": (f"Jev doubted this line with its cited passages (p={first:.2f}) but agreed once "
                            f"{', '.join(extra)} were cited too (p={second:.2f}); those were added to its sources"),
                "path": path, "doc": "resume", "source": "jev",
            })
            continue
        doubt = second if second is not None else first
        also = f", even with {', '.join(extra)}" if extra else ""
        flags.append({
            "code": "jev_unsupported",
            "message": f"Jev doubts this line is supported by its cited passages{also} (p={doubt:.2f})",
            "path": path, "doc": "resume", "source": "jev",
        })
    return flags, added


def _add_sources(draft: dict[str, Any], added: dict[str, list[str]]) -> None:
    for path, extra in added.items():
        line = draft.get("summary") if path == "summary" else dict(iter_bullets(draft)).get(path)
        if isinstance(line, dict):
            line["sources"] = [*(line.get("sources") or []), *[e for e in extra if e not in (line.get("sources") or [])]]


def _read_optional(path: Path, default: Any) -> Any:
    return read_json(path) if path.exists() else default


def run_check(app_dir: Path, rnd: int, cfg: dict[str, Any], jev: Any = None) -> dict[str, Any]:
    app_dir = Path(app_dir)
    rdir = round_dir(app_dir, rnd)
    draft_path = rdir / "resume.yaml"
    draft = load_resume(draft_path)
    base = load_base(app_dir, cfg)
    index = load_index(cfg)
    req = _read_optional(app_dir / "requirements.json", {})
    posting_path = app_dir / "posting.md"
    posting = posting_path.read_text(encoding="utf-8") if posting_path.exists() else ""
    applied = _read_optional(rdir / "applied.json", {})

    # Revert weakly supported changes first, so later checks judge what actually ships.
    # Source-id problems are judged on the unreverted draft so a bad id is never hidden by a revert.
    pre = copy.deepcopy(draft)
    threshold = float(cfg.get("similarity_revert", DEFAULT_SIMILARITY_REVERT))
    reverted = _revert_low_similarity(draft, base, index, threshold)
    if reverted or draft != pre:  # a revert, or citations added for a missed passage
        draft_path.write_text(
            yaml.safe_dump(draft, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8"
        )

    claim_texts = [p["text"] for p in index.values() if p.get("use", "claim") == "claim"]
    base_text = flatten(base)
    ctx = {
        "index": index, "req": req, "posting": posting, "base_text": base_text,
        "claim_texts": claim_texts, "own_texts": [base_text, *claim_texts], "company": req.get("company", ""),
    }
    criticals, warnings, _ = check_resume(draft, base, ctx)
    # Re-add source criticals for reverted paths (bad ids on a reverted line still go on record).
    pre_b = _bullet_map(pre)
    for path in reverted:
        for sid in pre_b.get(path, {}).get("sources") or []:
            if sid not in index:
                criticals.append({"code": "unknown_source", "message": f"cites unknown passage id {sid!r}", "path": path, "doc": "resume"})
    for p in validate(draft, require_sources=True):
        warnings.append({"code": "resume_invalid", "message": p, "path": "", "doc": "resume"})

    letter = run_letter_checks(app_dir, rnd, cfg, ctx)
    criticals += letter["criticals"]
    warnings += letter["warnings"]
    for err in applied.get("letter_errors") or []:
        criticals.append({"code": "letter_shape", "message": err, "path": "cover-letter.json", "doc": "letter"})

    flags, added = _jev_flags(jev, _changed_lines(draft, base), index)
    if added:
        _add_sources(draft, added)
        draft_path.write_text(
            yaml.safe_dump(draft, sort_keys=False, allow_unicode=True, width=110), encoding="utf-8"
        )
    result = {
        "criticals": criticals,
        "warnings": warnings,
        "flags": flags,
        "reverted": reverted,
        "metrics": metrics.compute(metrics.resume_text(draft), metrics.resume_text(base), posting, claim_texts),
    }
    write_json(rdir / "check.json", result)
    if (app_dir / "app.json").exists():
        log(app_dir, "check", f"r{rnd}: {len(criticals)} criticals, {len(warnings)} warnings, {len(reverted)} reverted")
    return result
