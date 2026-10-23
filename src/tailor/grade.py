"""Step 6: grade a draft round.

Two parts feed one score:

- a deterministic ATS score (keywords, skills, title, sections, dates), where
  only vault-backed terms can earn credit;
- a checklist judged by Jev on the identity-stripped draft. With no Jev key every
  item comes back "unchecked" and counts as passed.

`score = 0.6 * ATS total + 0.4 * checklist pass rate * 100`, where each item counts
by Jev's probability that it passes (`p_pass`), so a 0.51 yes and a 0.49 no
weigh about the same instead of 1 and 0. Feedback for the
repair round is built here from failed items and missing must-haves; it never
quotes the checklist question wording (the writer must not see the rubric).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.experience import parse_min_years_experience
from src.resume import iter_bullets, load_resume
from src.tailor import TailorError, rejects, taxonomy, wording
from src.tailor.appdir import log, read_json, round_dir, write_json
from src.tailor.evidence import degree_level
from src.tailor.jev import Question, strip_identity

DEFAULT_WEIGHTS = {"keyword": 40, "skills": 20, "title": 15, "sections": 15, "dates": 10}
SENIORITY_WORDS = {
    "junior", "jr", "senior", "sr", "lead", "principal", "staff", "associate", "entry", "level",
    "entry-level", "intern", "trainee", "i", "ii", "iii", "iv",
}
BOILERPLATE_FACTOR = 0.25
MUST_FACTOR = 1.5
SOFT_FACTOR = 0.0  # soft skills don't count: ATS searches and recruiter filters key on hard skills (Jake, Oct 23 2026)

_RANGE = re.compile(r"^[A-Z][a-z]{2} \d{4}\s*[–-]\s*(?:[A-Z][a-z]{2} \d{4}|Present)$")
_SINGLE = re.compile(r"^[A-Z][a-z]{2} \d{4}$")


# ---------------------------------------------------------------------------
# Resume / letter text
# ---------------------------------------------------------------------------


def _bullet_texts(data: dict[str, Any]) -> list[tuple[str, str]]:
    return [(p, str(b.get("text") or "")) for p, b in iter_bullets(data)]


def _skills_text(data: dict[str, Any]) -> str:
    parts = []
    for g in data.get("skills") or []:
        parts.append(str(g.get("label") or ""))
        parts.extend(str(i) for i in g.get("items") or [])
    return "\n".join(p for p in parts if p)


def _summary_text(data: dict[str, Any]) -> str:
    s = data.get("summary")
    return str(s.get("text") or "").strip() if isinstance(s, dict) else ""


def resume_text(data: dict[str, Any]) -> str:
    """The whole resume as plain text, in reading order."""
    out: list[str] = []
    if _summary_text(data):
        out += ["SUMMARY", _summary_text(data)]
    if data.get("skills"):
        out += ["SKILLS", _skills_text(data)]
    for section in ("experience", "projects"):
        entries = data.get(section) or []
        if entries:
            out.append(section.upper())
        for e in entries:
            head = " ".join(str(e.get(k) or "") for k in ("title", "company", "name", "context", "dates"))
            out.append(head.strip())
            out += [f"- {b.get('text', '')}" for b in e.get("bullets") or []]
    if data.get("education"):
        out.append("EDUCATION")
        for e in data["education"]:
            out.append(" ".join(str(e.get(k) or "") for k in ("school", "degree", "dates")).strip())
            out += [f"{ln.get('label', '')}: {ln.get('text', '')}" for ln in e.get("lines") or []]
    return "\n".join(out)


def letter_text(letter: dict[str, Any] | None) -> str:
    if not letter:
        return ""
    paras = [str(p.get("text") or "") if isinstance(p, dict) else str(p) for p in letter.get("paragraphs") or []]
    return "\n\n".join([str(letter.get("greeting") or ""), *paras, str(letter.get("sign_off") or "")]).strip()


# ---------------------------------------------------------------------------
# ATS score
# ---------------------------------------------------------------------------


def _collect_terms(req: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], set[str]]:
    """Posting terms keyed by lowercase text, and the lowercase terms that come from requirements."""
    terms: dict[str, dict[str, Any]] = {}
    req_terms: set[str] = set()

    def add(term: str, weight: str, must: bool) -> None:
        key = term.strip().lower()
        if not key:
            return
        t = terms.setdefault(key, {"term": term.strip(), "boilerplate": True, "must": False,
                                   "soft": taxonomy.category(taxonomy.canonical(term) or "") == "Soft skills"})
        t["must"] = t["must"] or must
        t["boilerplate"] = t["boilerplate"] and weight == "boilerplate"

    for r in req.get("requirements") or []:
        kind = r.get("kind")
        for term in r.get("terms") or []:
            add(term, r.get("weight", "role"), kind == "must")
            if kind in ("must", "nice"):
                req_terms.add(term.strip().lower())
    for k in req.get("keywords") or []:
        add(k.get("term", ""), k.get("weight", "role"), False)
    return terms, req_terms


def _a(noun: str) -> str:
    """'a Data Analyst' / 'an Associate'."""
    return ("an " if noun[:1].lower() in "aeiou" else "a ") + noun


def _backed_set(evidence: dict[str, Any]) -> set[str]:
    backed = {str(t).lower() for t in evidence.get("present") or []}
    for t in evidence.get("terms") or []:
        if any((t.get("in_base") or {}).values()):
            backed.add(str(t.get("term", "")).lower())
            if t.get("canonical"):
                backed.add(str(t["canonical"]).lower())
    return backed


def _is_backed(term: str, backed: set[str]) -> bool:
    if term.lower() in backed:
        return True
    canon = taxonomy.canonical(term)
    return bool(canon and canon.lower() in backed)


def _wording_backed(term: str, backed: set[str], vault: tuple[str, set[str]] | None = None) -> bool:
    """Backed in the posting's own words: the term itself, or a full synonym of a backed skill. A
    narrower phrase backed only through its skill ("reporting pipelines" via "reporting") is not, so
    repair is never told to use words the vault doesn't say.

    `vault` is (base and claim-passage text, confirmed skill keys), what the check judges a draft's
    wording against: a hard skill's term must be in that text or its skill confirmed for a passage.
    A synonym the vault never says ("data requirements" where it says "requirements gathering") is
    flagged as invented by the check, so it is not a wording the grade may ask for."""
    canon = taxonomy.canonical(term)
    if term.lower() not in backed and not (canon and canon.lower() in backed and taxonomy.is_synonym(term)):
        return False
    if vault is None or not (canon and taxonomy.is_hard(canon)):
        return True
    text, confirmed = vault
    return wording.same(term, text) or rejects.key(term) in confirmed


def _credit(term: str, text: str, synonym_credit: float) -> float:
    if taxonomy.exact(term, text):
        return 1.0
    canon = taxonomy.canonical(term)
    if canon and taxonomy.mentions(canon, text):
        return synonym_credit
    return 0.0


def _count(term: str, text: str) -> int:
    return wording.count(term, text)


def _term_weight(t: dict[str, Any], soft_factor: float = SOFT_FACTOR) -> float:
    return ((BOILERPLATE_FACTOR if t["boilerplate"] else 1.0) * (MUST_FACTOR if t["must"] else 1.0)
            * (soft_factor if t.get("soft") else 1.0))


def _keyword_score(terms, backed, text, synonym_credit, soft_factor: float = SOFT_FACTOR) -> float | None:
    if not terms:
        return None
    got = total = 0.0
    for t in terms.values():
        w = _term_weight(t, soft_factor)
        total += w
        if _is_backed(t["term"], backed):
            got += w * _credit(t["term"], text, synonym_credit)
    return 100.0 * got / total if total else None


def _skills_score(req_terms: set[str], terms, data, soft_factor: float = SOFT_FACTOR) -> float | None:
    if not req_terms:
        return None
    hay = _skills_text(data) + "\n" + "\n".join(t for _, t in _bullet_texts(data))
    w = {k: soft_factor if terms[k].get("soft") else 1.0 for k in req_terms}
    found = sum(w[k] for k in req_terms if _credit(terms[k]["term"], hay, 0.5) > 0)
    return 100.0 * found / sum(w.values()) if sum(w.values()) else None


def _core_title(title: str) -> str:
    words = [w for w in re.findall(r"[\w+#/&.-]+", title) if w.lower() not in SENIORITY_WORDS]
    return " ".join(words)


def _title_score(title: str, data: dict[str, Any]) -> float | None:
    summary = _summary_text(data)
    headline = data.get("headline")
    if not title.strip() or not (summary or headline):
        return None
    first = str(headline) if isinstance(headline, str) and headline.strip() else re.split(r"(?<=[.!?])\s", summary, maxsplit=1)[0]
    core = _core_title(title)
    phrases = [p for p in (title.strip(), core) if p]
    if any(taxonomy.exact(p, first) for p in phrases):
        return 100.0
    if any(taxonomy.exact(p, summary) for p in phrases):
        return 75.0
    words = {w.lower() for w in re.findall(r"\w+", core or title)}
    have = {w.lower() for w in re.findall(r"\w+", summary + " " + first)}
    return 50.0 * len(words & have) / len(words) if words else 0.0


def _sections_score(data: dict[str, Any]) -> float:
    present = [bool(_summary_text(data)), bool(data.get("experience")), bool(data.get("education")), bool(data.get("skills"))]
    return 100.0 * sum(present) / 4


def _dates_score(data: dict[str, Any]) -> float | None:
    checks: list[bool] = []
    for section in ("experience", "education"):
        checks += [bool(_RANGE.match(str(e.get("dates") or "").strip())) for e in data.get(section) or []]
    for e in data.get("projects") or []:
        d = str(e.get("dates") or "").strip()
        if d:
            checks.append(bool(_RANGE.match(d) or _SINGLE.match(d)))
    return 100.0 * sum(checks) / len(checks) if checks else None


def ats_score(data: dict[str, Any], req: dict[str, Any], evidence: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Deterministic ATS score. Components that can't be scored are None and their weight is redistributed."""
    text = resume_text(data)
    terms, req_terms = _collect_terms(req)
    backed = _backed_set(evidence)
    soft = cfg.get("ats_soft_weight", SOFT_FACTOR)
    comps: dict[str, float | None] = {
        "keyword": _keyword_score(terms, backed, text, cfg.get("synonym_credit", 0.5), soft),
        "skills": _skills_score(req_terms, terms, data, soft),
        "title": _title_score(str(req.get("title") or ""), data),
        "sections": _sections_score(data),
        "dates": _dates_score(data),
    }
    weights = {**DEFAULT_WEIGHTS, **(cfg.get("ats_weights") or {})}
    live = {k: v for k, v in comps.items() if v is not None}
    wsum = sum(weights.get(k, 0) for k in live)
    total = sum(weights.get(k, 0) * v for k, v in live.items()) / wsum if wsum else 0.0
    stuffing = total > cfg.get("stuffing_score", 90) and any(_count(t["term"], text) > 4 for t in terms.values())
    rounded = {k: (round(v, 1) if v is not None else None) for k, v in comps.items()}
    return {"total": round(total, 1), "components": rounded, "stuffing": stuffing, "_repeated": _repeated(terms, text)}


