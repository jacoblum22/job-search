"""Step 2: what in the vault backs each posting requirement, and what each base already says.

Facts come from the taxonomy (synonym-aware regexes); Jev gets a second look at
requirements the taxonomy found nothing for or only a synonym for, and at every
soft-skill requirement: soft skills rarely use the posting's words ("explained
results to non-technical stakeholders" shows communication without saying it), and
self-descriptions that do ("strong communication skills") are the weakest evidence.
Its answers are advisory evidence. A term the taxonomy doesn't know is matched by its plain
words, which misfires ("Access" in "access tokens"), so those matches count
only once Jev confirms them; with no Jev key they don't count at all. Degree
requirements are checked against the vault's degree passages, not by words.
Term and passage pairs rejected on earlier jobs (`rejects.py`) are never matched.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.tailor import appdir, rejects, taxonomy
from src.tailor.jev import Question
from src.tailor.sources import base_text, claim_passages, load_bases, load_index

KIND_RANK = {"must": 0, "nice": 1, "keyword": 2}
SKILLS_FILES = {"skills-map.md"}
# Self-descriptions with no story ("Strong collaboration, cooperation, and teamwork abilities"): they
# repeat posting vocabulary, so they rank last, after any line that shows the skill in real work.
GENERIC_FILES = {"extra-skills.md"}
# Rows that name what happened and where ("Worked on a 5-person data team | [[algaecal]]"):
# evidence, ranked by the note they cite.
EVIDENCE_TABLES = {"soft-skills.md"}
_LINK = re.compile(r"\[\[([^\]|#]+)")
SCOPE_WORDS = re.compile(
    r"\b(teams?|stakeholders?|datasets?|records?|rows?|users?|customers?|clients?|"
    r"departments?|daily|weekly|monthly|million|thousand|\d+k)\b", re.I)
STOP = set("a an the and or of to in on for with from by at as is are was were be our we you your "
           "experience strong ability work working skills knowledge using use have has".split())


# --- term matching ---------------------------------------------------------

def term_mentioned(entry: dict, text: str) -> bool:
    """True when `text` mentions a term entry (taxonomy synonyms, else the exact phrase)."""
    if entry.get("canonical"):
        return taxonomy.mentions(entry["canonical"], text)
    return taxonomy.exact(entry["term"], text)


def term_exact(entry: dict, text: str) -> bool:
    """True when `text` uses the posting's own wording (or the skill's canonical name).

    A synonym-only match ("experimentation" for A/B testing) is too loose to back an
    injected keyword, so those passages are kept apart as `related`.
    """
    names = list(entry.get("raw") or []) + [entry["term"]]
    return any(taxonomy.exact(n, text) for n in names if n)


def collect_terms(reqs: dict) -> list[dict]:
    """Every requirement term and keyword, deduped by canonical (else lower-case term)."""
    terms: dict[str, dict] = {}

    def add(term: str, canon: str | None, kind: str, weight: str) -> None:
        canon = canon if canon is not None else taxonomy.canonical(term)
        key = canon or term.strip().lower()
        cur = terms.get(key)
        if cur is None:
            terms[key] = {"term": canon or term.strip(), "canonical": canon, "kind": kind, "weight": weight,
                          "raw": [term.strip()]}
            return
        if term.strip() not in cur["raw"]:
            cur["raw"].append(term.strip())
        if KIND_RANK[kind] < KIND_RANK[cur["kind"]]:
            cur["kind"] = kind
        if weight == "role":
            cur["weight"] = "role"

    for r in reqs.get("requirements", []):
        canons = r.get("canonical") if isinstance(r.get("canonical"), list) else []
        for i, t in enumerate(r.get("terms", [])):
            if isinstance(t, dict):
                add(t["term"], t.get("canonical"), r["kind"], r.get("weight", "role"))
            else:
                add(t, canons[i] if i < len(canons) else None, r["kind"], r.get("weight", "role"))
    for k in reqs.get("keywords", []):
        add(k["term"], k.get("canonical"), "keyword", k.get("weight", "role"))
    return list(terms.values())


def _req_term_names(r: dict) -> list[str]:
    """Display names (the evidence `term` field) of a requirement's terms."""
    canons = r.get("canonical") if isinstance(r.get("canonical"), list) else []
    out = []
    for i, t in enumerate(r.get("terms", [])):
        if isinstance(t, dict):
            term, canon = t["term"], t.get("canonical")
        else:
            term, canon = t, (canons[i] if i < len(canons) else None)
        canon = canon if canon is not None else taxonomy.canonical(term)
        out.append(canon or term.strip())
    return out


