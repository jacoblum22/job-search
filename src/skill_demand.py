"""The tools postings ask for that Jake's experience vault doesn't show, and how many postings ask.

Stats tab section "Skills you're missing". It reads the same gaps the score charges
(`vault_gaps.find_gaps`: an "or" list is met by any one of its tools, text about the employer
doesn't count, tools Jake confirmed or lacks come from the skill record), over the stored
postings that have a full description. Listings that are only a snippet are left out, since
absence of a tool in a snippet says nothing. Each posting counts once (a posting several
boards listed is one), using its longest description.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from src.enrich import SNIPPET_MAX_CHARS
from src.vault_gaps import ROOT, find_gaps, load_vault

TOP = 25


def _scopes(tier: str | None) -> dict[str, bool]:
    return {"ab": tier in ("A", "B"), "live": tier != "skip"}


def missing_skills(conn: sqlite3.Connection, score_cfg: dict[str, Any], root: Path = ROOT) -> dict[str, Any]:
    """`score_cfg` is settings.yaml's `score:` section. {"error": ...} when the vault index isn't on this machine, else for each scope
    ("ab" = tier A and B, "live" = every posting that isn't skipped): how many postings were
    checked and the top missing tools with the postings asking and the share asking."""
    vault_cfg = score_cfg.get("vault_gaps") or {}
    index = vault_cfg.get("index", "materials/profile/vault-index.json")
    record = vault_cfg.get("record", "materials/tailor/skill-record.json")
    vault = load_vault(root / index if not Path(index).is_absolute() else index,
                       root / record if not Path(record).is_absolute() else record)
    if vault is None:
        return {"error": "The experience vault index isn't on this computer, so missing skills can't be worked out here."}

    best: dict[str, sqlite3.Row] = {}  # one posting per dedup group: the longest description
    for r in conn.execute("SELECT dedup_group_id, title, description, tier FROM jobs").fetchall():
        d = best.get(r[0])
        if d is None or len(r[2] or "") > len(d[2] or ""):
            best[r[0]] = r
    stored = len(best)
    full = [r for r in best.values() if len(r[2] or "") >= SNIPPET_MAX_CHARS]

    checked = {"ab": 0, "live": 0}
    asked: dict[str, Counter] = {"ab": Counter(), "live": Counter()}
    required: dict[str, Counter] = {"ab": Counter(), "live": Counter()}
    for title, desc, tier in ((r[1], r[2], r[3]) for r in full):
        gaps = find_gaps(f"{title}\n{desc}", vault, vault_cfg)
        for scope, inside in _scopes(tier).items():
            if not inside:
                continue
            checked[scope] += 1
            for g in gaps:
                asked[scope][g.label] += 1
                if not g.preferred:
                    required[scope][g.label] += 1

    out: dict[str, Any] = {"stored": stored, "full": len(full)}
    for scope in ("ab", "live"):
        n = checked[scope]
        out[scope] = {
            "postings": n,
            "skills": [
                {"skill": s, "postings": c, "required": required[scope][s], "percent": round(100 * c / n, 1)}
                for s, c in asked[scope].most_common(TOP)
            ] if n else [],
        }
    return out
