"""Reading and writing the files of one application folder."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.tailor import TailorError

_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def folder_name(created: str, company: str, title: str) -> str:
    """`2026-10-18 Acme - Data Analyst`, filesystem-safe and at most 120 chars."""
    name = f"{created} {company} - {title}"
    name = _UNSAFE.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:120].rstrip(" .")


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path: Path) -> Any:
    if not path.exists():
        raise TailorError(f"{path.name} is missing in {path.parent}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise TailorError(f"{path} is not valid JSON: {e}") from e


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def round_dir(app_dir: Path, rnd: int) -> Path:
    return app_dir / "drafts" / f"r{rnd}"


def load_app(app_dir: Path) -> dict[str, Any]:
    return read_json(app_dir / "app.json")


def save_app(app_dir: Path, app: dict[str, Any]) -> None:
    write_json(app_dir / "app.json", app)


def humanized(app_dir: Path, name: str) -> Path | None:
    """The humanize pass's copy of `name` (resume.yaml or cover-letter.json) when it was made from
    the current best round. A later round that becomes the best makes the old copy stale: rendering
    it would ship the earlier draft. Copies from before the pass recorded its round count as current."""
    path = app_dir / "humanize" / name
    if not path.exists():
        return None
    marker = app_dir / "humanize" / "round.json"
    if marker.exists():
        best = load_app(app_dir).get("best_round")
        if best and int(read_json(marker).get("round") or 0) != int(best):
            return None
    return path


def log(app_dir: Path, step: str, note: str = "", **fields: Any) -> dict[str, Any]:
    """Append to app.json history (and set any top-level fields); returns the updated app."""
    app = load_app(app_dir)
    app.update(fields)
    app.setdefault("history", []).append({"at": now(), "step": step, "note": note})
    save_app(app_dir, app)
    return app
