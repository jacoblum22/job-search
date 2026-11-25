"""What was true when an application was sent, and how it was sent.

A job's tier, score and level keep changing after you apply (rescoring, new rules), and nothing
recorded whether you applied on the company's own page or through a job board, or whether a
letter went with it. So callbacks could not be compared by segment afterwards. On the first
"I applied" the facts are frozen into app.json under `applied` and mirrored into the
`applications` table; how it was sent is added from the details page.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from src.tailor import TailorError, appdir, store

CHANNELS = ("company_site", "linkedin_easy_apply", "job_board", "email", "other")

# rescoring writes the level into score_reasons: "level: entry (...)" or "tier B at most: stretch level (...)"
_LEVEL = re.compile(r"\bat most: (\w+) level\b|\blevel: (\w+)")


def host(url: str | None) -> str | None:
    """'https://www.Boards.greenhouse.io/x?y' -> 'boards.greenhouse.io'; None when it is not a web link."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return parts.hostname.lower().removeprefix("www.")


def _level(score_reasons: Any) -> str | None:
    m = _LEVEL.search(str(score_reasons or ""))
    return (m[1] or m[2]) if m else None


def letter_in(app_dir: Path) -> bool:
    final = Path(app_dir) / "final"
    return final.is_dir() and any("cover letter" in p.name.lower() for p in final.iterdir())


def snapshot(conn: Any, job_id: int, app_dir: Path, *, drafted: dict[str, Any] | None = None) -> dict[str, Any]:
    """The job as it stands now. `drafted` (tier and score saved when the packet was drafted)
    replaces today's tier and score when filling in an application sent before this existed."""
    row = conn.execute(
        "SELECT source, tier, score, score_reasons, years_experience, location_category, url, real_url "
        "FROM jobs WHERE id = ?", (job_id,)).fetchone()
    source, tier, score, reasons, years, where, url, real_url = row if row else (None,) * 8
    if drafted:
        tier, score = drafted.get("tier") or tier, drafted.get("score") if drafted.get("score") is not None else score
    return {
        "source": source, "tier": tier, "score": score, "level": _level(reasons),
        "required_years": years, "location": where,
        "posting_host": host(url), "employer_host": host(real_url),
        "letter_sent": letter_in(app_dir),
    }


def columns(applied: dict[str, Any]) -> dict[str, Any]:
    """The `applications` columns that mirror app.json's `applied`."""
    sent = applied.get("letter_sent")
    return {
        "applied_source": applied.get("source"), "applied_tier": applied.get("tier"),
        "applied_score": applied.get("score"), "applied_level": applied.get("level"),
        "apply_channel": applied.get("channel"), "apply_host": applied.get("host"),
        "letter_sent": None if sent is None else int(bool(sent)),
    }


def record_how(app_dir: Path, cfg: dict[str, Any], *, channel: str | None = None, url: str | None = None,
               letter_sent: bool | None = None) -> dict[str, Any]:
    """Save how an application was sent: the channel, the page it went through, whether a letter
    went with it. Each is optional; what is not given stays as it was."""
    from src.tailor.packet import _sync

    app = appdir.load_app(app_dir)
    if not app.get("applied_at"):
        raise TailorError('press "I applied" first')
    applied = dict(app.get("applied") or {})
    if channel is not None:
        if channel not in CHANNELS:
            raise TailorError(f"channel must be one of {', '.join(CHANNELS)}")
        applied["channel"] = channel
    if url is not None and url.strip():
        h = host(url)
        if not h:
            raise TailorError("the link must start with http:// or https://")
        p = urlsplit(url.strip())
        # the page, not the visit: query strings on apply pages carry tracking and sign-in tokens
        applied["url"] = urlunsplit((p.scheme, p.netloc, p.path, "", ""))
        applied["host"] = h
    if letter_sent is not None:
        applied["letter_sent"] = bool(letter_sent)
    app = appdir.log(app_dir, "applied_how", applied.get("channel") or "", applied=applied)
    _sync(app_dir, cfg, app, app["status"], **columns(applied))
    return applied


def backfill(conn: Any) -> dict[str, int]:
    """Fill `applied` for applications sent before it was recorded, from what is still known: the
    tier and score saved when the packet was drafted, the job's level and source today, and
    whether final/ holds a letter. How it was sent is not known and stays empty."""
    rows = conn.execute(
        "SELECT job_id, folder, tier, score FROM applications "
        "WHERE applied_at IS NOT NULL AND applied_source IS NULL").fetchall()
    done = missing = 0
    for job_id, folder, tier, score in rows:
        app_dir = store.folder_path(folder)
        snap = {**snapshot(conn, job_id, app_dir, drafted={"tier": tier, "score": score}), "backfilled": True}
        if (app_dir / "app.json").exists():
            app = appdir.load_app(app_dir)
            snap = {**snap, **(app.get("applied") or {})}
            app["applied"] = snap
            appdir.save_app(app_dir, app)
        else:
            missing += 1
            snap["letter_sent"] = None  # no folder on this computer, so unknown
        store.set_fields(conn, job_id, **columns(snap))
        done += 1
    return {"filled": done, "folder_missing": missing}
