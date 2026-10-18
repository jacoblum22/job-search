"""Step 2: what in the vault backs each posting requirement, and what each base already says.

Facts come from the taxonomy (synonym-aware regexes); Jev only gets a second
look at requirements the taxonomy found nothing for, and its answers are
advisory evidence. Everything works with no Jev key.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from src.tailor import appdir, taxonomy
from src.tailor.jev import Question
from src.tailor.sources import base_text, claim_passages, load_bases, load_index

KIND_RANK = {"must": 0, "nice": 1, "keyword": 2}
SKILLS_FILES = {"skills-map.md", "soft-skills.md"}
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


# --- passage strength ------------------------------------------------------

def _skills_only(p: dict) -> bool:
    name = str(p.get("file", "")).replace("\\", "/").rsplit("/", 1)[-1].lower()
    return name in SKILLS_FILES or any("skill" in s.lower() for s in p.get("section") or [])


def passage_strength(p: dict) -> int:
    """1 skills list only, 2 a bullet, 3 a bullet with a concrete tool and a scope signal."""
    if _skills_only(p):
        return 1
    text = p.get("text", "")
    has_tool = any(taxonomy.is_hard(n) for n in taxonomy.find(text))
    has_scope = bool(p.get("numbers")) or bool(SCOPE_WORDS.search(text))
    return 3 if has_tool and has_scope else 2


def _origin_rank(p: dict) -> int:
    """Work bullets first, then project bullets, then coursework; tech-stack lists and other files last."""
    f = str(p.get("file", "")).replace("\\", "/").lower()
    rank = 0 if f.startswith("work/") else 1 if f.startswith("projects/") else 2 if "coursework" in f else 3
    if any("stack" in str(s).lower() for s in p.get("section") or []):
        rank += 2
    return rank


def _words(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9+#]+", s.lower()) if len(w) > 2 and w not in STOP}


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

def _jev_pass(reqs_missing: list[dict], claims: dict[str, dict], cfg: dict, jev: Any) -> dict[str, list[str]]:
    """Ask Jev whether candidate passages show each missing requirement; one call per passage."""
    ev_cfg = cfg.get("evidence") or {}
    n_cand = int(ev_cfg.get("jev_candidates", 15))
    threshold = float(ev_cfg.get("jev_yes", 0.6))
    if jev is None or not reqs_missing or n_cand <= 0:
        return {}
    per_passage: dict[str, list[tuple[dict, Question]]] = {}
    for r in reqs_missing:
        want = _words(r["text"] + " " + " ".join(_req_term_names(r)))
        ranked = sorted(((len(want & _words(p["text"])), pid) for pid, p in claims.items()), key=lambda x: -x[0])
        for overlap, pid in ranked[:n_cand]:
            if overlap <= 0:
                break
            q = Question(id=f"{r['id']}|{pid}", type="yesno",
                         text=f"Does this passage show the candidate has: {r['text']}?")
            per_passage.setdefault(pid, []).append((r, q))
    hits: dict[str, list[tuple[float, str]]] = {}
    for pid, items in per_passage.items():
        answers = jev.ask(claims[pid]["text"], [q for _, q in items])
        for (r, _), a in zip(items, answers):
            if a.ok and isinstance(a.value, (int, float)) and a.value >= threshold:
                hits.setdefault(r["id"], []).append((float(a.value), pid))
    return {rid: [pid for _, pid in sorted(v, key=lambda x: -x[0])] for rid, v in hits.items()}


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
    ranked = sorted(claims.values(), key=lambda p: (passage_strength(p) < 2, _origin_rank(p),
                                                    -passage_strength(p), p.get("source") != "primary"))
    for e in entries:
        hits = [p for p in ranked if term_mentioned(e, p["text"])]
        e["passages"] = [p["id"] for p in hits if term_exact(e, p["text"])][:cap]
        e["related"] = [p["id"] for p in hits if not term_exact(e, p["text"])][:3]

    def best(names: list[str]) -> dict[str, int]:
        return {n: max((passage_strength(claims[i]) for i in by_name[n]["passages"]), default=0)
                for n in names if n in by_name}

    req_out: list[dict] = []
    for r in reqs.get("requirements", []):
        names = list(dict.fromkeys(_req_term_names(r)))
        covered = [n for n in names if by_name[n]["passages"]]
        pids = list(dict.fromkeys(i for n in covered for i in by_name[n]["passages"]))[:cap]
        status = "missing" if not covered else "covered" if len(covered) == len(names) else "partial"
        strength = max(best(covered).values(), default=0)
        req_out.append({"id": r["id"], "status": status, "strength": strength,
                        "passages": pids, "method": "taxonomy" if covered else "none"})

    # Jev second look at requirements the taxonomy found nothing for.
    text_by_id = {r["id"]: r for r in reqs.get("requirements", [])}
    missing = [text_by_id[o["id"]] for o in req_out if o["status"] == "missing"]
    for rid, pids in _jev_pass(missing, claims, cfg, jev).items():
        o = next(x for x in req_out if x["id"] == rid)
        o.update(status="covered", strength=2, passages=pids, method="jev")
        for n in _req_term_names(text_by_id[rid]):  # its terms are now backed by those passages
            if n in by_name and not by_name[n]["passages"]:
                by_name[n]["passages"] = list(pids)

    buckets: dict[str, dict] = {}
    for bid, text in base_texts.items():
        matched = {e["term"] for e in entries if term_mentioned(e, text)}
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
                  "in_base": {bid: term_mentioned(e, t) for bid, t in base_texts.items()}} for e in entries]
    present = [t["term"] for t in terms_out if t["passages"] or any(t["in_base"].values())]
    result = {
        "requirements": req_out, "terms": terms_out, "buckets": buckets,
        "present": present,
        "absent": [t["term"] for t in terms_out if t["term"] not in present and t["weight"] != "boilerplate"],
    }
    appdir.write_json(app_dir / "evidence.json", result)
    n_cov = sum(o["status"] == "covered" for o in req_out)
    appdir.log(app_dir, "evidence", f"{n_cov}/{len(req_out)} requirements covered; {len(present)} terms present")
    return result