def ats_gap(data: dict[str, Any], req: dict[str, Any], evidence: dict[str, Any], cfg: dict[str, Any],
            vault: tuple[str, set[str]] | None = None, title_ok: bool | str = False) -> dict[str, Any]:
    """Why the ATS score is where it is: backed hard-skill terms the resume doesn't use, backed soft
    skills it doesn't name (listed apart: a repair works them into a line whose story shows them,
    never as an adjective), terms the vault can't back, and the highest score reachable if every
    backed hard term were used in the posting's words (`vault`: see `_wording_backed`), and the job
    title too when the plan found it truthful (`title_ok`, the plan's headline; `title_missing` names it
    when the summary doesn't open with it yet). Soft skills weigh `ats_soft_weight` (0 since
    Jake, Oct 23 2026: ATS searches key on hard skills), so a missing soft word is never a gap to close.

    The ATS target is the floor, or the ceiling minus a small tolerance when the ceiling itself is
    under the floor. A ceiling under the floor is a fit gap (the evidence isn't there), not a wording gap."""
    text = resume_text(data)
    terms, req_terms = _collect_terms(req)
    backed = _backed_set(evidence)
    soft = cfg.get("ats_soft_weight", SOFT_FACTOR)

    def weight(t: dict[str, Any]) -> float:
        return _term_weight(t, soft)

    ranked = sorted(terms.values(), key=lambda t: -weight(t))
    missing = [t for t in ranked if _wording_backed(t["term"], backed, vault) and _credit(t["term"], text, 1.0) < 1.0]
    unused = [t["term"] for t in missing if not t["soft"]]
    unused_soft = [t["term"] for t in missing if t["soft"]]
    unbacked = [t["term"] for t in ranked if not _is_backed(t["term"], backed) and not t["boilerplate"]]
    score = ats_score(data, req, evidence, cfg)
    comps = dict(score["components"])
    total_w = sum(weight(t) for t in terms.values())
    if total_w:
        # A narrower phrase backed only through its skill reaches synonym credit, not full credit.
        syn = cfg.get("synonym_credit", 0.5)
        comps["keyword"] = 100.0 * sum(
            weight(t) * (1.0 if _wording_backed(t["term"], backed, vault) else syn)
            for t in terms.values() if _is_backed(t["term"], backed)) / total_w
    if req_terms:
        sw = {k: soft if terms[k]["soft"] else 1.0 for k in req_terms}
        if sum(sw.values()):
            comps["skills"] = 100.0 * sum(sw[k] for k in req_terms if _is_backed(terms[k]["term"], backed)) / sum(sw.values())
    title_missing = ""
    if title_ok and comps.get("title") is not None:
        if comps["title"] < 100.0:
            title_missing = title_ok if isinstance(title_ok, str) else ""
        comps["title"] = 100.0
    weights = {**DEFAULT_WEIGHTS, **(cfg.get("ats_weights") or {})}
    live = {k: v for k, v in comps.items() if v is not None}
    wsum = sum(weights.get(k, 0) for k in live)
    ceiling = round(sum(weights.get(k, 0) * v for k, v in live.items()) / wsum if wsum else 0.0, 1)
    floor = float(cfg.get("ats_floor", 70))
    target = min(floor, ceiling - float(cfg.get("ats_wording_tolerance", 5)))
    return {"unused": unused, "unused_soft": unused_soft, "unbacked": unbacked, "title_missing": title_missing,
            "ceiling": ceiling, "floor": floor, "target": round(target, 1), "fit_gap": ceiling < floor,
            "needs_repair": score["total"] < target and bool(unused or title_missing)}


