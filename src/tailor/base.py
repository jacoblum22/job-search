"""Step 3 (code half): pick the base resume and score every bullet's relevance.

The base is chosen by evidence: how much of the posting each base already
shows (`current_pct`). Every base can reach the same vault-backed terms, so
potential coverage ties and can't choose. Jev's holistic pick wins when it is
within a few points of the best. Claude then writes the
plan fields (headline, swap_in, ...) into the same plan.json.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.resume import iter_bullets
from src.tailor import TailorError, appdir
from src.tailor.evidence import term_mentioned
from src.tailor.jev import Question
from src.tailor.entries import available as entry_available
from src.tailor.sources import bullet_paths, load_bases, load_index

JEV_TIE_POINTS = 5.0
CHUNK = 20


def posting_summary(reqs: dict) -> str:
    lines = [f"Job: {reqs.get('title', '')} at {reqs.get('company', '')} (seniority: {reqs.get('seniority', 'unknown')})"]
    must = [r["text"] for r in reqs.get("requirements", []) if r.get("kind") == "must"]
    if must:
        lines.append("Must-haves: " + "; ".join(must))
    if reqs.get("responsibilities"):
        lines.append("Responsibilities: " + "; ".join(reqs["responsibilities"]))
    return "\n".join(lines)


def _base_label(base: dict) -> str:
    return str(base.get("label") or base["id"])


def _jev_pick(jev: Any, summary: str, bases: dict[str, dict]) -> str | None:
    if jev is None or len(bases) < 2:
        return None
    state = summary + "\n\nResume versions:\n" + "\n".join(f"- {bid}: {_base_label(b)}" for bid, b in bases.items())
    q = Question(id="base_pick", type="choice", options=list(bases),
                 text="Which resume version best fits this job?")
    a = jev.ask(state, [q])[0]
    return a.value if a.ok and a.value in bases else None


def _relevance(jev: Any, summary: str, items: dict[str, str], role_terms: list[dict]) -> dict[str, int]:
    """0-3 per item: Jev's score when it answers, else role terms mentioned (capped at 3)."""
    out: dict[str, int] = {}
    if jev is not None:
        keys = list(items)
        for i in range(0, len(keys), CHUNK):
            qs = [Question(id=k, type="score", scale=(0, 3),
                           text=f"How relevant is this resume line to the job above? Line: {items[k]}")
                  for k in keys[i:i + CHUNK]]
            for k, a in zip(keys[i:i + CHUNK], jev.ask(summary, qs)):
                if a.ok and isinstance(a.value, (int, float)):
                    out[k] = max(0, min(3, int(round(a.value))))
    for k, text in items.items():
        if k not in out:
            out[k] = min(3, sum(term_mentioned(t, text) for t in role_terms))
    return out


def run_base(app_dir: Path, cfg: dict[str, Any], jev: Any) -> dict:
    app_dir = Path(app_dir)
    reqs = appdir.read_json(app_dir / "requirements.json")
    ev = appdir.read_json(app_dir / "evidence.json")
    index = load_index(cfg)
    bases = load_bases(cfg)

    if not any(b in (ev.get("buckets") or {}) for b in bases):
        raise TailorError("evidence.json has no buckets for any base; re-run the evidence step")
    summary = posting_summary(reqs)
    pick = _jev_pick(jev, summary, bases)
    scores = {bid: float((ev["buckets"].get(bid) or {}).get("current_pct", 0.0)) for bid in bases}
    potential = {bid: float((ev["buckets"].get(bid) or {}).get("potential_pct", 0.0)) for bid in bases}
    best = max(sorted(scores), key=lambda b: (scores[b], potential[b]))
    chosen = pick if pick and scores[pick] >= scores[best] - JEV_TIE_POINTS else best
    base = bases[chosen]

    terms = ev.get("terms", [])
    bucket = ev["buckets"].get(chosen, {})
    inject = set(bucket.get("injectable", []))
    candidates = list(dict.fromkeys(
        pid for t in terms if t["term"] in inject for pid in t.get("passages", []) if pid in index))

    own = bullet_paths(base)
    items = dict(own)
    items.update({pid: index[pid]["text"] for pid in candidates if pid not in items})
    role_terms = [t for t in terms if t.get("weight") == "role"]
    relevance = _relevance(jev, summary, items, role_terms)

    # A bullet is protected when it is the only one carrying a must-have the base already shows.
    bullets = {p: b.get("text", "") for p, b in iter_bullets(base)}
    protected: list[str] = []
    for t in terms:
        if t.get("kind") != "must" or not t.get("in_base", {}).get(chosen):
            continue
        hits = [p for p, text in bullets.items() if term_mentioned(t, text)]
        if len(hits) == 1 and hits[0] not in protected:
            protected.append(hits[0])

    path = app_dir / "plan.json"
    plan = appdir.read_json(path) if path.exists() else {}
    plan.update({
        "base_id": chosen, "base_scores": scores, "reachable_pct": potential[chosen], "jev_pick": pick,
        "bullet_relevance": relevance, "candidate_passages": candidates,
        "protected_paths": protected,
        # Jobs and projects from the other bases or entries.yaml the draft may add (entries.py).
        "entry_library": entry_available(cfg, base),
    })
    appdir.write_json(path, plan)
    appdir.log(app_dir, "base", f"base {chosen} (shows {scores[chosen]}% now, {potential[chosen]}% reachable)", base_id=chosen)
    return plan
