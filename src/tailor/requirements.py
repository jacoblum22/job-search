"""Step 1 (code half): validate and normalize the requirements.json Claude wrote.

Claude reads the posting and extracts requirements; code then refuses anything
it cannot verify. A requirement whose quote is not in the posting is dropped
(it may be a hallucination), so every later step only sees checkable items.
"""

from __future__ import annotations

import csv
import re
from datetime import date
from pathlib import Path
from typing import Any

from src.tailor import TailorError, appdir, taxonomy
from src.tailor.paths import resolve

KINDS = {"must", "nice"}
WEIGHTS = {"role", "boilerplate"}
ROLES = {"hiring_manager", "recruiter"}
CSV_HEADER = ["term", "job_id", "date"]


def norm_text(s: str) -> str:
    """Lower-case words only: ignores case, whitespace, punctuation, curly quotes, bullets."""
    s = s.replace("’", "'").replace("‘", "'")
    return " ".join(re.findall(r"[a-z0-9]+", s.lower()))


def quote_in(quote: Any, posting_norm: str) -> bool:
    q = norm_text(quote) if isinstance(quote, str) else ""
    return bool(q) and f" {q} " in f" {posting_norm} "


def _need(cond: bool, where: str, what: str) -> None:
    if not cond:
        raise TailorError(f"requirements.json: {where} {what}")


def _validate(data: Any) -> None:
    _need(isinstance(data, dict), "top level", "must be an object")
    reqs = data.get("requirements")
    _need(isinstance(reqs, list), "'requirements'", "must be a list")
    seen: set[str] = set()
    for i, r in enumerate(reqs):
        w = f"requirements[{i}]"
        _need(isinstance(r, dict), w, "must be an object")
        _need(isinstance(r.get("id"), str) and r["id"], w, "needs a string 'id'")
        _need(r["id"] not in seen, w, f"has duplicate id {r['id']!r}")
        seen.add(r["id"])
        _need(isinstance(r.get("text"), str) and r["text"].strip(), w, "needs a non-empty 'text'")
        _need(r.get("kind") in KINDS, w, f"'kind' must be one of {sorted(KINDS)}, got {r.get('kind')!r}")
        _need(r.get("weight") in WEIGHTS, w, f"'weight' must be one of {sorted(WEIGHTS)}, got {r.get('weight')!r}")
        terms = r.get("terms")
        _need(isinstance(terms, list) and all(isinstance(t, str) and t.strip() for t in terms),
              w, "'terms' must be a list of non-empty strings")
        _need(isinstance(r.get("quote"), str), w, "needs a string 'quote'")
        tier = r.get("tier")
        _need(tier is None or (isinstance(tier, int) and not isinstance(tier, bool)), w, "'tier' must be an integer")
    kws = data.get("keywords", [])
    _need(isinstance(kws, list), "'keywords'", "must be a list")
    for i, k in enumerate(kws):
        w = f"keywords[{i}]"
        _need(isinstance(k, dict), w, "must be an object")
        _need(isinstance(k.get("term"), str) and k["term"].strip(), w, "needs a non-empty 'term'")
        _need(k.get("weight") in WEIGHTS, w, f"'weight' must be one of {sorted(WEIGHTS)}, got {k.get('weight')!r}")
        _need(isinstance(k.get("quote"), str), w, "needs a string 'quote'")
    resp = data.get("responsibilities", [])
    _need(isinstance(resp, list) and all(isinstance(x, str) for x in resp),
          "'responsibilities'", "must be a list of strings")
    facts = data.get("company_facts", [])
    _need(isinstance(facts, list), "'company_facts'", "must be a list")
    for i, f in enumerate(facts):
        w = f"company_facts[{i}]"
        _need(isinstance(f, dict) and isinstance(f.get("fact"), str), w, "needs a string 'fact'")
        _need(isinstance(f.get("quote"), str), w, "needs a string 'quote'")
    hc = data.get("hiring_contact")
    if hc is not None:
        _need(isinstance(hc, dict), "'hiring_contact'", "must be an object or null")
        _need(isinstance(hc.get("name"), str), "'hiring_contact'", "needs a string 'name'")
        _need(hc.get("role") in ROLES, "'hiring_contact'", f"'role' must be one of {sorted(ROLES)}")
        _need(isinstance(hc.get("quote"), str), "'hiring_contact'", "needs a string 'quote'")