def _repeated(terms, text) -> list[str]:
    return [t["term"] for t in terms.values() if _count(t["term"], text) > 4]


# ---------------------------------------------------------------------------
# Checklist
# ---------------------------------------------------------------------------


def p_pass(item: dict[str, Any]) -> float:
    """How likely a checklist item passes: Jev's probability when it answered, 1 or 0 for a rule,
    1 for an unchecked item. Older grade files have no `p_pass`; their confidence is the
    probability of the answer given, so it is recovered from that."""
    if item.get("p_pass") is not None:
        return float(item["p_pass"])
    if item.get("passed") is None:
        return 1.0
    conf = item.get("confidence")
    if item.get("source") == "jev" and isinstance(conf, (int, float)):
        return float(conf) if item["passed"] else 1.0 - float(conf)
    return 1.0 if item["passed"] else 0.0


def _req_label(r: dict[str, Any]) -> str:
    terms = r.get("terms") or []
    return terms[0] if terms else str(r.get("text") or r.get("id"))


def _is_degree(r: dict[str, Any]) -> bool:
    return degree_level(f"{r.get('text', '')} {r.get('quote', '')}") is not None


# "Computer Science or a related field", "or equivalent", "a quantitative discipline"...
_OPEN_FIELD = re.compile(r"\brelated\b|\bequivalent\b|\bsimilar\b|\bquantitative\b|\btechnical (?:field|discipline)", re.I)


