"""Evidence matches that were rejected once, so they aren't made again.

The plan step lists weak matches it refused in `plan.json` `evidence_drops`
("problem solving" from a passage that only names the skill as a research
result). Those drops are copied into one shared list, `evidence-rejects.json`,
which the evidence step reads for every later job, and the grade step reads so
its repair notes never point back at a rejected passage. A drop the candidate
marks "Undo" in check.md stays in the list as undone, so it isn't re-added.

The reverse list, `evidence-confirms.json`, holds matches that are known to be
right: ones the candidate marked "This shows it" (or "Shows the skill" on a drop)
in check.md, ones the plan step added (`plan.json` `evidence_adds`), and soft-skill
passages Jev said yes to with high confidence. Pairs are keyed by skill (the
taxonomy name, or the soft-skill category), not by a posting's wording, so a match
confirmed for "collaborate across departments" also counts for "strong team player".
The candidate's own confirms win over any reject; a reject wins over a plan or Jev
confirm. Jev's remembered answers aren't asked again.

A third list, `known-gaps.json`, holds skills the candidate has said they don't have
("Node.js", "Power BI"). The evidence step matches nothing to them, doesn't ask Jev about
them and offers no "This shows it" candidates, so a known gap is reported as a fit gap
straight away instead of costing questions on every job.

The same folder holds a small cache of Jev's yes/no answers for terms the
taxonomy doesn't know, so a "no" sticks and the same question isn't paid twice.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from src.tailor import appdir, taxonomy
from src.tailor.paths import DEFAULT_PATHS, resolve

BASE = "base"  # passage value for a match in the base resume itself
# check.md's Undo lines carry the pair in a trailing comment ("<!-- undo: term | passage -->") so
# the visible text can be plain language; older check.md files used "Undo  term (passage): reason".
# A drop is decided with two exclusive boxes: "Set aside" (the rejection was right) or "Undo".
_UNDO = re.compile(r"^- \[[ xX]\] Set aside\s+- \[(?P<x>[ xX])\] Undo\s+.*<!-- undo: (?P<term>.+?) \| "
                   r"(?P<passage>[^>]+?) -->")
_OLD_UNDO = re.compile(r"^- \[(?P<x>[ xX])\] Undo\s+(?:.*<!-- undo: (?P<term>.+?) \| (?P<passage>[^>]+?) -->"
                       r"|(?P<old_term>.+?) \((?P<old_passage>[^()]+)\):)")


# A requirement line the candidate decides: "Doesn't show it" (record a reject) or "This shows it"
# (record a confirm), with the pair in a trailing comment.
_CONFIRM = re.compile(r"^- \[(?P<no>[ xX])\] Doesn't show it\s+- \[(?P<yes>[ xX])\] This shows it\s+.*"
                      r"<!-- confirm: (?P<term>.+?) \| (?P<passage>[^>]+?) -->")
STRONG = {"jake"}  # confirm sources that win over a reject


def _path(cfg: dict[str, Any], name: str) -> Path:
    return resolve({"paths": {**DEFAULT_PATHS, **(cfg.get("paths") or {})}}, name)


def _key(term: str) -> str:
    """One key per skill: "Problem-solving" and "problem solving" both map to the taxonomy name."""
    term = str(term)
    return " ".join((taxonomy.canonical(term) or term).lower().split())


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"rejects": []}
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    data.setdefault("rejects", [])
    return data


key = _key  # public name for other steps


def req_keys(r: dict[str, Any]) -> list[str]:
    """The skills a requirement asks for, as confirm keys: its terms' taxonomy names plus the soft-skill
    categories its wording falls under ("work well with others" is Collaboration). A requirement with
    neither is keyed by its own text."""
    canons = r.get("canonical") if isinstance(r.get("canonical"), list) else []
    names = []
    for i, t in enumerate(r.get("terms") or []):
        term, canon = (t.get("term", ""), t.get("canonical")) if isinstance(t, dict) else \
            (t, canons[i] if i < len(canons) else None)
        names.append(canon or taxonomy.canonical(term) or str(term))
    soft = [c for c in taxonomy.find(f"{r.get('text', '')}. {r.get('quote', '')}")
            if taxonomy.category(c) == "Soft skills"]
    keys = list(dict.fromkeys(_key(n) for n in names + soft if n))
    return keys or [_key(r.get("text", ""))]


def load(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Every reject entry, undone ones included."""
    return _load(_path(cfg, "evidence_rejects"))["rejects"]


