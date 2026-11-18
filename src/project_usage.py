"""Which projects the tailored resumes feature most often (the Stats tab's "Projects on your resumes")."""

from __future__ import annotations

import sqlite3
from collections import Counter
from typing import Any

from src.tailor import appdir, packet, store


def _project_names(resume: dict[str, Any]) -> dict[str, str]:
    """Project id -> name for each project on `resume` that has at least one bullet."""
    out: dict[str, str] = {}
    for p in resume.get("projects") or []:
        if not isinstance(p, dict) or not p.get("bullets"):
            continue
        name = str(p.get("name") or p.get("id") or "").strip()
        if name:
            out[str(p.get("id") or name)] = name
    return out


def project_usage(conn: sqlite3.Connection) -> dict[str, Any]:
    """How many tailored resumes carry each project, and how many of those were applied with.

    Each application counts once, using the resume that was rendered (the humanized copy if there is
    one, else the best round's). Applications with no resume yet are left out."""
    featured: Counter[str] = Counter()
    applied: Counter[str] = Counter()
    names: dict[str, str] = {}
    resumes = applied_resumes = 0
    for row in store.all_apps(conn).values():
        folder = store.folder_path(row.get("folder"))
        if not row.get("folder") or not folder.is_dir():
            continue
        try:
            app = appdir.load_app(folder)
        except Exception:  # noqa: BLE001 - a broken app.json just leaves that application out
            continue
        rnd = packet._best_round(folder, app)
        rd = appdir.round_dir(folder, rnd) if rnd else None
        _, resume = packet._final_resume(rd, folder)
        if not resume:
            continue
        projects = _project_names(resume)
        resumes += 1
        did_apply = row.get("status") == "applied"
        applied_resumes += did_apply
        for pid, name in projects.items():
            names.setdefault(pid, name)
            featured[pid] += 1
            if did_apply:
                applied[pid] += 1
    rows = [{"id": pid, "name": names[pid], "resumes": n, "applied": applied[pid],
             "percent": round(100 * n / resumes) if resumes else 0}
            for pid, n in sorted(featured.items(), key=lambda kv: (-kv[1], names[kv[0]].lower()))]
    return {"resumes": resumes, "applied_resumes": applied_resumes, "projects": rows}