def _degree_by_rule(r: dict[str, Any], evidence: dict[str, Any], cfg: dict[str, Any]) -> bool:
    """A degree must-have the held degree meets by Jake's rule: the level is met (evidence's degree
    check) and the posting accepts a related field, which his degree counts as (`degree_counts_as_related`)."""
    if not cfg.get("degree_counts_as_related") or not _OPEN_FIELD.search(f"{r.get('text', '')} {r.get('quote', '')}"):
        return False
    return any(e.get("id") == r.get("id") and e.get("method") == "degree" and e.get("status") == "covered"
               for e in evidence.get("requirements") or [])


def _req_passage(rid: str, r: dict[str, Any], evidence: dict[str, Any]) -> str | None:
    for e in evidence.get("requirements") or []:
        # A degree match ("5+ years with a Bachelor's degree") cites the degree line, which backs
        # none of the requirement's terms: point repair at a term's own passage instead.
        if e.get("id") == rid and e.get("passages") and e.get("method") != "degree":
            return e["passages"][0]
    wanted = {t.lower() for t in r.get("terms") or []}
    for t in evidence.get("terms") or []:
        if str(t.get("term", "")).lower() in wanted and t.get("passages"):
            return t["passages"][0]
    return None


def _must_sections(data: dict[str, Any], passage_ids: set[str]) -> list[str]:
    cited = []
    for section in ("experience", "projects"):
        for e in data.get(section) or []:
            if any(set(b.get("sources") or []) & passage_ids for b in e.get("bullets") or []):
                cited.append(f"{section}/{e.get('id')}")
    if not cited:
        cited = [f"experience/{e.get('id')}" for e in data.get("experience") or []]
    return ["summary", "skills", *cited]


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")


