"""Shared loaders: the vault index and the base resumes.

Several steps read the same two inputs, so they live here once. Passages are
keyed by id; a base's bullets are addressed by the paths the edit gates use.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.resume import iter_bullets, load_resume
from src.tailor import TailorError
from src.tailor.paths import resolve


def load_index(cfg: dict[str, Any]) -> dict[str, dict]:
    """Vault passages by id (accepts `{"passages": [...]}` or a bare list)."""
    path = resolve(cfg, "vault_index")
    if not path.exists():
        raise TailorError(f"vault index not found at {path}; build it with the vault index command")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise TailorError(f"{path} is not valid JSON: {e}") from e
    passages = data.get("passages") if isinstance(data, dict) else data
    if not isinstance(passages, list):
        raise TailorError(f"{path}: expected a list of passages")
    return {p["id"]: p for p in passages if isinstance(p, dict) and "id" in p}


def claim_passages(index: dict[str, dict]) -> dict[str, dict]:
    """Only passages that may be claimed on a resume (`use == "claim"`)."""
    return {i: p for i, p in index.items() if p.get("use") == "claim"}


def load_bases(cfg: dict[str, Any]) -> dict[str, dict]:
    """Every base resume in the bases dir, keyed by its `id` (file stem if missing)."""
    folder = resolve(cfg, "bases")
    files = sorted([*folder.glob("*.yaml"), *folder.glob("*.yml")]) if folder.is_dir() else []
    if not files:
        raise TailorError(f"no base resumes (*.yaml) in {folder}")
    bases: dict[str, dict] = {}
    for f in files:
        try:
            data = load_resume(Path(f))
        except Exception as e:  # yaml errors and non-mapping files
            raise TailorError(f"cannot read base {f.name}: {e}") from e
        data.setdefault("id", f.stem)
        bases[data["id"]] = data
    return bases


def _skill_text(group: dict) -> str:
    items = ", ".join(str(i) for i in group.get("items") or [])
    return f"{group.get('label', '')}: {items}".strip(": ")


def bullet_paths(base: dict) -> dict[str, str]:
    """`{path: text}` for the summary, every skills group and every bullet."""
    out: dict[str, str] = {}
    summary = base.get("summary")
    if isinstance(summary, dict) and summary.get("text"):
        out["summary"] = str(summary["text"]).strip()
    for group in base.get("skills") or []:
        out[f"skills/{group.get('id')}"] = _skill_text(group)
    for path, bullet in iter_bullets(base):
        out[path] = str(bullet.get("text", "")).strip()
    return out


def base_text(base: dict) -> str:
    """All of a base's wording as one string, for "does this base mention X"."""
    parts = list(bullet_paths(base).values())
    for section in ("experience", "projects"):
        for e in base.get(section) or []:
            parts += [str(e.get(k, "")) for k in ("title", "company", "name", "context")]
    for e in base.get("education") or []:
        parts.append(str(e.get("degree", "")))
        parts += [str(line.get("text", "")) for line in e.get("lines") or []]
    return "\n".join(p for p in parts if p)
