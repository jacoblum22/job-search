"""A short AI-written fit verdict for every job that reached review (Jake, Nov 19 2026).

check.md already says what to fix; it doesn't say what to *think* of the job. This step gives each
reviewed application a few plain sentences from a Claude that has read the posting itself, the job's
score and why it got it, how the tailored resume fared, and what the outside reviewer said: whether
the score is about right, how much of a stretch the job is, and how good Jake should feel about it.
It is not a restatement of the score reasons.

Same shape as every Claude step: a code step writes `fit-verdict/input.md` (`build_input`), a
subagent follows `prompts/tailor/fit-verdict.md` and writes `fit-verdict/verdict.json`, and a code
step validates and saves it as `fit-verdict.json` in the application folder (`save`). The dashboard
details page and the table read that file (`load`). Only jobs that reached review get one, never the
other ~3,000: they cost no usage.

A verdict is kept until the posting or the review packet changes (`fingerprint`): ticking boxes in
check.md, or the daily score drifting with the posting's age, doesn't make it stale.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from src.tailor import TailorError, appdir

# Statuses that have been through the packet step and still wait on Jake.
REVIEWED = ("ready_for_review", "needs_fixes", "approved")
SCORE_CHECKS = ("about right", "too high", "too low")
STRETCHES = ("comfortable", "some stretch", "big stretch")
OUTLOOKS = ("good", "mixed", "poor")
MAX_TEXT = 900  # characters; the prompt asks for 2-4 sentences

_BOX = re.compile(r"\[[ xX]\]")


def fv_dir(app_dir: Path) -> Path:
    return Path(app_dir) / "fit-verdict"


def verdict_path(app_dir: Path) -> Path:
    return Path(app_dir) / "fit-verdict.json"


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def fingerprint(app_dir: Path) -> str:
    """Hash of what a verdict is about: the posting and the review packet with every box shown
    unticked (so ticking doesn't change it). The score isn't in it: it moves with the posting's age."""
    app_dir = Path(app_dir)
    h = hashlib.sha1()
    h.update(_read(app_dir / "posting.md").encode("utf-8"))
    h.update(_BOX.sub("[ ]", _read(app_dir / "check.md")).encode("utf-8"))
    try:
        h.update(str(appdir.load_app(app_dir).get("status")).encode("utf-8"))
    except (TailorError, OSError):
        pass
    return h.hexdigest()[:16]


def load(app_dir: Path) -> dict[str, Any] | None:
    """The saved verdict, or None when there isn't a readable one."""
    path = verdict_path(app_dir)
    if not path.exists():
        return None
    try:
        data = appdir.read_json(path)
    except TailorError:
        return None
    return data if isinstance(data, dict) and data.get("text") else None


def is_current(app_dir: Path) -> bool:
    saved = load(app_dir)
    return bool(saved) and saved.get("fingerprint") == fingerprint(app_dir)


def needs_verdict(app_dir: Path) -> bool:
    """Reviewed (packet has run, not applied or dismissed) and no verdict for what is there now."""
    app_dir = Path(app_dir)
    try:
        app = appdir.load_app(app_dir)
    except (TailorError, OSError):
        return False
    if app.get("status") not in REVIEWED or not (app_dir / "check.md").exists():
        return False
    return not is_current(app_dir)


def _job_row(app: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """The job's score, tier and reasons from jobs.db; empty if the database can't be read."""
    try:
        from src.db import connect
        from src.tailor.paths import resolve

        conn = connect(resolve(cfg, "db"))
        try:
            row = conn.execute("SELECT score, tier, score_reasons, years_experience FROM jobs WHERE id = ?",
                               (app["job_id"],)).fetchone()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 - the verdict is still worth writing from app.json's score
        return {}
    return {"score": row[0], "tier": row[1], "score_reasons": row[2], "years": row[3]} if row else {}


def build_input(app_dir: Path, cfg: dict[str, Any]) -> dict[str, Any]:
    """Write `fit-verdict/input.md` for the Claude step and say where the answer goes."""
    app_dir = Path(app_dir)
    app = appdir.load_app(app_dir)
    job = _job_row(app, cfg)
    score = job.get("score") if job.get("score") is not None else app.get("score")
    tier = job.get("tier") or app.get("tier")
    parts = [
        f"# {app.get('title', '')} at {app.get('company', '')}",
        "",
        f"Score {score} (tier {tier}; tiers: A 60+, B 40-59, C 20-39, D under 20). "
        f"Status: {app.get('status')}.",
        "",
        "## Why the job scored what it did (the score's own reasons)",
        "",
        job.get("score_reasons") or "(none recorded)",
        "",
        "## The review packet (check.md: fit summary, ATS result, flags, outside reviewer's verdict)",
        "",
        _BOX.sub("[ ]", _read(app_dir / "check.md")).strip() or "(missing)",
        "",
        "## Requirement-by-requirement evidence (fit-notes.md)",
        "",
        _read(app_dir / "fit-notes.md").strip() or "(missing)",
        "",
        "## The posting",
        "",
        _read(app_dir / "posting.md").strip() or "(missing)",
        "",
    ]
    out = fv_dir(app_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "input.md").write_text("\n".join(parts), encoding="utf-8")
    return {"input": str(out / "input.md"), "output": str(out / "verdict.json"),
            "prompt": "prompts/tailor/fit-verdict.md"}


def _choice(data: dict[str, Any], key: str, allowed: tuple[str, ...]) -> str:
    value = str(data.get(key) or "").strip().lower()
    if value not in allowed:
        raise TailorError(f"fit-verdict.json: {key} must be one of {', '.join(allowed)} (got {value!r})")
    return value


def save(app_dir: Path) -> dict[str, Any]:
    """Validate Claude's `fit-verdict/verdict.json` and keep it as `fit-verdict.json`."""
    app_dir = Path(app_dir)
    data = appdir.read_json(fv_dir(app_dir) / "verdict.json")
    if not isinstance(data, dict):
        raise TailorError("fit-verdict/verdict.json must be a JSON object")
    text = re.sub(r"\s+", " ", str(data.get("text") or "")).strip()
    if len(text) < 40:
        raise TailorError("fit-verdict.json: text is missing or too short (2-4 sentences)")
    if len(text) > MAX_TEXT:
        raise TailorError(f"fit-verdict.json: text is {len(text)} characters; keep it to 2-4 sentences "
                          f"(at most {MAX_TEXT})")
    saved = {
        "score_check": _choice(data, "score_check", SCORE_CHECKS),
        "stretch": _choice(data, "stretch", STRETCHES),
        "outlook": _choice(data, "outlook", OUTLOOKS),
        "text": text,
        "fingerprint": fingerprint(app_dir),
        "at": appdir.now(),
    }
    appdir.write_json(verdict_path(app_dir), saved)
    appdir.log(app_dir, "fit-verdict", f"{saved['outlook']}, {saved['stretch']}, score {saved['score_check']}")
    return {"saved": str(verdict_path(app_dir)), **{k: saved[k] for k in ("score_check", "stretch", "outlook")}}


def pending(folders: list[Path], limit: int | None = None) -> list[str]:
    """Folders (newest first) that need a verdict, at most `limit`."""
    todo = [f for f in folders if needs_verdict(f)]
    todo.sort(key=lambda f: f.name, reverse=True)
    return [str(f) for f in (todo[:limit] if limit else todo)]