def _first_last_sentences(letter: dict[str, Any]) -> tuple[str, str]:
    paras = [str(p.get("text") or "") if isinstance(p, dict) else str(p) for p in letter.get("paragraphs") or []]
    paras = [p.strip() for p in paras if p.strip()]
    if not paras:
        return "", ""
    return _SENTENCE_END.split(paras[0])[0], _SENTENCE_END.split(paras[-1])[-1]


def _build_questions(app_dir, rnd, data, req, company, letter):
    qs: list[Question] = []
    meta: dict[str, dict[str, Any]] = {}

    def add(qid: str, text: str, fail_on_yes: bool = False, **extra: Any) -> None:
        qs.append(Question(qid, "yesno", text))
        meta[qid] = {"fail_on_yes": fail_on_yes, **extra}

    for r in req.get("requirements") or []:
        if r.get("kind") == "must" and _is_degree(r):
            # A degree is shown by the education section, not by a bullet that names a tool.
            add(f"must.{r['id']}", f"Does the resume's education meet this requirement: {r.get('text') or _req_label(r)}?", req_id=r["id"])
        elif r.get("kind") == "must":
            add(f"must.{r['id']}", f"Is {r.get('text') or _req_label(r)} backed by a resume bullet that names a tool and a scope?", req_id=r["id"])
    title = str(req.get("title") or "").strip()
    if title:
        add("top_third", f"Does the top third of the resume match {_a(title)} role?", sections=["summary"])
    if letter is not None:
        add("letter.specific", f"Does the letter name something specific to {company or 'the company'}?", sections=["letter"])
        # One question each, about the one sentence, so a doubt about either is clear.
        opener, closer = _first_last_sentences(letter)
        if opener:
            add("letter.opener", f'Could this opening sentence start a cover letter for almost any job: "{opener}"?',
                fail_on_yes=True, sections=["letter"], sentence=opener)
        if closer:
            add("letter.closer", f'Could this closing sentence end a cover letter for almost any job: "{closer}"?',
                fail_on_yes=True, sections=["letter"], sentence=closer)
    return qs, meta


