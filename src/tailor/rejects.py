"""Evidence matches that were rejected once, so they aren't made again.

The plan step lists weak matches it refused in `plan.json` `evidence_drops`
("problem solving" from a passage that only names the skill as a research
result). Those drops are copied into one shared list, `evidence-rejects.json`,
which the evidence step reads for every later job, and the grade step reads so
its repair notes never point back at a rejected passage. A drop the candidate
marks "Undo" in check.md stays in the list as undone, so it isn't re-added.

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
_UNDO = re.compile(r"^- \[(?P<x>[ xX])\] Undo\s+(?P<term>.+?) \((?P<passage>[^()]+)\):")


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


def load(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Every reject entry, undone ones included."""
    return _load(_path(cfg, "evidence_rejects"))["rejects"]


def pairs(cfg: dict[str, Any], app_dir: Path | None = None) -> set[tuple[str, str]]:
    """Active (term, passage) pairs: the shared list plus this application's own plan drops."""
    out = {(_key(r["term"]), r["passage"]) for r in load(cfg) if not r.get("undone")}
    if app_dir is not None:
        plan_path = Path(app_dir) / "plan.json"
        if plan_path.exists():
            for d in appdir.read_json(plan_path).get("evidence_drops") or []:
                if isinstance(d, dict) and d.get("term") and d.get("passage"):
                    out.add((_key(d["term"]), str(d["passage"])))
    return out


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
    ticked = {(_key(m["term"]), m["passage"].strip()) for line in check_md.splitlines()
              if (m := _UNDO.match(line)) and m["x"] != " "}
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