# --- degree requirements ---------------------------------------------------

_DEGREE = {
    "bachelor": re.compile(r"\bbachelor|\bundergraduate degree|\bb\.?sc\b|\bb\.?a\.? degree|\bb\.?s\.? degree", re.IGNORECASE),
    "master": re.compile(r"\bmaster['’]?s\b|\bm\.?sc\b|\bgraduate degree", re.IGNORECASE),
    "phd": re.compile(r"\bph\.?\s?d\b|\bdoctora", re.IGNORECASE),
}
_LEVELS = ["bachelor", "master", "phd"]


def degree_level(text: str) -> str | None:
    """Lowest degree level a requirement asks for ("Bachelor's or Master's" asks for a Bachelor's)."""
    return next((lvl for lvl in _LEVELS if _DEGREE[lvl].search(text)), None)


def _degree_check(r: dict, claims: dict[str, dict]) -> dict | None:
    """Evidence entry for a degree requirement, or None when the requirement isn't about a degree."""
    need = degree_level(f"{r.get('text', '')} {r.get('quote', '')}")
    if need is None:
        return None
    # A graduate degree must read as held ("Master's degree, conferred ..."), not as a
    # passing mention ("worked with Master's students").
    held = {lvl: [pid for pid, p in claims.items() if _DEGREE[lvl].search(p["text"])
                  and (lvl == "bachelor" or re.search(r"\bdegree\b|\bconferred\b|\bgraduated\b", p["text"], re.IGNORECASE))]
            for lvl in _LEVELS}
    have = [lvl for lvl in _LEVELS if held[lvl]]
    ok = bool(have) and _LEVELS.index(have[-1]) >= _LEVELS.index(need)
    pids = held[have[-1]] if ok else []
    return {"id": r["id"], "status": "covered" if ok else "missing", "strength": 2 if ok else 0,
            "passages": pids, "method": "degree"}


# --- passage strength ------------------------------------------------------

def _file_name(p: dict) -> str:
    return str(p.get("file", "")).replace("\\", "/").rsplit("/", 1)[-1].lower()


def _skills_only(p: dict) -> bool:
    name = _file_name(p)
    if name in EVIDENCE_TABLES:
        return False
    return name in SKILLS_FILES | GENERIC_FILES or any("skill" in s.lower() for s in p.get("section") or [])


def passage_strength(p: dict) -> int:
    """1 skills list only, 2 a bullet, 3 a bullet with a concrete tool and a scope signal."""
    if _skills_only(p):
        return 1
    text = p.get("text", "")
    has_tool = any(taxonomy.is_hard(n) for n in taxonomy.find(text))
    has_scope = bool(p.get("numbers")) or bool(SCOPE_WORDS.search(text))
    return 3 if has_tool and has_scope else 2


def _folders(claims: dict[str, dict]) -> dict[str, str]:
    """Vault note name -> its file path ("algaecal" -> "work/algaecal.md"), to follow [[links]]."""
    return {str(p.get("file", "")).replace("\\", "/").rsplit("/", 1)[-1].lower().removesuffix(".md"):
            str(p.get("file", "")).replace("\\", "/").lower() for p in claims.values()}


def _origin_rank(p: dict, folders: dict[str, str] | None = None) -> int:
    """Work bullets first, then project bullets, then coursework; tech-stack lists and other files last.

    An evidence-table row ranks as the note it cites: "[[algaecal]]" is work.
    """
    f = str(p.get("file", "")).replace("\\", "/").lower()
    if _file_name(p) in EVIDENCE_TABLES and folders:
        link = _LINK.search(p.get("markdown") or "")
        f = folders.get(link.group(1).strip().lower(), f) if link else f
    rank = 0 if f.startswith("work/") else 1 if f.startswith("projects/") else 2 if "coursework" in f else 3
    if any("stack" in str(s).lower() for s in p.get("section") or []):
        rank += 2
    return rank


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#]+", s.lower()) if len(w) > 2 and w not in STOP}


def _stems(s: str) -> set[str]:
    """Word starts, so "departments" meets "department" and "collaborate" meets "collaborated"."""
    return {w[:6] for w in _words(s)}


def _rank_key(p: dict, folders: dict[str, str]) -> tuple:
    """Real bullets before skills lists and self-descriptions; work, then projects, then coursework;
    the stronger passage; primary copies before cross-references."""
    s = passage_strength(p)
    return (s < 2, _origin_rank(p, folders), -s, p.get("source") != "primary")