def _run_checklist(jev, state: str, qs: list[Question], meta) -> list[dict[str, Any]]:
    try:
        answers = jev.ask(state, qs) if qs else []
    except Exception:  # Jev is advice only; any failure means unchecked
        answers = []
    by_id = {a.id: a for a in answers}
    items = []
    for q in qs:
        a = by_id.get(q.id)
        m = meta[q.id]
        item: dict[str, Any] = {"id": q.id, "question": q.text, "passed": None, "confidence": None, "source": "unchecked"}
        if a is not None and a.ok and isinstance(a.value, (int, float)):
            yes = float(a.value) >= 0.5
            item["passed"] = (not yes) if m["fail_on_yes"] else yes
            item["confidence"] = a.confidence
            item["p_pass"] = round(1.0 - float(a.value) if m["fail_on_yes"] else float(a.value), 3)
            item["source"] = "jev"
        if "sections" in m:
            item["sections"] = m["sections"]
        # Kept so the review page can show the requirement, bullet or sentence a question was about.
        item.update({k: m[k] for k in ("req_id", "bullet", "sentence") if k in m})
        items.append(item)
    return items


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _vault_wording(app_dir: Path, cfg: dict[str, Any]) -> tuple[str, set[str]] | None:
    """The text and confirmed skills the check judges wording against (checks.check_resume: the
    chosen base and every claim passage). None before the plan has picked a base."""
    if not (app_dir / "plan.json").exists():
        return None
    from src.tailor.checks import flatten
    from src.tailor.edits import load_base, load_index

    claims = [p["text"] for p in load_index(cfg).values() if p.get("use", "claim") == "claim"]
    text = flatten(load_base(app_dir, cfg)) + "\n" + "\n".join(claims)
    return text, {k for k, _ in rejects.confirmed(cfg, app_dir)}


def run_grade(app_dir: Path, rnd: int, cfg: dict[str, Any], jev) -> dict[str, Any]:
    app_dir = Path(app_dir)
    d = round_dir(app_dir, rnd)
    req = read_json(app_dir / "requirements.json")
    evidence = graded_evidence(app_dir, cfg, req)
    if not (d / "resume.yaml").exists():
        raise TailorError(f"resume.yaml is missing in {d}")
    data = load_resume(d / "resume.yaml")
    letter = read_json(d / "cover-letter.json") if (d / "cover-letter.json").exists() else None
    company = str(req.get("company") or "")

    ats = ats_score(data, req, evidence, cfg)
    repeated = ats.pop("_repeated") if ats["stuffing"] else []
    ats.pop("_repeated", None)

    text = resume_text(data)
    must_reqs = {r["id"]: r for r in req.get("requirements") or [] if r.get("kind") == "must"}
    qs, meta = _build_questions(app_dir, rnd, data, req, company, letter)
    state = strip_identity(text + ("\n\n--- LETTER ---\n" + letter_text(letter) if letter else ""), data.get("contact"))
    items = _run_checklist(jev, state, qs, meta)
    for it in items:
        r = must_reqs.get(meta[it["id"]].get("req_id", ""), {})
        if it["id"].startswith("must.") and _is_degree(r) and _degree_by_rule(r, evidence, cfg):
            it.update(passed=True, confidence=None, p_pass=1.0, source="rule")
    for it in items:
        if it["id"].startswith("must."):
            r = must_reqs[meta[it["id"]]["req_id"]]
            it["sections"] = _must_sections(data, {p for e in evidence.get("requirements") or [] if e.get("id") == r["id"] for p in e.get("passages") or []})
    _mark_fit_gaps(items, must_reqs, evidence, text, cfg)

    rate = sum(p_pass(it) for it in items) / len(items) if items else 1.0
    score = round(0.6 * ats["total"] + 0.4 * rate * 100, 1)

    gaps, feedback = _gaps_and_feedback(items, must_reqs, evidence, data, text, req, cfg, repeated)
    gap = ats_gap(data, req, evidence, cfg, _vault_wording(app_dir, cfg), title_ok=title_ok(app_dir))
    # A soft must-have Jev already says a bullet shows needs no word for it.
    shown = {str(t).lower() for it in items if it["id"].startswith("must.") and it["passed"] is True
             for t in must_reqs.get(it["id"][5:], {}).get("terms") or []}
    gap["unused_soft"] = [t for t in gap["unused_soft"] if t.lower() not in shown]
    for g in ats_gap_lines(gap, evidence, data):
        gaps.append(g)
        feedback.append(g["sentence"])
    result = {
        "ats": {"total": ats["total"], "components": ats["components"]},
        "checklist": items,
        "score": score,
        "stuffing": ats["stuffing"],
        "gaps": gaps,
        "feedback": feedback,
        "ats_floor": gap["floor"],
        "below_floor": ats["total"] < gap["floor"],
        "ats_ceiling": gap["ceiling"],
        "ats_target": gap["target"],
        "fit_gap": gap["fit_gap"],
        "needs_ats_repair": gap["needs_repair"],
        "unused_terms": gap["unused"],
        "unused_soft_terms": gap["unused_soft"],
        "unbacked_terms": gap["unbacked"],
    }
    write_json(d / "grade.json", result)
    log(app_dir, "grade", f"round {rnd}: score {score}, ATS {ats['total']}", )
    return result


