import threading
import time

import httpx

from src.concurrency import RateLimiter, parallel_map
from src.db import Job
from src.enrich import _interleave_hosts
from src.sources.ats_common import fetch_boards


def test_parallel_map_keeps_order_and_overlaps():
    started = time.monotonic()
    out = parallel_map(lambda x: (time.sleep(0.1), x * 2)[1], range(8), workers=8)
    assert out == [0, 2, 4, 6, 8, 10, 12, 14]
    assert time.monotonic() - started < 0.5


def test_rate_limiter_spaces_starts_per_key():
    limiter = RateLimiter(0.05)
    starts: list[float] = []
    lock = threading.Lock()

    def hit(_):
        limiter.wait("same-host")
        with lock:
            starts.append(time.monotonic())

    parallel_map(hit, range(5), workers=5)
    starts.sort()
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    assert min(gaps) >= 0.04


def test_rate_limiter_does_not_hold_other_hosts():
    limiter = RateLimiter(1.0)
    limiter.wait("a")
    started = time.monotonic()
    limiter.wait("b")
    assert time.monotonic() - started < 0.1


def test_fetch_boards_runs_boards_side_by_side_in_list_order():
    def fetch_one(client, board):
        time.sleep(0.1 if board["slug"] == "slow" else 0)
        if board["slug"] == "bad":
            raise RuntimeError("boom")
        return [board["slug"]]

    client = httpx.Client()
    started = time.monotonic()
    out = fetch_boards("Test", ["slow", "bad", "a", "b"], fetch_one, client=client, workers=4)
    assert out == ["slow", "a", "b"]
    assert time.monotonic() - started < 0.3


def test_interleave_hosts_round_robins():
    jobs = [Job("s", str(i), "t", "c", "l", "", f"https://{h}/{i}") for i, h in enumerate("aaab")]
    assert [j.url for j in _interleave_hosts(jobs)] == ["https://a/0", "https://b/3", "https://a/1", "https://a/2"]