def _is_soft(r: dict) -> bool:
    """A requirement whose terms are all soft skills, or that has none ("work on your own")."""
    canons = r.get("canonical") if isinstance(r.get("canonical"), list) else [
        t.get("canonical") if isinstance(t, dict) else taxonomy.canonical(t) for t in r.get("terms") or []]
    return all(c and taxonomy.category(c) == "Soft skills" for c in canons)


# --- weights ---------------------------------------------------------------

def term_weight(entry: dict) -> float:
    """Hard skill 3, soft 1, other 0.5; x1.5 for must-haves; x0.25 for boilerplate."""
    canon = entry.get("canonical")
    cat = taxonomy.category(canon) if canon else None
    w = 3.0 if cat and taxonomy.is_hard(canon) else 1.0 if cat == "Soft skills" else 0.5
    if entry["kind"] == "must":
        w *= 1.5
    if entry["weight"] == "boilerplate":
        w *= 0.25
    return w


def _pct(entries: list[dict], names: set[str]) -> float:
    total = sum(term_weight(e) for e in entries)
    if not total:
        return 0.0
    return round(100 * sum(term_weight(e) for e in entries if e["term"] in names) / total, 1)


# --- main ------------------------------------------------------------------

def _soft_cats(text: str) -> set[str]:
    return {c for c in taxonomy.find(text) if taxonomy.category(c) == "Soft skills"}


def _jev_pass(reqs: list[dict], claims: dict[str, dict], cfg: dict, jev: Any,
              active: set[tuple[str, str]] = frozenset(),
              known: dict[str, list[str]] | None = None) -> dict[str, dict[str, float]]:
    """Ask Jev whether candidate passages show each requirement; one call per passage.

    Candidates are the passages sharing the most words with the requirement, plus, for a soft
    skill, the real bullets and evidence rows about the same soft skill (soft-skills.md files
    its rows under "Communication", "Teamwork & Collaboration", ...), plus the passages the
    taxonomy already found (`known`). Self-descriptions and skills lists repeat a posting's
    words ("strong collaboration") and would otherwise fill every slot ahead of the story that
    shows the skill, so only a few of them get asked. Returns every parsed answer as
    `{requirement id: {passage id: value}}`.
    """
    ev_cfg = cfg.get("evidence") or {}
    n_cand = int(ev_cfg.get("jev_candidates", 15))
    n_generic = int(ev_cfg.get("jev_generic_candidates", 2))
    if jev is None or not reqs or n_cand <= 0:
        return {}
    known = known or {}
    folders = _folders(claims)
    stems = {pid: _stems(p["text"]) for pid, p in claims.items()}
    cats = {pid: _soft_cats(p["text"] + ". " + ". ".join(p.get("section") or [])) for pid, p in claims.items()}
    per_passage: dict[str, list[tuple[dict, Question]]] = {}
    for r in reqs:
        want = _stems(r["text"] + " " + " ".join(_req_term_names(r)))
        overlap = {pid: len(want & s) for pid, s in stems.items() if want & s}
        order = sorted(overlap, key=lambda pid: (-overlap[pid], _rank_key(claims[pid], folders)))
        real = [pid for pid in order if passage_strength(claims[pid]) >= 2][:n_cand]
        weak = [pid for pid in order if passage_strength(claims[pid]) < 2][:min(n_generic, n_cand)]
        r_cats = _soft_cats(f"{r['text']}. {r.get('quote', '')}")
        same = sorted((pid for pid in claims if r_cats & cats[pid] and passage_strength(claims[pid]) >= 2),
                      key=lambda pid: _rank_key(claims[pid], folders))[:n_cand]
        names = _req_term_names(r) + [r["text"]]
        for pid in dict.fromkeys([*known.get(r["id"], []), *real, *same, *weak]):
            if rejects.rejected(names, pid, active):
                continue
            q = Question(id=f"{r['id']}|{pid}", type="yesno",
                         text=f"Does this passage show the candidate has: {r['text']}?")
            per_passage.setdefault(pid, []).append((r, q))
    out: dict[str, dict[str, float]] = {}
    for pid, items in per_passage.items():
        answers = jev.ask(claims[pid]["text"], [q for _, q in items])
        for (r, _), a in zip(items, answers):
            if a.ok and isinstance(a.value, (int, float)):
                out.setdefault(r["id"], {})[pid] = float(a.value)
    return out