def title_ok(app_dir: Path) -> str:
    """The job title the plan found truthful for the summary to open with (prompts/tailor/plan.md),
    or "" when it found none."""
    p = app_dir / "plan.json"
    return str(read_json(p).get("headline") or "").strip() if p.exists() else ""


def graded_evidence(app_dir: Path, cfg: dict[str, Any], req: dict[str, Any]) -> dict[str, Any]:
    """evidence.json as the grade sees it."""
    # Repair notes must never point back at a match that was rejected (here or on an earlier job).
    evidence = rejects.scrub_evidence(read_json(app_dir / "evidence.json"), req, rejects.pairs(cfg, app_dir))
    # The plan may have added a match the evidence step missed; count it here too.
    return rejects.add_evidence(evidence, req, rejects.confirmed(cfg, app_dir))


def ats_gap_lines(gap: dict[str, Any], evidence: dict[str, Any], data: dict[str, Any]) -> list[dict[str, Any]]:
    """The repair notes for an ATS gap: backed hard skills the resume doesn't say in the posting's
    words, the job title the plan found truthful when the summary doesn't open with it, and backed
    soft skills it doesn't name."""
    out = []

    def sections(terms: list[str]) -> list[str]:
        names = {u.lower() for u in terms}
        return _must_sections(data, {p for t in evidence.get("terms") or [] if str(t.get("term", "")).lower() in names
                                     for p in t.get("passages") or []})

    if gap["unused"]:
        # Hard skills the vault backs but the resume never says in the posting's words: the main ATS lever.
        out.append({"id": "ats.unused", "sections": sections(gap["unused"]), "sentence": (
            "Use the posting's own words for these terms the vault backs (only where a cited passage "
            f"supports them): {', '.join(gap['unused'][:12])}.")})
    if gap.get("title_missing"):
        # An ATS ranks a resume whose opening names the job title well above one that doesn't (Jake,
        # Oct 23 2026: fine to say when it is true).
        out.append({"id": "ats.title", "sections": ["summary"], "sentence": (
            f'Open the summary\'s first sentence with the job title "{gap["title_missing"]}", worded as a plain '
            f'description of the work ("{gap["title_missing"]} working in ..."), once; the plan found it truthful.')})
    if gap["unused_soft"]:
        # Soft skills don't count in the score, but a reader still looks for them: the resume names
        # the ones a story already shows and the letter the rest (Jake, Oct 23 2026). A ride-along
        # note: never a reason for a round on its own.
        out.append({"id": "ats.soft", "sections": sections(gap["unused_soft"]) + ["letter"], "sentence": (
            "Soft skills the vault shows that neither draft names yet: use the posting's word where a resume "
            "line's story already shows it (never as an adjective about the candidate, never stretched to fit), "
            f"and show the rest in the letter through a story: {', '.join(gap['unused_soft'][:8])}.")})
    return out


