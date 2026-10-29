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


def test_jev_batches_sent_at_once_keep_their_answers():
    import time

    import httpx

    from src.tailor.jev import JevClient, Question

    def handler(request):
        body = json.loads(request.content)
        keys = list(body["questions"])
        if "q0" in keys:
            time.sleep(0.2)  # the first batch answers last
        return httpx.Response(200, json={"answers": {
            k: {"type": "boolean", "probability": int(k[1:]) / 100} for k in keys}})

    qs = [Question(f"q{i}", "yesno", "x" * 400) for i in range(10)]
    c = JevClient("k", {"max_request_tokens": 1000}, transport=httpx.MockTransport(handler))
    out = c.ask("short state", qs)
    assert [a.id for a in out] == [q.id for q in qs]
    assert [a.value for a in out] == [i / 100 for i in range(10)]
    assert c.usage.requests > 1


def test_remembered_jev_keeps_answers_asked_from_threads(tmp_path):
    from src.concurrency import parallel_map
    from src.tailor.jev import FakeJev, Question, RememberedJev

    jev = RememberedJev(FakeJev(lambda state, q: 0.7), tmp_path / "jev-answers.json")
    qs = [Question(f"q{i}", "yesno", f"line {i}?") for i in range(20)]
    parallel_map(lambda q: jev.ask("state", [q]), qs, 8)
    assert len(json.loads((tmp_path / "jev-answers.json").read_text(encoding="utf-8"))) == 20
