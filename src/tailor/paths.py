"""Config and path resolution for the tailoring pipeline."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
SETTINGS = ROOT / "config" / "settings.yaml"

DEFAULT_PATHS = {
    "materials": "materials",
    "applications": "materials/applications",
    "companies": "materials/companies",
    "bases": "materials/resumes/bases",
    "vault_index": "materials/profile/vault-index.json",
    "rules": "materials/docs/tailoring-rules.md",
    "db": "jobs.db",
    "unknown_terms": "materials/tailor/unknown-terms.csv",
}


@lru_cache(maxsize=1)
def _settings() -> dict[str, Any]:
    if not SETTINGS.exists():
        return {}
    return yaml.safe_load(SETTINGS.read_text(encoding="utf-8")) or {}


def load_config(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """The `tailor:` section of settings.yaml, with defaults filled in.

    `overrides` is merged on top (tests pass paths into a tmp dir this way).
    """
    cfg = dict(_settings().get("tailor") or {})
    paths = dict(DEFAULT_PATHS)
    paths.update(cfg.get("paths") or {})
    if overrides:
        paths.update(overrides.get("paths") or {})
        cfg.update({k: v for k, v in overrides.items() if k != "paths"})
    cfg["paths"] = paths
    return cfg


def resolve(cfg: dict[str, Any], name: str) -> Path:
    """Absolute path for a named location (relative paths are under the repo root)."""
    p = Path(cfg["paths"][name])
    return p if p.is_absolute() else ROOT / p
