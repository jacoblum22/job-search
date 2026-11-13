"""Step 0: pick the jobs worth tailoring and create their application folders.

Jev's gate questions take points off the score (Jake, Nov 12 2026): each failed question costs
`score.jev_flag_penalty` points (up to `score.jev_max_penalty`), saved in the jev_gate table so the
dashboard's score is the same number the queue ranks by. A job is never dropped for it, and a question
Jev couldn't answer costs nothing.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any

from src.concurrency import parallel_map
from src.posting_status import closed_reason, seen_date
from src.retention import posted_on
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
        taken = {r[0] for r in conn.execute("SELECT job_id FROM applications WHERE status != 'shortlisted'")}
        return [r for r in rows if r["id"] not in taken]
    marks = ",".join("?" * len(tiers))
    rows = conn.execute(
        f"SELECT * FROM jobs WHERE tier IN ({marks}) AND length(description) >= ? "
        # A folder that is only "shortlisted" (made, nothing drafted) doesn't take the job out: it
        # competes on score like any other, and its folder is reused (Jake, Nov 12 2026).
        "AND id NOT IN (SELECT job_id FROM applications WHERE status != 'shortlisted') "
        "AND dedup_group_id NOT IN (SELECT j.dedup_group_id FROM jobs j "
        "JOIN applications a ON a.job_id = j.id WHERE a.status != 'shortlisted') "
        # A job you dismissed or applied to yourself (any posting of it) is never drafted.
        "AND status NOT IN ('dismissed', 'applied') "
        "AND dedup_group_id NOT IN (SELECT dedup_group_id FROM jobs "
        "WHERE status IN ('dismissed', 'applied') AND dedup_group_id IS NOT NULL)",
        [*tiers, int(cfg.get("min_description_chars", 1000))],
    ).fetchall()
    # A posting that says it's filled internally or whose deadline has passed is
    # never drafted; one closed copy closes the whole group.
    closed = {g for g, desc, seen, raw in conn.execute(
        "SELECT dedup_group_id, description, first_seen, raw FROM jobs")
        if closed_reason(desc or "", seen=seen_date(seen), raw=raw)}
    best: dict[str, Any] = {}
    for r in rows:
        if r["dedup_group_id"] in closed:
            continue
        cur = best.get(r["dedup_group_id"])
        if cur is None or len(r["description"]) > len(cur["description"]):
            best[r["dedup_group_id"]] = r
    return list(best.values())


def _posted_days(conn) -> dict[str, date]:
    """When each dedup group was first posted: the earliest date any of its postings
    gives, else the day it was first seen (as on the dashboard)."""
    out: dict[str, date] = {}
    for g, posted, raw, first, last in conn.execute(
            "SELECT dedup_group_id, posted_date, raw, first_seen, last_seen FROM jobs"):
        day = posted_on(posted, raw, seen_date(last)) or seen_date(first)
        if day and (g not in out or day < out[g]):
            out[g] = day
    return out


def gate_penalty(flags: list[dict[str, Any]], score_cfg: dict[str, Any]) -> tuple[int, str]:
    """Points a job's failed quick-fit answers take off its score, and why. A question Jev couldn't
    answer ("unchecked") costs nothing."""
    per = int(score_cfg.get("jev_flag_penalty", 10))
    cap = int(score_cfg.get("jev_max_penalty", 40))
    failed = [f["question"].replace("_", " ") for f in flags if f.get("reason") == "failed"]
    return min(cap, per * len(failed)), ", ".join(failed)


def _save_gate_penalties(conn, entries: list, stored: dict, score_cfg: dict[str, Any],
                         rescore: bool = True) -> dict[int, int]:
    """Write each checked job's penalty to the jev_gate table, rescore so the dashboard shows the same
    number the queue ranks by, and return, per job id, how many points to add to its (already rescored
    from an earlier check) score to get the new one."""
    from src.score import rescore_all

    out: dict[int, int] = {}
    stamp = appdir.now()
    for r, flags, _ in entries:
        points, why = gate_penalty(flags, score_cfg)
        out[r["id"]] = int(stored.get(r["dedup_group_id"], (0, ""))[0]) - points
        conn.execute("DELETE FROM jev_gate WHERE job_id IN (SELECT id FROM jobs WHERE dedup_group_id = ?) "
                     "AND job_id != ?", (r["dedup_group_id"], r["id"]))
        conn.execute(
            "INSERT INTO jev_gate (job_id, penalty, reason, checked_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(job_id) DO UPDATE SET penalty = excluded.penalty, reason = excluded.reason, "
            "checked_at = excluded.checked_at", (r["id"], points, why, stamp))
    conn.commit()
    if rescore:
        rescore_all(conn, score_cfg)
    return out


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
              job_ids: list[int] | None = None, plan_only: bool = False) -> list[Path]:
    """Create application folders for the next jobs; returns their paths in queue order.

    With `plan_only` no folder is made: every eligible job, in rank order, is written to open-check/plan.json for the browser step (see `queue_from_plan`)."""
    gate = cfg.get("gate") or {}
    tiers = cfg.get("tiers") or ["A", "B"]
    limit = limit if limit is not None else int(cfg.get("daily_cap", 3))
    if limit <= 0 and not job_ids:
        return []  # a run that only finishes waiting rounds (run_tailoring.ps1 -ResumeOnly)
    conn = store.connect(resolve(cfg, "db"))
    try:
        # Tiers in jobs.db are only as new as the last scrape or rescore, so a scoring fix (a
        # location rule, a language skip) wouldn't reach the queue until then. Rescore first.
        if cfg.get("rescore_before_queue", True):
            from src.score import rescore_all
            from src.tailor.paths import _settings

            rescore_all(conn, _settings().get("score") or {})
        rows = _eligible(conn, cfg, job_ids)
        # Strictly by score (the age penalty already covers freshness), then newest. Jev's quick fit
        # check takes points off the score (below), so the order is one number and nothing sinks.
        posted = _posted_days(conn)
        from src.score import load_jev_penalties
        from src.tailor.paths import _settings

        score_cfg = _settings().get("score") or {}
        stored = load_jev_penalties(conn)   # points already off each row's score from an earlier check

        def order(r, adjust: int = 0) -> tuple:
            day = posted.get(r["dedup_group_id"]) or date.min
            return (-((r["score"] or 0) + adjust), -day.toordinal(), r["id"])

        rows.sort(key=order)
        rest: list[Any] = []
        if not job_ids:
            # Jev only needs to look at enough candidates to fill the cap with room to reorder.
            cut = int(gate.get("max_candidates", max(limit * 5, 20)))
            rows, rest = rows[:cut], rows[cut:]  # `rest` only matters to the open check's plan
        # Without a Jev key the gate is skipped (no flags); "unchecked" is kept for
        # answers that fail when Jev is configured, since those deserve a look.
        use_jev = jev is not None and getattr(jev, "available", True)
        bases = _base_resumes(cfg) if use_jev else {}
        default_base = gate.get("resume_base", "data-scientist")
        entries = []
        if not use_jev:
            entries = [(r, [], None) for r in rows]
        else:
            states = []
            for r in rows:
                posting = _to_markdown(r["description"])
                base_id, resume = _gate_resume(bases, f"{r['title']}\n{posting}", default_base)
                states.append((base_id, f"JOB POSTING\n{r['title']} at {r['company']}\n\n"
                                        f"{posting}\n\nRESUME\n{resume}"))
            # One Jev call per candidate, several at once: the same questions and answers as one
            # after another, in a fraction of the time (about 4 minutes for 20 candidates, Oct 29 2026).
            answered = parallel_map(lambda st: jev.ask(st[1], [q for q, _ in GATE_QUESTIONS]), states,
                                    int(gate.get("parallel", 6)))
            for r, (base_id, _), answers in zip(rows, states, answered):
                entries.append((r, _flags(answers, gate), base_id or None))
        # Save each checked job's penalty so the dashboard score matches, then rank by the new score.
        adjust: dict[int, int] = {}
        if use_jev:
            adjust = _save_gate_penalties(conn, entries, stored, score_cfg,
                                          rescore=bool(cfg.get("rescore_before_queue", True)))
        entries.sort(key=lambda e: order(e[0], adjust.get(e[0]["id"], 0)))
        if plan_only:
            # The whole ranked list: the gated candidates, then every other eligible job, all by score,
            # so the open check can keep going down it until the cap is filled (Jake, Nov 12).
            everything = [*entries, *[(r, [], None) for r in rest]]
            everything.sort(key=lambda e: order(e[0], adjust.get(e[0]["id"], 0)))
            write_plan(cfg, everything, limit, use_jev)
            return []
        if not job_ids:
            entries = entries[:limit]
        return _make_folders(conn, cfg, entries, use_jev)
    finally:
        conn.close()


# ── The open check (Jake, Nov 12 2026) ─────────────────────────────────────────────────
# A posting can close before we get to it. `queue --plan` lists the next jobs in order, the
# wrapper has Claude in Chrome open each link (prompts/tailor/open-check.md) and write a verdict
# file per job, then `queue --from-plan` dismisses the closed ones and takes the next open job
# in line instead, so a run still drafts `daily_cap` jobs. The same read also catches an obvious
# miss ("miss": a certain deal-breaker, as the requirements step's no_chance / hard stop) so the
# final set is open jobs that aren't obvious misses (Jake, Nov 12 2026). A job the browser
# couldn't read ("unknown") is kept: a page we can't judge never costs a job.

# Job-search aggregators (Jake, Nov 13 2026): an Adzuna link can end on a JobLeads search page, which
# is a list of other jobs and never the posting. Landing on one of these means "look for the posting
# elsewhere, else closed". Hosts match by suffix ("jobleads.com" also catches "www.jobleads.com").
AGGREGATOR_HOSTS = ("jobleads.com", "adzuna.ca", "adzuna.com", "jooble.org", "jobrapido.com", "talent.com",
                    "neuvoo.ca", "careerjet.ca", "careerjet.com", "jobtome.com", "whatjobs.com", "bebee.com",
                    "learn4good.com", "jobsora.com", "recruit.net")


def aggregator_hosts(cfg: dict[str, Any]) -> tuple[str, ...]:
    extra = ((cfg.get("open_check") or {}).get("aggregator_hosts")) or ()
    return AGGREGATOR_HOSTS + tuple(str(h).lower() for h in extra)


def is_aggregator(url: str, cfg: dict[str, Any]) -> bool:
    from urllib.parse import urlparse

    host = (urlparse(url or "").hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in aggregator_hosts(cfg))


def posting_url(row: Any) -> str:
    """The link to open a job: the real employer/ATS page the open check found, else the scraped one."""
    try:
        real = row["real_url"]
    except (KeyError, IndexError):
        real = None
    return (real or row["url"] or "")


def open_check_dir(cfg: dict[str, Any]) -> Path:
    return resolve(cfg, "materials") / "tailor" / "open-check"


def write_plan(cfg: dict[str, Any], entries: list[tuple[Any, list, Any]], limit: int, checked: bool) -> Path:
    import json

    d = open_check_dir(cfg)
    d.mkdir(parents=True, exist_ok=True)
    for old in d.glob("*.json"):  # last run's plan and verdicts
        old.unlink()
    plan = {"date": date.today().isoformat(), "limit": limit, "checked": checked,
            "min_years": int((cfg.get("hard_stop") or {}).get("min_years", 7)), "entries": [
        {"job_id": r["id"], "company": r["company"], "title": r["title"], "url": posting_url(r),
         "flags": flags, "resume_base": base} for r, flags, base in entries]}
    path = d / "plan.json"
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return path


def read_verdicts(cfg: dict[str, Any]) -> dict[int, dict[str, Any]]:
    """The browser step's verdicts by job id. A file that isn't valid, or calls a job closed
    without quoting the page, counts as unknown."""
    import json

    out: dict[int, dict[str, Any]] = {}
    for f in open_check_dir(cfg).glob("*.json"):
        if f.name == "plan.json" or not f.stem.isdigit():
            continue
        try:
            v = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not isinstance(v, dict):
            continue
        state = v.get("state")
        if state in ("closed", "miss") and not str(v.get("evidence") or "").strip():
            state = "unknown"
        if state == "miss" and not str(v.get("why") or "").strip():
            state = "unknown"
        evidence = str(v.get("evidence") or "").strip()
        real_url = str(v.get("real_url") or "").strip()
        if not re.match(r"https?://", real_url, re.I) or is_aggregator(real_url, cfg):
            real_url = ""  # only a real employer/ATS page is worth saving
        landed = str(v.get("landed_url") or "").strip()
        if state != "miss" and not real_url and landed and is_aggregator(landed, cfg):
            # The link ended on a job-search aggregator and the posting wasn't found elsewhere: closed.
            host = re.sub(r"^https?://", "", landed, flags=re.I).split("/")[0]
            state = "closed"
            evidence = f"The link ended on {host}, a job-search site, and the posting was not found elsewhere. {evidence}".strip()
        out[int(f.stem)] = {"state": state if state in ("open", "closed", "miss") else "unknown",
                            "evidence": evidence, "why": str(v.get("why") or "").strip(),
                            "real_url": real_url if state == "open" else ""}
    return out


def queue_from_plan(cfg: dict[str, Any], limit: int | None = None) -> list[Path]:
    """Create the folders for the planned jobs, skipping the ones the browser found closed."""
    import json

    from src import db

    path = open_check_dir(cfg) / "plan.json"
    plan = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    if not plan or plan.get("date") != date.today().isoformat():
        raise TailorError("no queue plan from today: run `queue --plan` first")
    limit = limit if limit is not None else int(plan["limit"])
    verdicts = read_verdicts(cfg)
    conn = store.connect(resolve(cfg, "db"))
    try:
        taken = {r[0] for r in conn.execute("SELECT job_id FROM applications WHERE status != 'shortlisted'")}
        entries, closed = [], []
        for e in plan["entries"]:
            if len(entries) >= limit:
                break
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (e["job_id"],)).fetchone()
            if row is None or row["id"] in taken or row["status"] in ("dismissed", "applied"):
                continue
            v = verdicts.get(e["job_id"])
            if v and v["state"] in ("closed", "miss"):
                db.set_job_status(conn, e["job_id"], "dismissed")
                store.set_status(conn, e["job_id"], "dismissed")
                closed.append({"job_id": e["job_id"], "company": e["company"], "title": e["title"],
                               "kind": v["state"], "evidence": v["evidence"], "why": v["why"]})
                continue
            if v and v.get("real_url") and v["real_url"] != (row["real_url"] or ""):
                conn.execute("UPDATE jobs SET real_url = ? WHERE id = ?", (v["real_url"], row["id"]))
                conn.commit()
                row = conn.execute("SELECT * FROM jobs WHERE id = ?", (e["job_id"],)).fetchone()
            entries.append((row, e["flags"], e["resume_base"]))
        if closed:
            log = open_check_dir(cfg) / "dismissed.jsonl"
            with log.open("a", encoding="utf-8") as f:
                for c in closed:
                    f.write(json.dumps({"date": date.today().isoformat(), **c}) + "\n")
        return _make_folders(conn, cfg, entries, bool(plan.get("checked")))
    finally:
        conn.close()


def shortfall(cfg: dict[str, Any], limit: int | None = None) -> int:
    """How many more jobs today's run must draft to reach the daily cap: the cap minus the
    folders made today whose job wasn't dismissed since (a hard stop or an open check can
    dismiss one after its folder exists). The wrapper tops up with another open check and
    queue round until this is 0 (Jake, Nov 12 2026: every job gets both checks)."""
    limit = limit if limit is not None else int(cfg.get("daily_cap", 3))
    conn = store.connect(resolve(cfg, "db"))
    try:
        (kept,) = conn.execute(
            "SELECT COUNT(*) FROM applications a JOIN jobs j ON j.id = a.job_id "
            "WHERE a.created_at = ? AND j.status != 'dismissed' AND a.status != 'dismissed'",
            (date.today().isoformat(),)).fetchone()
    finally:
        conn.close()
    return max(0, limit - int(kept))


def _make_folders(conn, cfg: dict[str, Any], entries: list[tuple[Any, list, Any]], use_jev: bool) -> list[Path]:
    apps_root = resolve(cfg, "applications")
    today = date.today().isoformat()
    out: list[Path] = []
    for rank, (r, flags, gate_base) in enumerate(entries, 1):
        # The score and tier now, after the quick fit check took its points off.
        now = conn.execute("SELECT score, tier FROM jobs WHERE id = ?", (r["id"],)).fetchone() or r
        prior = conn.execute("SELECT folder FROM applications WHERE job_id = ? AND status = 'shortlisted'",
                             (r["id"],)).fetchone()
        folder = store.folder_path(prior[0]) if prior and prior[0] else None
        if folder is None or not folder.is_dir():
            folder = apps_root / appdir.folder_name(today, r["company"], r["title"])
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "posting.md").write_text(_posting_md(r), encoding="utf-8")
        appdir.save_app(folder, {
            "job_id": r["id"], "company": r["company"], "title": r["title"], "url": r["url"],
            "tier": now["tier"], "score": now["score"], "created": today, "status": "shortlisted",
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