def _append_unknown(path: Path, terms: list[str], job_id: Any) -> None:
    """Add (term, job_id, date) rows, skipping a term already logged for this job."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: set[tuple[str, str]] = set()
    if path.exists():
        with path.open(encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                existing.add((row.get("term", "").lower(), str(row.get("job_id", ""))))
    new = not path.exists() or path.stat().st_size == 0
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(CSV_HEADER)
        for t in terms:
            key = (t.lower(), str(job_id if job_id is not None else ""))
            if key in existing:
                continue
            existing.add(key)
            w.writerow([t, "" if job_id is None else job_id, date.today().isoformat()])


def normalize(app_dir: Path, cfg: dict[str, Any]) -> dict:
    """Validate requirements.json, add canonical names, verify quotes, write it back."""
    app_dir = Path(app_dir)
    data = appdir.read_json(app_dir / "requirements.json")
    _validate(data)
    posting_path = app_dir / "posting.md"
    if not posting_path.exists():
        raise TailorError(f"posting.md is missing in {app_dir}")
    posting = norm_text(posting_path.read_text(encoding="utf-8"))

    data.pop("_normalized", None)
    dropped: list[dict] = []
    unknown: list[str] = []

    def note_unknown(term: str, canon: str | None) -> None:
        if canon is None and term.lower() not in {u.lower() for u in unknown}:
            unknown.append(term)

    reqs = []
    for r in data["requirements"]:
        if not quote_in(r["quote"], posting):
            dropped.append({"type": "requirement", "id": r["id"], "text": r["text"],
                            "reason": "quote not found in posting"})
            continue
        r["canonical"] = [taxonomy.canonical(t) for t in r["terms"]]
        if r.get("weight", "role") != "boilerplate":  # perks and EEO text aren't skills to learn
            for t, c in zip(r["terms"], r["canonical"]):
                note_unknown(t, c)
        reqs.append(r)
    data["requirements"] = reqs

    kws = []
    for k in data.get("keywords", []):
        if not quote_in(k["quote"], posting):
            dropped.append({"type": "keyword", "term": k["term"], "reason": "quote not found in posting"})
            continue
        k["canonical"] = taxonomy.canonical(k["term"])
        if k.get("weight", "role") != "boilerplate":
            note_unknown(k["term"], k["canonical"])
        kws.append(k)
    data["keywords"] = kws

    facts = []
    for f in data.get("company_facts", []):
        if quote_in(f["quote"], posting):
            facts.append(f)
        else:
            dropped.append({"type": "company_fact", "fact": f["fact"], "reason": "quote not found in posting"})
    data["company_facts"] = facts

    hc = data.get("hiring_contact")
    if hc is not None:
        name = norm_text(hc["name"])
        if not name or not quote_in(hc["quote"], posting):
            reason = "quote not found in posting"
        elif f" {name} " not in f" {norm_text(hc['quote'])} ":
            reason = "quote does not contain the name"
        else:
            reason = ""
        if reason:
            dropped.append({"type": "hiring_contact", "name": hc["name"], "reason": reason})
            data["hiring_contact"] = None
    else:
        data["hiring_contact"] = None

    data["_normalized"] = {"dropped": dropped, "unknown_terms": unknown}
    appdir.write_json(app_dir / "requirements.json", data)

    app = appdir.load_app(app_dir)
    if unknown:
        unknown_path = resolve(cfg, "unknown_terms")
        with appdir.file_lock(unknown_path):
            _append_unknown(unknown_path, unknown, app.get("job_id"))
    appdir.log(app_dir, "requirements",
               f"{len(reqs)} requirements, {len(kws)} keywords; dropped {len(dropped)}; "
               f"{len(unknown)} unknown terms")
    return data
