"""The daily application goal: how many jobs were marked "I applied" today, in Jake's own day."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

DEFAULT_GOAL = 10
DEFAULT_TZ = "America/Vancouver"


def settings(cfg: dict[str, Any]) -> tuple[int, ZoneInfo]:
    goal = cfg.get("goal") or {}
    n = int(goal.get("daily_applications") or DEFAULT_GOAL)
    return max(n, 1), ZoneInfo(goal.get("timezone") or DEFAULT_TZ)


def applied_today(conn: sqlite3.Connection, cfg: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    """{done, goal, date}: applications whose first "I applied" fell on today's local date.

    applied_at is set once, when the job is first marked applied; older rows that predate the column
    fall back to outcome_at while their outcome is still 'applied'."""
    from src.tailor import store

    goal, tz = settings(cfg)
    today = (now or datetime.now(timezone.utc)).astimezone(tz).date()
    done = 0
    if store.has_table(conn):
        rows = conn.execute(
            "SELECT applied_at, outcome, outcome_at FROM applications "
            "WHERE applied_at IS NOT NULL OR outcome = 'applied'"
        ).fetchall()
        for applied_at, outcome, outcome_at in rows:
            stamp = applied_at or (outcome_at if outcome == "applied" else None)
            if not stamp:
                continue
            when = datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            done += when.astimezone(tz).date() == today
    return {"done": done, "goal": goal, "date": today.isoformat()}
