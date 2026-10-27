"""Start a tailoring run from the dashboard: scripts/run_tailoring.ps1 -Limit N, the same
run the 9:00 "JobSearch-Tailoring" task does, on this PC in the background.

The server remembers only the run it started, so a restart forgets it. The scheduled
task counts as a run too, so the button never starts a second run beside it.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from src.tailor import TailorError

ROOT = Path(__file__).resolve().parent.parent
MAX_JOBS = 10
TASK_NAME = "JobSearch-Tailoring"
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _launch(root: Path, limit: int) -> subprocess.Popen:
    if os.name != "nt":
        raise TailorError("tailoring runs only on the Windows PC")
    cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass",
           "-File", str(root / "scripts" / "run_tailoring.ps1"), "-Limit", str(limit)]
    return subprocess.Popen(cmd, cwd=root, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            creationflags=_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP)


def _task_running() -> bool:
    """Is the scheduled tailoring task running right now?"""
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, timeout=10, check=False,
                             creationflags=_NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return '"Running"' in out


class TailoringRunner:
    def __init__(self, root: Path = ROOT, launch: Callable[[Path, int], Any] = _launch,
                 task_running: Callable[[], bool] = _task_running) -> None:
        self.root = Path(root)
        self._launch = launch
        self._task_running = task_running
        self._proc: Any = None
        self._started: str | None = None
        self._limit: int | None = None

    def _last_log_line(self) -> str:
        log = self.root / "logs" / "tailoring.log"
        try:
            with log.open("rb") as f:
                f.seek(max(0, log.stat().st_size - 4096))
                tail = f.read().decode("utf-8", errors="replace")
        except OSError:
            return ""
        lines = [line.strip() for line in tail.splitlines() if line.strip()]
        return lines[-1] if lines else ""

    def status(self) -> dict[str, Any]:
        ours = self._proc is not None and self._proc.poll() is None
        by = "dashboard" if ours else "scheduled task" if self._task_running() else None
        return {"running": by is not None, "by": by,
                "started": self._started if ours else None, "limit": self._limit if ours else None,
                "max": MAX_JOBS, "last_log": self._last_log_line()}

    def start(self, limit: Any) -> dict[str, Any]:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            raise TailorError("send limit, a number of jobs") from None
        if not 1 <= limit <= MAX_JOBS:
            raise TailorError(f"limit must be 1 to {MAX_JOBS}")
        if self.status()["running"]:
            raise TailorError("a tailoring run is already going")
        self._proc = self._launch(self.root, limit)
        self._started = datetime.now().astimezone().isoformat(timespec="seconds")
        self._limit = limit
        return self.status()
