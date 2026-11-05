"""Scoring files that live in materials/ but are needed wherever the scrape runs (Azure
plan, phase 5; docs/azure-scrape-job.md).

The score (src/score.py) counts tools a posting asks for that Jake's experience vault
doesn't show, from materials/profile/vault-index.json and materials/tailor/skill-record.json.
Both are personal, git-ignored and never baked into the public image, so the desktop
copies them into a `score_inputs` table in the (private) Postgres database and the Azure
scrape job writes them back out before it scores. Without them the job would score every
posting from the fallback gap list and rewrite every tier in the shared database.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS score_inputs (
    name TEXT PRIMARY KEY,
    body TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def names(score_cfg: dict | None) -> list[str]:
    """The files scoring reads, as written in settings.yaml (score.vault_gaps), index first."""
    vault_cfg = (score_cfg or {}).get("vault_gaps") or {}
    if not vault_cfg:
        return []
    return [vault_cfg.get("index", "materials/profile/vault-index.json"),
            vault_cfg.get("record", "materials/tailor/skill-record.json")]


def _path(name: str, root: Path) -> Path:
    p = Path(name)
    return p if p.is_absolute() else root / p


def _sha(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def ready(score_cfg: dict | None, root: Path = ROOT) -> bool:
    """True when scoring has what it needs: no vault configured, or the vault index is here."""
    files = names(score_cfg)
    return not files or _path(files[0], root).exists()


def _stored(conn: Any) -> dict[str, tuple[str, str]]:
    conn.executescript(SCHEMA)
    return {r[0]: (r[1], r[2]) for r in conn.execute("SELECT name, body, sha256 FROM score_inputs")}


def push(conn: Any, score_cfg: dict | None, root: Path = ROOT) -> list[str]:
    """Copy the local scoring files into the database; returns the ones that changed."""
    stored = _stored(conn)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    changed = []
    for name in names(score_cfg):
        path = _path(name, root)
        if not path.exists():
            continue
        body = path.read_text(encoding="utf-8")
        sha = _sha(body)
        if stored.get(name, (None, None))[1] == sha:
            continue
        conn.execute(
            "INSERT INTO score_inputs (name, body, sha256, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET body = excluded.body, sha256 = excluded.sha256, "
            "updated_at = excluded.updated_at",
            (name, body, sha, now))
        changed.append(name)
    conn.commit()
    return changed


def pull(conn: Any, score_cfg: dict | None, root: Path = ROOT) -> list[str]:
    """Write the database's copies of the scoring files to disk; returns the ones written."""
    stored = _stored(conn)
    written = []
    for name in names(score_cfg):
        if name not in stored:
            continue
        body, sha = stored[name]
        path = _path(name, root)
        if path.exists() and _sha(path.read_text(encoding="utf-8")) == sha:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        written.append(name)
    return written


def sync(conn: Any, score_cfg: dict | None, root: Path = ROOT) -> tuple[str, list[str]]:
    """Where the vault index is on disk (the desktop) push it; where it isn't (the Azure
    job), pull it. Returns ("push" | "pull", files changed)."""
    if ready(score_cfg, root) and names(score_cfg):
        return "push", push(conn, score_cfg, root)
    return "pull", pull(conn, score_cfg, root)
