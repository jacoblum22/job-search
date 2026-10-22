"""Cover-letter checks, called from checks.run_check (doc "letter")."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.tailor import phrases, rejects, taxonomy
from src.tailor.appdir import read_json, write_json
from src.tailor.paths import resolve

DEFAULT_GREETING = "Dear Hiring Manager,"
_GREETING = re.compile(r"^\s*(?:dear|hello|hi|to)\s+(.+?)\s*[,:]?\s*$", re.I)
_GENERIC = re.compile(
    r"hiring|recruit|team|committee|manager|madam|whom|department|talent|people|staff|"
    r"\bsir\b|\bcrew\b|\bpanel\b",
    re.I,
)
_HONORIFIC = re.compile(r"\b(?:mr|mrs|ms|miss|mx|dr|prof)\b\.?", re.I)
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_FAMILIAR = re.compile(r"\bfamiliar(?:ity)? with\s+([^.;:\n]{1,80})", re.I)
_KEEN = re.compile(
    r"\b(?:keen|eager|excited|looking|hoping|hope|want|wanting|ready)\s+to\s+(?:grow|learn|develop|build)\b"
    r"|\bgrow(?:ing)?\s+(?:my|as)\b",
    re.I,
)

# A course grade used as evidence ("88% in STAT 301", "STAT 301 (A)"): the work is the evidence.
_GRADE = re.compile(
    r"\b[A-Z]{3,4}\s?\d{3}\b[^.\n]{0,40}?(?:\b\d{2,3}(?:\.\d)?\s?%|\([A-D][+-]?\))"
    r"|\b\d{2,3}(?:\.\d)?\s?%\s+in\s+[A-Z]{3,4}\s?\d{3}\b"
    r"|(?i:\b(?:an?|earned|got|received)\s+(?:an?\s+)?[A-D][+-]?\s+in\s+)[A-Z]{3,4}\s?\d{3}\b"
)


def _must_missing(app_dir: Path, req: dict[str, Any]) -> bool:
    """Whether evidence.json has a `must` requirement the vault doesn't back at all, or a must term
    in `absent` ("AWS, particularly SageMaker" is only partial when AWS is backed; SageMaker is missing)."""
    path = app_dir / "evidence.json"
    if not path.exists():
        return True  # can't tell; don't warn
    musts = [r for r in req.get("requirements") or [] if isinstance(r, dict) and r.get("kind") == "must"]
    ev = read_json(path)
    ids = {r.get("id") for r in musts}
    if any(o.get("status") == "missing" and o.get("id") in ids
           for o in (ev.get("requirements") or []) if isinstance(o, dict)):
        return True
    absent = {str(t).lower() for t in ev.get("absent") or []}
    names = {str(n).lower() for r in musts for t in r.get("terms") or [] if isinstance(t, str)
             for n in (t, taxonomy.canonical(t)) if n}
    names |= {str(c).lower() for r in musts for c in r.get("canonical") or [] if isinstance(c, str)}
    return bool(absent & names)


def company_slug(company: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", company.lower()).strip("-")


def load_company_facts(cfg: dict[str, Any], company: str) -> dict[str, dict[str, Any]]:
    """Verified facts by id from materials/companies/<slug>/facts.json (empty when absent)."""
    p = resolve(cfg, "companies") / company_slug(company) / "facts.json"
    if not company or not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(raw, dict) and isinstance(raw.get("facts"), list):
        raw = raw["facts"]
    if isinstance(raw, dict):
        raw = [{"id": k, **v} for k, v in raw.items() if isinstance(v, dict)]
    out: dict[str, dict[str, Any]] = {}
    for f in raw if isinstance(raw, list) else []:
        if isinstance(f, dict) and f.get("id") and f.get("verified") is True:
            out[str(f["id"])] = f
    return out


def _fact_text(f: dict[str, Any]) -> str:
    # Only the quote was checked against its source; the "fact" sentence is the writer's own paraphrase.
    return str(f.get("quote") or "")


def _contact_ok(greeting_name: str, contact_name: str | None) -> bool:
    if not contact_name:
        return False
    toks = {t for t in re.findall(r"[a-z]+", _HONORIFIC.sub(" ", greeting_name.lower()))}
    allowed = set(re.findall(r"[a-z]+", contact_name.lower()))
    return bool(toks) and toks <= allowed


def check_greeting(letter: dict[str, Any], contact: dict[str, Any] | None) -> tuple[bool, str]:
    """(ok, person_named). Generic greetings are fine; a named person must be the verified contact."""
    m = _GREETING.match(letter.get("greeting") or "")
    if not m:
        return True, ""
    name = m.group(1).strip()
    if _GENERIC.search(name):
        return True, ""
    contact_name = (contact or {}).get("name") if isinstance(contact, dict) else None
    return _contact_ok(name, contact_name), name


def run_letter_checks(app_dir: Path, rnd: int, cfg: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Return {"criticals", "warnings", "greeting_reset"}; resets an unverified greeting in the file.

    `ctx` (built by checks.run_check): index, req, posting, base_text, claim_texts, own_texts, confirmed.
    """
    from src.tailor.checks import extract_numbers, number_keys  # lazy: checks imports this module

    path = app_dir / "drafts" / f"r{rnd}" / "cover-letter.json"
    out: dict[str, Any] = {"criticals": [], "warnings": [], "greeting_reset": False}
    if not path.exists():
        return out
    letter = read_json(path)
    if not isinstance(letter, dict) or not isinstance(letter.get("paragraphs"), list):
        return out

    def crit(code: str, msg: str, where: str = "letter", **data: Any) -> None:
        out["criticals"].append({"code": code, "message": msg, "path": where, "doc": "letter",
                                 **({"data": data} if data else {})})

    def warn(code: str, msg: str, where: str = "letter", **data: Any) -> None:
        out["warnings"].append({"code": code, "message": msg, "path": where, "doc": "letter",
                                **({"data": data} if data else {})})

    req = ctx["req"]
    contact = req.get("hiring_contact")
    ok, named = check_greeting(letter, contact)
    if not ok:
        crit(
            "greeting_unverified",
            f"greeting names {named!r}, who is not the verified hiring contact; reset to {DEFAULT_GREETING!r}",
            "greeting",
        )
        letter["greeting"] = DEFAULT_GREETING
        write_json(path, letter)
        out["greeting_reset"] = True

    paras = [p for p in letter["paragraphs"] if isinstance(p, dict)]
    facts = load_company_facts(cfg, req.get("company") or ctx.get("company", ""))
    posting_facts = req.get("company_facts") or []
    allowed_text = [ctx["base_text"], *ctx["claim_texts"]]
    allowed_text += [_fact_text(f) for f in posting_facts if isinstance(f, dict)]
    allowed_text += [_fact_text(f) for f in facts.values()]
    allowed_nums = set().union(*(number_keys(t) for t in allowed_text)) if allowed_text else set()
    vault_skills = taxonomy.find(ctx["base_text"] + "\n" + "\n".join(ctx["claim_texts"]))
    # Every skill a must term names: "Databricks SQL" is SQL and Databricks, though canonical() gives one.
    must_terms = {s for r in req.get("requirements") or [] if isinstance(r, dict) and r.get("kind") == "must"
                  for t in r.get("terms") or [] if isinstance(t, str)
                  for s in taxonomy.find(t) | {taxonomy.canonical(t) or t}}
    confirmed = ctx.get("confirmed") or set()

    cited_fact = False
    for i, p in enumerate(paras):
        where = f"paragraphs[{i}]"
        text = str(p.get("text", ""))
        for sid in p.get("sources") or []:
            if sid not in ctx["index"]:
                crit("unknown_source", f"{where} cites {sid!r}, which is not in the vault index", where)
            elif ctx["index"][sid].get("use", "claim") != "claim":
                crit("non_claim_source", f"{where} cites {sid!r}, which is not a claim passage", where)
        para_fact_text: list[str] = []
        for fid in p.get("company_facts") or []:
            ftext = None
            if fid.startswith("posting:"):
                try:
                    n = int(fid.split(":", 1)[1])  # 1-based, matching prompts/tailor/requirements.md
                    if n < 1:
                        raise IndexError(n)
                    f = posting_facts[n - 1]
                    ftext = _fact_text(f)
                except (ValueError, IndexError, TypeError, AttributeError):
                    ftext = None
            elif fid in facts:
                ftext = _fact_text(facts[fid])
            if ftext is None:
                crit("unverified_company_fact", f"{where} cites company fact {fid!r}, which is not verified", where)
            else:
                cited_fact = True
                para_fact_text.append(ftext)
        for raw in extract_numbers(text, allowed_nums):
            crit("invented_number", f"{where}: {raw!r} appears in no vault passage or company fact", where, term=raw)
        fact_skills = taxonomy.find("\n".join(para_fact_text))
        # The one "keen to grow into" sentence may name the missing must-haves it is about.
        keen_ok = {s for sent in _SENTENCE.split(text) if _KEEN.search(sent)
                   for s in taxonomy.find(sent) & must_terms}
        # As on the resume, a confirmed (skill, passage) pair backs the skill where that passage is cited.
        srcs = p.get("sources") or []
        for skill in sorted(taxonomy.find(text) - vault_skills - fact_skills - keen_ok):
            if taxonomy.is_hard(skill) and not any((rejects.key(skill), sid) in confirmed for sid in srcs):
                crit("invented_skill", f"{where}: mentions {skill}, which the passages it cites don't back", where, term=skill)
        for m in _FAMILIAR.finditer(text):
            for skill in sorted(taxonomy.find(m.group(1)) - vault_skills):
                warn("familiar_absent_term", f"{where}: 'familiar with' {skill}, which the vault does not show", where, term=skill)

    if paras and not cited_fact:
        warn("no_company_fact", "no paragraph cites a verified company-specific fact")
    if not 3 <= len(paras) <= 5:
        warn("paragraph_count", f"{len(paras)} paragraphs; aim for 3-5")
    full = "\n".join(str(p.get("text", "")) for p in paras)
    lo, hi = cfg.get("letter_words") or (190, 320)
    n_words = len(re.findall(r"[\w'’-]+", full))
    if paras and not lo <= n_words <= hi:
        short = n_words < lo
        # A short letter has room for what the resume lists without a bullet behind it.
        show = [t for t in ctx.get("listed_only") or [] if short]
        msg = f"{n_words} words; aim for about 200-300 ({'add' if short else 'cut'} a little)"
        if show:
            msg += "; use the room to show " + ", ".join(show) + ", which the resume lists without a bullet"
        warn("letter_length", msg, words=n_words, **({"show": show} if show else {}))
    if len(_KEEN.findall(full)) > 1:
        warn("keen_to_grow", "more than one 'keen to grow' style phrase")
    elif _KEEN.search(full) and not _must_missing(app_dir, req):
        warn("keen_not_must", "a 'keen to grow' style phrase, but no must-have is missing")
    for m in _GRADE.finditer(full):
        warn("course_grade", f"course grade used as evidence: {m.group(0)!r}", term=m.group(0))
    for i, p in enumerate(paras):
        for h in phrases.scan(str(p.get("text", "")), ctx["posting"], ctx["own_texts"], letter=True):
            warn("ai_phrase", f"paragraphs[{i}]: {h.code} {h.phrase!r}", f"paragraphs[{i}]")
    return out