def _confirm_unknown(entries: list[dict], claims: dict[str, dict], base_texts: dict[str, str],
                     cfg: dict, jev: Any, cache: rejects.JevCache | None = None,
                     said_no: list[dict] | None = None) -> dict[str, set[str]]:
    """Keep only Jev-confirmed plain-word matches for terms the taxonomy doesn't know.

    Trims each such entry's passages in place and returns, per term, the base ids
    whose text Jev confirmed. With no Jev, nothing is confirmed. Every "no" goes in
    `said_no` so the candidate can spot a false rejection.
    """
    threshold = float((cfg.get("evidence") or {}).get("jev_yes", 0.6))
    usable = jev is not None and getattr(jev, "available", True)
    confirmed_bases: dict[str, set[str]] = {}

    def yes(term: str, text: str, where: str = "") -> bool:
        ok = _ask(term, text)
        if ok is False and said_no is not None:
            said_no.append({"term": term, "passage": where, "text": text[:160]})
        return bool(ok)

    def _ask(term: str, text: str) -> bool | None:
        q = Question(id="shows", type="yesno",
                     text=f"Does this text show the candidate has used or has the skill: {term}?")
        cached = cache.get(q.text, text) if cache is not None else None
        if cached is not None:
            return cached >= threshold
        if not usable:
            return None
        a = jev.ask(text, [q])[0]
        if not (a.ok and isinstance(a.value, (int, float))):
            return None
        if cache is not None:
            cache.put(q.text, text, float(a.value))
        return a.value >= threshold

    for e in entries:
        if e.get("canonical"):
            continue
        e["passages"] = [pid for pid in e["passages"] if yes(e["term"], claims[pid]["text"], pid)]
        e["related"] = []
        confirmed_bases[e["term"]] = set()
        for bid, text in base_texts.items():
            lines = [ln for ln in text.splitlines() if term_mentioned(e, ln)]
            if any(yes(e["term"], ln, f"base:{bid}") for ln in lines):
                confirmed_bases[e["term"]].add(bid)
    return confirmed_bases


