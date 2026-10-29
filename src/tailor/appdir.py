"""Reading and writing the files of one application folder."""

from __future__ import annotations

import json
import os
import re
import threading
import time
from contextlib import contextmanager
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
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Windows refuses the replace while another process has the file open for a read; that
    # read is over in a moment, so try again briefly.
    for attempt in range(20):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt == 19:
                raise
            time.sleep(0.1)


# Files every application shares (the skill record, the Jev cache) are read, changed and written
# back whole. Tailoring sessions running side by side (run_tailoring.ps1 -Parallel) take this
# lock around each read-change-write so one never overwrites what another just added.
_held: dict[str, int] = {}
_held_guard = threading.Lock()
LOCK_TIMEOUT = 120.0   # seconds to wait for another process
LOCK_STALE = 300.0     # a lock file this old was left by a process that died


@contextmanager
def file_lock(path: Path, timeout: float = LOCK_TIMEOUT):
    """Hold `<path>.lock` across processes. Re-entrant within one process, so a locked function
    may call another. Raises TailorError if the lock can't be had within `timeout` seconds."""
    lock = Path(str(path) + ".lock")
    key = str(lock.resolve())
    with _held_guard:
        if _held.get(key):
            _held[key] += 1
            mine = False
        else:
            mine = True
    if not mine:
        try:
            yield
        finally:
            with _held_guard:
                _held[key] -= 1
        return
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - lock.stat().st_mtime > LOCK_STALE:
                    lock.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            if time.monotonic() > deadline:
                raise TailorError(f"{path.name} is locked by another tailoring session ({lock})")
            time.sleep(0.05)
        except PermissionError:  # Windows: the lock file is being deleted right now
            time.sleep(0.05)
    with _held_guard:
        _held[key] = 1
    try:
        yield
    finally:
        with _held_guard:
            _held.pop(key, None)
        try:
            lock.unlink()
        except OSError:
            pass


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