def _mark_fit_gaps(items, must_reqs, evidence, text, cfg) -> None:
    """Tag a failed must-have whose only missing terms are ones the vault doesn't back.

    Jev judges the whole requirement ("Python and C#/.NET"), so a real gap fails it even when
    the backed part is already shown. No rewrite can fix that, so repair rounds skip it; it
    still counts against the score and stays on the review page."""
    backed = _backed_set(evidence)
    syn = cfg.get("synonym_credit", 0.5)
    for it in items:
        if it["passed"] is not False or not it["id"].startswith("must."):
            continue
        r = must_reqs.get(it["id"][5:], {})
        terms = r.get("terms") or []
        if _is_degree(r):
            # The degree comes from the locked education entry, which no rewrite can change.
            it["fit_gap"] = ["degree"]
            continue
        if not terms and any(parse_min_years_experience(str(r.get(k) or "")) for k in ("quote", "text")):
            # Years of experience come from the dates, which no rewrite can change.
            it["fit_gap"] = ["years of experience"]
            continue
        unbacked = [t for t in terms if not _is_backed(t, backed)]
        if unbacked and all(_credit(t, text, syn) > 0 for t in terms if t not in unbacked):
            it["fit_gap"] = unbacked


def _gaps_and_feedback(items, must_reqs, evidence, data, text, req, cfg, repeated):
    """Plain-sentence fixes for failed items and for must-haves the resume doesn't show."""
    backed = _backed_set(evidence)
    syn = cfg.get("synonym_credit", 0.5)
    gaps: list[dict[str, Any]] = []
    sentences: list[str] = []
    seen_reqs: set[str] = set()

    def passage_clause(rid: str, r: dict[str, Any]) -> str:
        pid = _req_passage(rid, r, evidence)
        return f"passage {pid} supports it" if pid else "add it only if the vault supports it"

    jev_yes = {it["id"][5:] for it in items if it["id"].startswith("must.") and it["passed"] is True}
    # Must-haves with a vault-backed term that the resume doesn't show at all.
    for rid, r in must_reqs.items():
        terms = r.get("terms") or []
        # A soft skill is shown by what a bullet describes, not by its name: once Jev says a bullet
        # shows it, the missing word is no gap (soft words are never pushed in for points).
        if rid in jev_yes and not any(taxonomy.is_hard(t) for t in terms):
            continue
        if terms and any(_is_backed(t, backed) for t in terms) and not any(_credit(t, text, syn) for t in terms):
            # Name only the backed terms: the first term may be one the vault can't back.
            label = ", ".join(t for t in terms if _is_backed(t, backed))
            sentence = f"Must-have {label} isn't shown; {passage_clause(rid, r)}."
            pids = {p for e in evidence.get("requirements") or [] if e.get("id") == rid for p in e.get("passages") or []}
            gaps.append({"id": f"must.{rid}", "sentence": sentence, "sections": _must_sections(data, pids)})
            sentences.append(sentence)
            seen_reqs.add(rid)

    for it in items:
        if it["passed"] is not False:
            continue
        iid = it["id"]
        if iid.startswith("must."):
            rid = iid[5:]
            if rid in seen_reqs:
                continue
            if it.get("fit_gap"):
                continue
            r = must_reqs.get(rid, {})
            label = ", ".join(t for t in r.get("terms") or [] if _is_backed(t, backed)) or _req_label(r)
            sentences.append(f"Must-have {label} needs a bullet that names the tool and its scope; {passage_clause(rid, r)}.")
        elif iid == "top_third":
            sentences.append(f"Rewrite the summary so the top of the resume reads as {_a(req.get('title') or 'target')} role.")
        elif iid == "letter.specific":
            sentences.append(f"Name one concrete fact about {req.get('company') or 'the company'} from the posting in the letter.")
        elif iid == "letter.opener":
            sentences.append("The letter's first sentence could open any letter; start with something specific to this role.")
        elif iid == "letter.closer":
            sentences.append("The letter's last sentence could end any letter; tie it to this role or team.")
    if repeated:
        sentences.append(f"Cut repeated keywords ({', '.join(repeated[:3])}) back to a natural count.")
    return gaps, sentences