def pairs(cfg: dict[str, Any], app_dir: Path | None = None) -> set[tuple[str, str]]:
    """Active (term, passage) pairs: the shared list plus this application's own plan drops."""
    out = {(_key(r["term"]), r["passage"]) for r in load(cfg) if not r.get("undone")}
    if app_dir is not None:
        out |= {(_key(d["term"]), str(d["passage"])) for d in _plan_list(app_dir, "evidence_drops")}
    # The candidate's own "this shows it" overrides any reject.
    return out - {k for k, c in _confirm_map(cfg).items() if c.get("source") in STRONG}


def _plan_list(app_dir: Path, name: str) -> list[dict[str, Any]]:
    plan_path = Path(app_dir) / "plan.json"
    if not plan_path.exists():
        return []
    return [d for d in appdir.read_json(plan_path).get(name) or []
            if isinstance(d, dict) and d.get("term") and d.get("passage")]


def rejected(names: Iterable[str], passage: str, active: set[tuple[str, str]]) -> bool:
    return any((_key(n), passage) in active for n in names if n)


def sync_plan_drops(app_dir: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Copy this application's plan drops into the shared list; return the ones that were new."""
    app_dir = Path(app_dir)
    plan_path = app_dir / "plan.json"
    if not plan_path.exists():
        return []
    drops = appdir.read_json(plan_path).get("evidence_drops") or []
    path = _path(cfg, "evidence_rejects")
    data = _load(path)
    known = {(_key(r["term"]), r["passage"]) for r in data["rejects"]}
    known |= {k for k, c in _confirm_map(cfg).items() if c.get("source") in STRONG}  # the candidate said it shows it
    job_id = appdir.load_app(app_dir).get("job_id")
    new = []
    for d in drops:
        if not (isinstance(d, dict) and d.get("term") and d.get("passage")):
            continue
        k = (_key(d["term"]), str(d["passage"]))
        if k in known:
            continue
        known.add(k)
        new.append({"term": d["term"], "passage": str(d["passage"]), "reason": d.get("reason", ""),
                    "job_id": job_id, "added": appdir.now()[:10]})
    if new:
        data["rejects"].extend(new)
        appdir.write_json(path, data)
    return new


def apply_undos(check_md: str, cfg: dict[str, Any]) -> list[tuple[str, str]]:
    """Mark the rejects ticked "Undo" in check.md as undone; return the pairs changed."""
    ticked = set()
    for line in check_md.splitlines():
        m = _UNDO.match(line)
        if m and m["x"] != " ":
            ticked.add((_key(m["term"]), m["passage"].strip()))
            continue
        m = _OLD_UNDO.match(line)
        if m and m["x"] != " ":
            ticked.add((_key(m["term"] or m["old_term"]), (m["passage"] or m["old_passage"]).strip()))
    if not ticked:
        return []
    path = _path(cfg, "evidence_rejects")
    data = _load(path)
    changed = []
    for r in data["rejects"]:
        k = (_key(r["term"]), r["passage"])
        if k in ticked and not r.get("undone"):
            r["undone"] = True
            changed.append(k)
    if changed:
        appdir.write_json(path, data)
    # "Shows the skill" means the passage does show it: remember that for every later job.
    add_confirms(cfg, [{"term": t, "passage": p, "source": "jake", "reason": "You said it shows the skill"}
                       for t, p in ticked if p != BASE])
    return changed


def scrub_evidence(evidence: dict[str, Any], req: dict[str, Any], active: set[tuple[str, str]]) -> dict[str, Any]:
    """A copy of evidence.json without rejected passages (for repair notes)."""
    if not active:
        return evidence
    ev = json.loads(json.dumps(evidence))
    names_by_req = {r["id"]: list(r.get("terms") or []) + [r.get("text", "")]
                    for r in req.get("requirements") or []}
    for e in ev.get("requirements") or []:
        names = names_by_req.get(e.get("id"), [])
        e["passages"] = [p for p in e.get("passages") or [] if not rejected(names, p, active)]
    for t in ev.get("terms") or []:
        names = [t.get("term", ""), t.get("canonical") or ""]
        before = bool(t.get("passages") or t.get("related"))
        for k in ("passages", "related"):
            t[k] = [p for p in t.get(k) or [] if not rejected(names, p, active)]
        # A term backed only by rejected passages (and not in a base) is no longer present.
        if before and not (t["passages"] or t["related"] or any((t.get("in_base") or {}).values())):
            ev["present"] = [x for x in ev.get("present") or [] if x != t.get("term")]
            if t.get("term") not in (ev.get("absent") or []):
                ev.setdefault("absent", []).append(t.get("term"))
    return ev


# --- Confirmed matches -------------------------------------------------------

def _load_confirms(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"confirms": []}
    data = json.loads(path.read_text(encoding="utf-8") or "{}")
    data.setdefault("confirms", [])
    return data


def load_confirms(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Every confirm entry, undone ones included."""
    return _load_confirms(_path(cfg, "evidence_confirms"))["confirms"]


def _confirm_map(cfg: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    return {(_key(c["term"]), str(c["passage"])): c for c in load_confirms(cfg) if not c.get("undone")}


def confirmed(cfg: dict[str, Any], app_dir: Path | None = None) -> dict[tuple[str, str], dict[str, Any]]:
    """Active confirmed pairs -> their entry: the shared list plus this application's plan adds,
    minus plan and Jev confirms that a reject overrides."""
    out = _confirm_map(cfg)
    if app_dir is not None:
        for d in _plan_list(app_dir, "evidence_adds"):
            out.setdefault((_key(d["term"]), str(d["passage"])), {**d, "source": "plan"})
    active = pairs(cfg, app_dir)
    return {k: c for k, c in out.items() if c.get("source") in STRONG or k not in active}


def add_confirms(cfg: dict[str, Any], items: Iterable[dict[str, Any]], job_id: Any = None) -> list[dict[str, Any]]:
    """Add confirms (each {term, passage, source, reason?, value?}); return the ones new or changed.

    A pair already in the list is only changed to make it stronger: a candidate's confirm
    replaces a plan or Jev one, and brings back an undone entry."""
    items = [i for i in items if i.get("term") and i.get("passage")]
    if not items:
        return []
    path = _path(cfg, "evidence_confirms")
    data = _load_confirms(path)
    by_key = {(_key(c["term"]), str(c["passage"])): c for c in data["confirms"]}
    out = []
    for i in items:
        k = (_key(i["term"]), str(i["passage"]))
        cur = by_key.get(k)
        strong = i.get("source") in STRONG
        if cur is not None and not (strong and (cur.get("undone") or cur.get("source") not in STRONG)):
            continue
        entry = {"term": i["term"], "passage": str(i["passage"]), "source": i.get("source", "plan"),
                 "reason": i.get("reason", ""), "job_id": i.get("job_id", job_id), "added": appdir.now()[:10]}
        if i.get("value") is not None:
            entry["value"] = round(float(i["value"]), 3)
        if cur is None:
            data["confirms"].append(entry)
        else:
            cur.clear()
            cur.update(entry)
        by_key[k] = entry
        out.append(entry)
    if out:
        appdir.write_json(path, data)
    return out


# --- Known gaps ----------------------------------------------------------------

def load_gaps(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Every known-gap entry ({skill, note?, added})."""
    path = _path(cfg, "known_gaps")
    if not path.exists():
        return []
    return (json.loads(path.read_text(encoding="utf-8") or "{}")).get("gaps") or []


def gap_keys(cfg: dict[str, Any]) -> set[str]:
    """Skill keys the candidate doesn't have; a candidate's own confirm for the skill wins."""
    mine = {k for (k, _), c in _confirm_map(cfg).items() if c.get("source") in STRONG}
    return {_key(g["skill"]) for g in load_gaps(cfg) if g.get("skill")} - mine


def sync_plan_adds(app_dir: Path, cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Copy this application's plan adds into the shared confirm list; return the new ones."""
    job_id = appdir.load_app(app_dir).get("job_id") if (Path(app_dir) / "app.json").exists() else None
    return add_confirms(cfg, [{**d, "source": "plan"} for d in _plan_list(app_dir, "evidence_adds")], job_id)


def apply_confirms(check_md: str, cfg: dict[str, Any], job_id: Any = None) -> dict[str, list[tuple[str, str]]]:
    """Record check.md's "Doesn't show it" / "This shows it" picks.

    "This shows it" adds a candidate confirm (and undoes a reject of the same pair);
    "Doesn't show it" undoes a confirm of the pair and adds a reject, so it isn't suggested again."""
    yes, no = [], []
    for line in check_md.splitlines():
        m = _CONFIRM.match(line)
        if not m:
            continue
        pair = (m["term"].strip(), m["passage"].strip())
        if m["yes"] != " ":
            yes.append(pair)
        elif m["no"] != " ":
            no.append(pair)
    add_confirms(cfg, [{"term": t, "passage": p, "source": "jake", "reason": "You said this shows it"}
                       for t, p in yes], job_id)
    keys_yes, keys_no = {(_key(t), p) for t, p in yes}, {(_key(t), p) for t, p in no}
    if keys_no:
        path = _path(cfg, "evidence_confirms")
        data = _load_confirms(path)
        hit = [c for c in data["confirms"] if (_key(c["term"]), str(c["passage"])) in keys_no and not c.get("undone")]
        for c in hit:
            c["undone"] = True
        if hit:
            appdir.write_json(path, data)
    path = _path(cfg, "evidence_rejects")
    data = _load(path)
    changed = False
    by_key = {(_key(r["term"]), r["passage"]): r for r in data["rejects"]}
    for k in keys_yes:
        r = by_key.get(k)
        if r is not None and not r.get("undone"):
            r["undone"] = changed = True
    for (term, pid), k in zip(no, [(_key(t), p) for t, p in no]):
        r = by_key.get(k)
        if r is None:
            r = {"term": term, "passage": pid, "reason": "You said this doesn't show it", "job_id": job_id,
                 "added": appdir.now()[:10]}
            data["rejects"].append(r)
            by_key[k] = r
            changed = True
        elif r.get("undone"):
            r.pop("undone")
            changed = True
    if changed:
        appdir.write_json(path, data)
    return {"confirmed": sorted(keys_yes), "rejected": sorted(keys_no)}


def add_evidence(evidence: dict[str, Any], req: dict[str, Any],
                 conf: dict[tuple[str, str], dict[str, Any]]) -> dict[str, Any]:
    """A copy of evidence.json with this application's confirmed pairs counted (for the grade step):
    the plan can add a match after the evidence step ran."""
    if not conf:
        return evidence
    ev = json.loads(json.dumps(evidence))
    by_key: dict[str, list[str]] = {}
    for (k, pid), c in conf.items():
        if c.get("source") != "jev":  # Jev's remembered answers already fed the evidence step
            by_key.setdefault(k, []).append(pid)
    for t in ev.get("terms") or []:
        add = [p for n in (t.get("term"), t.get("canonical")) if n for p in by_key.get(_key(n), [])]
        if add:
            t["passages"] = list(dict.fromkeys(add + list(t.get("passages") or [])))
            if t.get("term") not in (ev.get("present") or []):
                ev.setdefault("present", []).append(t.get("term"))
            ev["absent"] = [x for x in ev.get("absent") or [] if x != t.get("term")]
    reqs = {r.get("id"): r for r in req.get("requirements") or []}
    for e in ev.get("requirements") or []:
        r = reqs.get(e.get("id"))
        add = [p for k in req_keys(r) for p in by_key.get(k, [])] if r else []
        if add:
            e["passages"] = list(dict.fromkeys(add + list(e.get("passages") or [])))
            if e.get("status") == "missing":
                e["status"] = "covered" if len(req_keys(r)) == 1 else "partial"
    return ev


# --- Jev answer cache -------------------------------------------------------

class JevCache:
    """Cached yes/no answers keyed by (question, text); only parsed answers are stored."""

    def __init__(self, cfg: dict[str, Any]):
        self.path = _path(cfg, "jev_cache")
        self.data: dict[str, Any] = (json.loads(self.path.read_text(encoding="utf-8") or "{}")
                                     if self.path.exists() else {})
        self.dirty = False

    @staticmethod
    def key(question: str, text: str) -> str:
        return hashlib.sha256(f"{question}\n{text}".encode()).hexdigest()[:32]

    def get(self, question: str, text: str) -> float | None:
        hit = self.data.get(self.key(question, text))
        return None if hit is None else float(hit["value"])

    def put(self, question: str, text: str, value: float) -> None:
        self.data[self.key(question, text)] = {"question": question, "text": text[:120],
                                               "value": value, "date": appdir.now()[:10]}
        self.dirty = True

    def save(self) -> None:
        if self.dirty:
            appdir.write_json(self.path, self.data)
            self.dirty = False
