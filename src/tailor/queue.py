"""Step 0: pick the jobs worth tailoring and create their application folders.

Jev's gate questions only reorder: a job that fails or can't be checked is flagged
and sinks to the bottom of its tier, but is never dropped.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from src.posting_status import closed_reason, seen_date
from src.tailor import TailorError, appdir, store
from src.tailor.jev import Answer, Question, strip_identity
from src.tailor.paths import resolve

# (question, side that fails). For yesno, "yes" fails when P(yes) > threshold and
# "no" fails when P(yes) < threshold; score questions fail at <= score_fail.
GATE_QUESTIONS: list[tuple[Question, str | None]] = [
    (Question("seniority_fit", "score", "How well does the seniority of this role match an entry-level candidate with about one year of industry experience?"), None),
    (Question("must_haves", "score", "How many of the posting's must-have requirements does the resume cover?"), None),
    (Question("domain_fit", "score", "How well does the resume's domain and kind of work match what this role does?"), None),
    (Question("location_ok", "yesno", "Is the role either remote from anywhere in Canada or onsite/hybrid in Vancouver, BC?"), "no"),
    (Question("requires_phd", "yesno", "Does the posting require a PhD or doctorate?"), "yes"),
    (Question("years_ok", "yesno", "Does the posting ask for no more than about three years of experience?"), "no"),
    (Question("is_coop", "yesno", "Is this a co-op, practicum, or student work-term position?"), "yes"),
]

_HTML = re.compile(r"<(?:p|div|br|ul|ol|li|h[1-6]|strong|b|span|a)\b[^>]*>", re.I)
_SKIP_KEYS = {"id", "sources", "file_stem", "order", "contact", "label"}


def resume_text(data: Any) -> str:
    """Flatten a resume YAML structure to plain text, skipping ids and sources."""
    lines: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                if k not in _SKIP_KEYS:
                    walk(v)
        elif isinstance(node, list):
            if node and all(isinstance(x, str) for x in node):
                lines.append(", ".join(node))
            else:
                for x in node:
                    walk(x)
        elif node not in (None, ""):
            lines.append(" ".join(str(node).split()))

    walk(data)
    return "\n".join(lines)


def _base_resumes(cfg: dict[str, Any]) -> dict[str, str]:
    """Every base resume as identity-stripped plain text, keyed by base id."""
    import yaml

    try:
        from src.resume import load_contact

        contact = load_contact()
    except Exception:
        contact = None
    out = {}
    for path in sorted(resolve(cfg, "bases").glob("*.yaml")):
        text = resume_text(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
        out[path.stem] = strip_identity(text, contact)
    return out


def _gate_resume(bases: dict[str, str], posting: str, default: str) -> tuple[str, str]:
    """The base closest to this posting (most shared skills), so the gate judges a
    software job against the Software Developer base, not the Data Scientist one."""
    if not bases:
        return "", ""
    from src.tailor import taxonomy

    wanted = taxonomy.find(posting)

    def overlap(base_id: str) -> tuple[int, bool]:
        return len(wanted & taxonomy.find(bases[base_id])), base_id == default

    best = max(bases, key=overlap)
    return best, bases[best]


def _to_markdown(description: str) -> str:
    if _HTML.search(description or ""):
        from markdownify import markdownify

        return re.sub(r"\n{3,}", "\n\n", markdownify(description)).strip()
    return (description or "").strip()


def _eligible(conn, cfg: dict[str, Any], job_ids: list[int] | None) -> list[Any]:
    tiers = cfg.get("tiers") or ["A", "B"]
    if job_ids:
        marks = ",".join("?" * len(job_ids))
        rows = conn.execute(f"SELECT * FROM jobs WHERE id IN ({marks})", job_ids).fetchall()
        missing = set(job_ids) - {r["id"] for r in rows}
        if missing:
            raise TailorError(f"no such job id(s): {sorted(missing)}")
        taken = {r[0] for r in conn.execute("SELECT job_id FROM applications")}
        return [r for r in rows if r["id"] not in taken]
    marks = ",".join("?" * len(tiers))
    rows = conn.execute(
        f"SELECT * FROM jobs WHERE tier IN ({marks}) AND length(description) >= ? "
        "AND id NOT IN (SELECT job_id FROM applications) "
        "AND dedup_group_id NOT IN (SELECT j.dedup_group_id FROM jobs j "
        "JOIN applications a ON a.job_id = j.id) "
        # A job you dismissed or applied to yourself (any posting of it) is never drafted.
        "AND status NOT IN ('dismissed', 'applied') "
        "AND dedup_group_id NOT IN (SELECT dedup_group_id FROM jobs "
        "WHERE status IN ('dismissed', 'applied') AND dedup_group_id IS NOT NULL)",
        [*tiers, int(cfg.get("min_description_chars", 1000))],
    ).fetchall()
    # A posting that says it's filled internally or whose deadline has passed is
    # never drafted; one closed copy closes the whole group.
    closed = {g for g, desc, seen in conn.execute(
        "SELECT dedup_group_id, description, first_seen FROM jobs")
        if closed_reason(desc or "", seen=seen_date(seen))}
    best: dict[str, Any] = {}
    for r in rows:
        if r["dedup_group_id"] in closed:
            continue
        cur = best.get(r["dedup_group_id"])
        if cur is None or len(r["description"]) > len(cur["description"]):
            best[r["dedup_group_id"]] = r
    return list(best.values())


def _flags(answers: list[Answer], gate: dict[str, Any]) -> list[dict[str, Any]]:
    score_fail = gate.get("score_fail", 1)
    thr = gate.get("yes_threshold", 0.5)
    flags = []
    for (q, fail_on), a in zip(GATE_QUESTIONS, answers):
        flag = {"question": q.id, "text": q.text, "answer": a.value if a.ok else None,
                "confidence": a.confidence if a.ok else None}
        if not a.ok:
            flags.append({**flag, "reason": "unchecked"})
            continue
        v = a.value
        if q.type == "score":
            failed = v <= score_fail
        else:
            failed = (v > thr) if fail_on == "yes" else (v < thr)
        if failed:
            flags.append({**flag, "reason": "failed"})
    return flags


def _posting_md(r) -> str:
    return (
        f"# {r['title']}\n\n"
        f"- Company: {r['company']}\n- Location: {r['location']}\n- URL: {r['url']}\n"
        f"- Posted: {r['posted_date'] or 'unknown'}\n\n"
        f"{_to_markdown(r['description'])}\n"
    )


def run_queue(cfg: dict[str, Any], limit: int | None = None, jev=None,
              job_ids: list[int] | None = None) -> list[Path]:
    """Create application folders for the next jobs; returns their paths in queue order."""
    gate = cfg.get("gate") or {}
    tiers = cfg.get("tiers") or ["A", "B"]
    limit = limit if limit is not None else int(cfg.get("daily_cap", 3))
    if limit <= 0 and not job_ids:
        return []  # a run that only finishes waiting rounds (run_tailoring.ps1 -ResumeOnly)
    tier_pos = {t: i for i, t in enumerate(tiers)}
    conn = store.connect(resolve(cfg, "db"))
    try:
        # Tiers in jobs.db are only as new as the last scrape or rescore, so a scoring fix (a
        # location rule, a language skip) wouldn't reach the queue until then. Rescore first.
        if cfg.get("rescore_before_queue", True):
            from src.score import rescore_all
            from src.tailor.paths import _settings

            rescore_all(conn, _settings().get("score") or {})
        rows = _eligible(conn, cfg, job_ids)
        rows.sort(key=lambda r: (tier_pos.get(r["tier"], len(tiers)), -(r["score"] or 0), r["id"]))
        if not job_ids:
            # Jev only needs to look at enough candidates to fill the cap with room to reorder.
            rows = rows[: int(gate.get("max_candidates", max(limit * 5, 20)))]
        # Without a Jev key the gate is skipped (no flags); "unchecked" is kept for
        # answers that fail when Jev is configured, since those deserve a look.
        use_jev = jev is not None and getattr(jev, "available", True)
        bases = _base_resumes(cfg) if use_jev else {}
        default_base = gate.get("resume_base", "data-scientist")
        entries = []
        for r in rows:
            if not use_jev:
                entries.append((r, [], None))
                continue
            posting = _to_markdown(r["description"])
            base_id, resume = _gate_resume(bases, f"{r['title']}\n{posting}", default_base)
            state = (f"JOB POSTING\n{r['title']} at {r['company']}\n\n"
                     f"{posting}\n\nRESUME\n{resume}")
            answers = jev.ask(state, [q for q, _ in GATE_QUESTIONS])
            entries.append((r, _flags(answers, gate), base_id or None))
        entries.sort(key=lambda e: (tier_pos.get(e[0]["tier"], len(tiers)), bool(e[1]),
                                    -(e[0]["score"] or 0), e[0]["id"]))
        if not job_ids:
            entries = entries[:limit]
        apps_root = resolve(cfg, "applications")
        today = date.today().isoformat()
        out: list[Path] = []
        for rank, (r, flags, gate_base) in enumerate(entries, 1):
            folder = apps_root / appdir.folder_name(today, r["company"], r["title"])
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "posting.md").write_text(_posting_md(r), encoding="utf-8")
            appdir.save_app(folder, {
                "job_id": r["id"], "company": r["company"], "title": r["title"], "url": r["url"],
                "tier": r["tier"], "score": r["score"], "created": today, "status": "shortlisted",
                "gate": {"flags": flags, "flagged": bool(flags), "queue_rank": rank,
                         "checked": use_jev, "resume_base": gate_base},
                "base_id": None, "rounds": [], "best_round": None, "history": [],
            })
            note = f"rank {rank}, " + (f"{len(flags)} gate flag(s)" if flags else "no gate flags")
            if not use_jev:
                note += " (gate skipped: Jev not configured)"
            store.upsert_app(conn, appdir.log(folder, "queue", note), folder)
            out.append(folder)
        return out
    finally:
        conn.close()