def run_evidence(app_dir: Path, cfg: dict[str, Any], jev: Any) -> dict:
    app_dir = Path(app_dir)
    reqs = appdir.read_json(app_dir / "requirements.json")
    claims = claim_passages(load_index(cfg))
    bases = load_bases(cfg)
    base_texts = {bid: base_text(b) for bid, b in bases.items()}

    entries = collect_terms(reqs)
    by_name = {e["term"]: e for e in entries}
    cap = int((cfg.get("evidence") or {}).get("max_passages", 8))
    # Real bullets before skills-list mentions; within those, work before projects before coursework,
    # then the stronger passage, primary copies before cross-references.
    folders = _folders(claims)
    ranked = sorted(claims.values(), key=lambda p: _rank_key(p, folders))
    active = rejects.pairs(cfg)
    for e in entries:
        names = [e["term"], e.get("canonical") or "", *(e.get("raw") or [])]
        hits = [p for p in ranked if term_mentioned(e, p["text"]) and not rejects.rejected(names, p["id"], active)]
        e["passages"] = [p["id"] for p in hits if term_exact(e, p["text"])][:cap]
        e["related"] = [p["id"] for p in hits if not term_exact(e, p["text"])][:3]
        e["base_rejected"] = rejects.rejected(names, rejects.BASE, active)
    cache = rejects.JevCache(cfg)
    said_no: list[dict] = []
    confirmed_bases = _confirm_unknown(entries, claims, base_texts, cfg, jev, cache, said_no)
    cache.save()

    def in_base(e: dict, bid: str) -> bool:
        if e.get("base_rejected"):
            return False
        if e.get("canonical"):
            return term_mentioned(e, base_texts[bid])
        return bid in confirmed_bases.get(e["term"], set())

    def best(names: list[str]) -> dict[str, int]:
        return {n: max((passage_strength(claims[i]) for i in by_name[n]["passages"]), default=0)
                for n in names if n in by_name}

    req_out: list[dict] = []
    for r in reqs.get("requirements", []):
        deg = _degree_check(r, claims)
        if deg is not None:
            req_out.append(deg)
            continue
        names = list(dict.fromkeys(_req_term_names(r)))
        covered = [n for n in names if by_name[n]["passages"]]
        pids = list(dict.fromkeys(i for n in covered for i in by_name[n]["passages"]))[:cap]
        status = "missing" if not covered else "covered" if len(covered) == len(names) else "partial"
        strength = max(best(covered).values(), default=0)
        method = "taxonomy" if covered else "none"
        # Synonym-only matches ("Data QA" for data quality) don't back the posting's wording,
        # but they do show the work, so the requirement is partly covered rather than missing.
        rel = list(dict.fromkeys(i for n in names if n not in covered for i in by_name[n]["related"]))
        if status == "missing" and rel:
            status, strength, pids, method = "partial", 1, rel[:cap], "related"
        req_out.append({"id": r["id"], "status": status, "strength": strength,
                        "passages": pids, "method": method})

    # Jev second look at requirements the taxonomy found nothing for, and at every soft-skill
    # requirement: the taxonomy only finds lines that use the skill's own word ("collaborated"), so
    # the story that shows it ("worked on a 5-person data team ...") needs Jev to be found and ranked.
    text_by_id = {r["id"]: r for r in reqs.get("requirements", [])}
    threshold = float((cfg.get("evidence") or {}).get("jev_yes", 0.6))

    def needs_look(o: dict) -> bool:
        if o["method"] == "degree":
            return False
        r = text_by_id[o["id"]]
        if o["status"] == "missing" or o["method"] == "related":  # related: only a synonym matched
            return True
        if r.get("weight") == "boilerplate":
            return False
        # A soft skill, or a soft term in a mixed requirement ("reports and presentations") that only
        # a self-description or skills list backs so far.
        soft = [n for n in _req_term_names(r) if taxonomy.category(n) == "Soft skills"]
        return _is_soft(r) or any(not any(passage_strength(claims[i]) >= 2 for i in by_name[n]["passages"])
                                  for n in soft if n in by_name)

    look = [text_by_id[o["id"]] for o in req_out if needs_look(o)]
    known = {o["id"]: o["passages"] for o in req_out}
    for rid, answers in _jev_pass(look, claims, cfg, jev, active, known).items():
        yes = [pid for pid, v in answers.items() if v >= threshold]
        if not yes:
            continue
        o = next(x for x in req_out if x["id"] == rid)
        # Real bullets Jev agrees with first, most confident first; then the taxonomy's other finds;
        # self-descriptions and skills lists last.
        merged = sorted(dict.fromkeys(yes + o["passages"]), key=lambda i: (
            passage_strength(claims[i]) < 2, i not in yes, -round(answers.get(i, 0.0), 1),
            *_rank_key(claims[i], folders)[1:]))[:cap]
        strength = max(passage_strength(claims[i]) for i in merged)
        o.update(status="covered", strength=max(strength, o["strength"]), passages=merged,
                 method="jev" if o["method"] in ("none", "related") else f"{o['method']}+jev")
        for n in _req_term_names(text_by_id[rid]):  # its terms are now backed by those passages
            if n in by_name and not by_name[n]["passages"]:
                by_name[n]["passages"] = [i for i in merged if i in yes]

    buckets: dict[str, dict] = {}
    for bid in base_texts:
        matched = {e["term"] for e in entries if in_base(e, bid)}
        inject = {e["term"] for e in entries if e["term"] not in matched and e["passages"]}
        related = {e["term"] for e in entries if e["term"] not in matched | inject and e["related"]}
        buckets[bid] = {
            "matched": [e["term"] for e in entries if e["term"] in matched],
            "injectable": [e["term"] for e in entries if e["term"] in inject],
            "related": [e["term"] for e in entries if e["term"] in related],
            "non_injectable": [e["term"] for e in entries if e["term"] not in matched | inject | related
                               and e["weight"] != "boilerplate"],
            "current_pct": _pct(entries, matched),
            "potential_pct": _pct(entries, matched | inject),
        }

    terms_out = [{"term": e["term"], "canonical": e["canonical"], "kind": e["kind"], "weight": e["weight"],
                  "passages": e["passages"], "related": e["related"],
                  "in_base": {bid: in_base(e, bid) for bid in base_texts}} for e in entries]
    present = [t["term"] for t in terms_out if t["passages"] or any(t["in_base"].values())]
    result = {
        "requirements": req_out, "terms": terms_out, "buckets": buckets,
        "present": present,
        "absent": [t["term"] for t in terms_out if t["term"] not in present and t["weight"] != "boilerplate"],
        "jev_said_no": said_no,
    }
    appdir.write_json(app_dir / "evidence.json", result)
    n_cov = sum(o["status"] == "covered" for o in req_out)
    appdir.log(app_dir, "evidence", f"{n_cov}/{len(req_out)} requirements covered; {len(present)} terms present")
    return result
