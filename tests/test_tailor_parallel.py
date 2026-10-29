"""Shared files stay whole when tailoring sessions run side by side (run_tailoring.ps1 -Parallel)."""

import json
import multiprocessing as mp
from pathlib import Path

import pytest

from src.tailor import TailorError, appdir, rejects


def _cfg(tmp_path: Path) -> dict:
    return {"paths": {"skill_record": str(tmp_path / "skill-record.json"),
                      "jev_cache": str(tmp_path / "jev-cache.json")}}


def test_file_lock_is_reentrant_and_cleans_up(tmp_path):
    target = tmp_path / "x.json"
    with appdir.file_lock(target):
        with appdir.file_lock(target):
            assert Path(str(target) + ".lock").exists()
        assert Path(str(target) + ".lock").exists()
    assert not Path(str(target) + ".lock").exists()


def test_file_lock_times_out_on_a_held_lock(tmp_path):
    target = tmp_path / "x.json"
    Path(str(target) + ".lock").write_text("123")
    with pytest.raises(TailorError, match="locked"):
        with appdir.file_lock(target, timeout=0.2):
            pass


def test_file_lock_breaks_a_stale_lock(tmp_path, monkeypatch):
    target = tmp_path / "x.json"
    Path(str(target) + ".lock").write_text("123")
    monkeypatch.setattr(appdir, "LOCK_STALE", -1.0)
    with appdir.file_lock(target, timeout=1):
        pass


def test_jev_cache_keeps_answers_another_session_saved(tmp_path):
    cfg = _cfg(tmp_path)
    a, b = rejects.JevCache(cfg), rejects.JevCache(cfg)   # both load the empty cache
    a.put("q1", "t1", 0.9)
    b.put("q2", "t2", 0.2)
    a.save()
    b.save()
    fresh = rejects.JevCache(cfg)
    assert fresh.get("q1", "t1") == 0.9 and fresh.get("q2", "t2") == 0.2
    assert b.get("q1", "t1") == 0.9   # b now sees a's answer too
    assert not a.dirty and not b.dirty


def _add_many(cfg: dict, worker: int, n: int) -> None:
    for i in range(n):
        rejects.add_confirms(cfg, [{"term": f"skill {worker}-{i}", "passage": f"p.{worker}.{i}",
                                    "source": "plan"}])


def test_parallel_processes_lose_no_confirms(tmp_path):
    cfg = _cfg(tmp_path)
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_add_many, args=(cfg, w, 15)) for w in range(3)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    data = json.loads((tmp_path / "skill-record.json").read_text(encoding="utf-8"))
    assert len(data["has"]) == 45
    assert not list(tmp_path.glob("*.lock")) and not list(tmp_path.glob("*.tmp"))
