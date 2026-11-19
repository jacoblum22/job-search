"""The tools postings ask for that Jake's experience vault doesn't show, and how many postings ask.

Stats tab section "Skills you're missing". It reads the same gaps the score charges
(`vault_gaps.find_gaps`: an "or" list is met by any one of its tools, text about the employer
doesn't count, tools Jake confirmed or lacks come from the skill record), over the stored
postings that have a full description. Listings that are only a snippet are left out, since
absence of a tool in a snippet says nothing. Each posting counts once (a posting several
boards listed is one), using its longest description.

Each posting's gaps are saved (`CACHE`, keyed by the posting's text), so a later call reads only
the postings that are new or changed since; the whole file is thrown away when the vault index
or skill record changes, since that can change any posting's gaps.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from src.enrich import SNIPPET_MAX_CHARS
from src.vault_gaps import ROOT, find_gaps, load_vault

TOP = 25
CACHE = "materials/tailor/skill-gaps-cache.json"


def _scopes(tier: str | None) -> dict[str, bool]:
    return {"ab": tier in ("A", "B"), "live": tier != "skip"}


def _fingerprint(*paths: Path) -> str:
    h = hashlib.sha1()
    for p in paths:
        h.update(p.read_bytes() if p.exists() else b"-")
    return h.hexdigest()


def missing_skills(conn: sqlite3.Connection, score_cfg: dict[str, Any], root: Path = ROOT,
                   cache_path: Path | None = None) -> dict[str, Any]:
    """`score_cfg` is settings.yaml's `score:` section. {"error": ...} when the vault index isn't on
    this machine, else for each scope ("ab" = tier A and B, "live" = every posting that isn't
    skipped): how many postings were checked and the top missing tools with the postings asking
    and the share asking."""
    vault_cfg = score_cfg.get("vault_gaps") or {}
    index = vault_cfg.get("index", "materials/profile/vault-index.json")
    record = vault_cfg.get("record", "materials/tailor/skill-record.json")
    index_p = Path(index) if Path(index).is_absolute() else root / index
    record_p = Path(record) if Path(record).is_absolute() else root / record
    vault = load_vault(index_p, record_p)
    if vault is None:
        return {"error": "The experience vault index isn't on this computer, so missing skills can't be worked out here."}

    cache_path = cache_path or root / CACHE
    stamp = _fingerprint(index_p, record_p, root / "config" / "settings.yaml") + json.dumps(vault_cfg, sort_keys=True, default=str)
    try:
        saved = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    old = saved.get("postings", {}) if saved.get("stamp") == stamp else {}

    best: dict[str, sqlite3.Row] = {}  # one posting per dedup group: the longest description
    for r in conn.execute("SELECT dedup_group_id, title, description, tier FROM jobs").fetchall():
        d = best.get(r[0])
        if d is None or len(r[2] or "") > len(d[2] or ""):
            best[r[0]] = r
    stored = len(best)

    postings: dict[str, list] = {}  # group -> [text signature, [[label, preferred], ...]]
    checked = {"ab": 0, "live": 0}
    asked: dict[str, Counter] = {"ab": Counter(), "live": Counter()}
    required: dict[str, Counter] = {"ab": Counter(), "live": Counter()}
    full = fresh = 0
    for group, (_, title, desc, tier) in best.items():
        if len(desc or "") < SNIPPET_MAX_CHARS:
            continue
        full += 1
        sig = hashlib.sha1(f"{title}\n{desc}".encode()).hexdigest()
        hit = old.get(group)
        if hit and hit[0] == sig:
            gaps = hit[1]
        else:
            gaps = [[g.label, g.preferred] for g in find_gaps(f"{title}\n{desc}", vault, vault_cfg)]
            fresh += 1
        postings[group] = [sig, gaps]
        for scope, inside in _scopes(tier).items():
            if not inside:
                continue
            checked[scope] += 1
            for label, preferred in gaps:
                asked[scope][label] += 1
                if not preferred:
                    required[scope][label] += 1
    if fresh or len(postings) != len(old):
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = cache_path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"stamp": stamp, "postings": postings}), encoding="utf-8")
            tmp.replace(cache_path)
        except OSError:
            pass  # the numbers are still right; the next call just works them out again

    out: dict[str, Any] = {"stored": stored, "full": full}
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


if __name__ == "__main__":  # the dashboard server runs this in a child process: python -m src.skill_demand <db>
    import sys

    from src.db import connect
    from src.tailor import paths

    _conn = connect(Path(sys.argv[1]))
    print(json.dumps(missing_skills(_conn, paths._settings().get("score") or {})))
