"""The entry library: every job and project a draft may show, whatever base it started from.

Jake, Oct 25 2026: "Every base should have access to every single piece of the experience vault,
and should be able to swap in every story by its own judgement." The PointClickCare draft couldn't
swap the WiDS datathon for Vancouver House Finder because the data-analyst base had no House Finder
entry. An entry's header (title, company, name, context, dates, url) is a fact the draft never
writes, so it comes from here: the entries of all four bases, then `materials/resumes/entries.yaml`
for vault stories no base carries. Bullets are always written by the draft, citing vault passages.
"""

from __future__ import annotations

from typing import Any

import yaml

from src.tailor.paths import resolve
from src.tailor.sources import load_bases

SECTIONS = ("experience", "projects")
HEADER = ("id", "title", "company", "location", "name", "context", "dates", "url")


def _vault_prefix(e: dict[str, Any]) -> str | None:
    """The vault file an entry's bullets cite most (`vhf` for vhf.scheduled-pipeline)."""
    if e.get("vault"):
        return str(e["vault"])
    counts: dict[str, int] = {}
    for b in e.get("bullets") or []:
        for sid in b.get("sources") or []:
            pre = str(sid).split(".", 1)[0]
            counts[pre] = counts.get(pre, 0) + 1
    return max(counts, key=counts.get) if counts else None


def _header(e: dict[str, Any]) -> dict[str, Any]:
    out = {k: e[k] for k in HEADER if e.get(k) is not None}
    pre = _vault_prefix(e)
    return {**out, "vault": pre} if pre else out


def library(cfg: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    """{section: {entry id: header}} for every experience and project entry a draft may add."""
    out: dict[str, dict[str, dict[str, Any]]] = {s: {} for s in SECTIONS}
    for base in load_bases(cfg).values():
        for s in SECTIONS:
            for e in base.get(s) or []:
                if isinstance(e, dict) and e.get("id"):
                    out[s].setdefault(str(e["id"]), _header(e))
    # Next to the bases folder (materials/resumes/entries.yaml) unless settings name another file.
    path = resolve(cfg, "entries") if "entries" in cfg.get("paths", {}) else resolve(cfg, "bases").parent / "entries.yaml"
    if path.exists():
        extra = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for s in SECTIONS:
            for e in extra.get(s) or []:
                if isinstance(e, dict) and e.get("id"):
                    out[s].setdefault(str(e["id"]), _header(e))
    return out


def label(section: str, e: dict[str, Any]) -> str:
    if section == "experience":
        return f"{e.get('title', '')}, {e.get('company', '')}"
    return str(e.get("name", e.get("id", "")))


def available(cfg: dict[str, Any], base: dict[str, Any]) -> list[dict[str, Any]]:
    """Library entries the base doesn't have, for plan.json (`entry_library`)."""
    lib = library(cfg)
    out = []
    for s in SECTIONS:
        have = {e.get("id") for e in base.get(s) or []}
        for eid, e in lib[s].items():
            if eid not in have:
                out.append({"section": s, "id": eid, "label": label(s, e), "dates": e.get("dates", ""),
                            "vault": e.get("vault")})
    return out
