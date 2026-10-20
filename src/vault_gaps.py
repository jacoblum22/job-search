"""Tools a posting asks for that Jake's experience vault doesn't show.

The tier score used to read gaps from a hand-kept list in settings.yaml. This reads
them from the vault instead, so a tool counts as a gap only when no claim passage in
the vault index names it, and every tool the skills list knows can be one:

- A list where one option is enough ("Tableau, Looker, or Power BI", "such as R, SAS
  and Matlab", "(e.g. AWS, GCP)") is one ask, met by any one of its tools. An open
  list ("or similar", "e.g.", "etc") is also met by any tool Jake has of the same type.
- Tools named only in text about the employer ("Our portfolio includes ...") aren't asks.
- A tool asked for only in nice-to-have parts counts less (`preferred_factor`).
- A tool the vault shows only lightly (`light` in settings: one course, a badge) halves
  the gap instead of closing it.
- Each gap counts once per posting, and a product asked next to its platform
  (Cloud Composer with GCP) is one gap.

The skill record (`materials/tailor/skill-record.json`, kept by the tailoring pipeline in
`src/tailor/rejects.py`) corrects the vault: a tool Jake confirmed or the plan matched (`has`)
counts even when no passage names it, a tool he said he doesn't have (`lacks`) never counts,
and a passage marked as not showing a tool (`not_shown`) doesn't count for that tool.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.posting_sections import Sections, to_markdown
from src.skill_groups import _is_tool, alternative_groups
from src.tailor import taxonomy

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Vault:
    tools: frozenset[str]  # tools a claim passage names
    types: frozenset[str]  # the tool types those tools have (a light tool's type counts too)


@dataclass(frozen=True)
class Gap:
    label: str  # "dbt", or "Airflow or Dagster" for a list
    preferred: bool
    points: float


def _skill(term: str) -> str:
    return taxonomy.canonical(str(term)) or str(term)


def _is_hard_tool(s: str) -> bool:
    return taxonomy.is_hard(s) and _is_tool(s)


@lru_cache(maxsize=4)
def _load(path: str, mtime: float, record_path: str, record_mtime: float) -> Vault:
    passages = json.loads(Path(path).read_text(encoding="utf-8"))["passages"]
    record = json.loads(Path(record_path).read_text(encoding="utf-8") or "{}") if record_path else {}
    live = lambda section: [e for e in record.get(section) or [] if isinstance(e, dict) and not e.get("undone")]
    not_shown = {(_skill(e.get("term", "")), str(e.get("passage"))) for e in live("not_shown")}
    tools = {s for p in passages if p.get("use", "claim") == "claim" for s in taxonomy.find(p["text"])
             if _is_hard_tool(s) and (s, p.get("id")) not in not_shown}
    # Jev's remembered answers are soft-skill stories; the candidate's and the plan's matches are tools too.
    mine = {_skill(e.get("term", "")) for e in live("has") if e.get("source") == "jake"}
    tools |= {s for s in (_skill(e.get("term", "")) for e in live("has") if e.get("source") in ("jake", "plan"))
              if _is_hard_tool(s)}
    tools -= {_skill(e.get("skill", "")) for e in live("lacks")} - mine
    types = frozenset(t for s in tools for t in taxonomy.TOOL_TYPES.get(s, ()))
    return Vault(frozenset(tools), types)


def _abs(p: str | Path) -> Path:
    p = Path(p)
    return p if p.is_absolute() else ROOT / p


def load_vault(index_path: str | Path, record_path: str | Path | None = None) -> Vault | None:
    """The vault's tools, corrected by the skill record when there is one; None when the index
    isn't there (a fresh clone, CI)."""
    path = _abs(index_path)
    if not path.exists():
        return None
    record = _abs(record_path) if record_path else None
    if record is None or not record.exists():
        return _load(str(path), path.stat().st_mtime, "", 0.0)
    return _load(str(path), path.stat().st_mtime, str(record), record.stat().st_mtime)


def _family(skill: str) -> str:
    return taxonomy.RELATED.get(skill, skill)


def find_gaps(description: str, vault: Vault, cfg: dict[str, Any]) -> list[Gap]:
    """The posting's asks the vault doesn't cover, each with its (negative) points."""
    md = html.unescape(to_markdown(description))  # unescaped, so list positions line up with mentions
    sections = Sections(md)
    groups = alternative_groups(md)
    asked: dict[str, str] = {}  # tool -> "required" (any mention outside nice-to-haves) or "preferred"
    alone: dict[str, str] = {}  # the same, for mentions outside any list of options
    for _, name, rx in taxonomy.compiled():
        if not (taxonomy.is_hard(name) and _is_tool(name)):
            continue
        kinds, lone = set(), set()
        for m in rx.finditer(md):
            kind = sections.kind(m.start())
            if kind == "about":
                continue
            kinds.add(kind)
            if not any(g.span[0] <= m.start() < g.span[1] and name in g.skills for g in groups):
                lone.add(kind)
        if kinds:
            asked[name] = "preferred" if kinds == {"preferred"} else "required"
        if lone:
            alone[name] = "preferred" if lone == {"preferred"} else "required"

    # Tools the vault shows only lightly (one course, a badge) cover an ask for part of its cost.
    light = set(cfg.get("light") or ()) & vault.tools
    strong = vault.tools - light
    light_factor = cfg.get("light_factor", 0.5)
    default = cfg.get("points", -2)
    heavier = cfg.get("heavier") or {}
    factor = cfg.get("preferred_factor", 0.5)

    def points(skills: set[str], preferred: bool) -> float:
        p = min((heavier.get(s, default) for s in skills), key=abs)  # a list costs its cheapest option
        if skills & light:
            p *= light_factor
        return p * factor if preferred else p

    gaps: list[Gap] = []
    charged: set[str] = set()  # families already counted in this posting
    for g in groups:
        skills = {s for s in g.skills if s in asked}
        if not skills:
            continue
        met = bool(skills & strong) or ((g.open_end or g.reason != "or") and g.tool_type in vault.types)
        families = {_family(s) for s in skills}
        if met or families & charged:
            continue
        charged |= families
        preferred = all(asked[s] == "preferred" for s in skills)
        gaps.append(Gap(" or ".join(sorted(skills)), preferred, points(skills, preferred)))
    # "Experience building with C++, Go, or Python" is met by Python, but "professional experience
    # in C++" elsewhere in the posting is still its own ask.
    for s in sorted(alone, key=lambda s: (alone[s] != "required", s)):
        if s in strong or s in charged or _family(s) in charged:
            continue
        charged |= {s, _family(s)}
        preferred = alone[s] == "preferred"
        gaps.append(Gap(s, preferred, points({s}, preferred)))
    return gaps
