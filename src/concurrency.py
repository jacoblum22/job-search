"""Small helpers for running HTTP work in parallel without hammering one site.

Network calls dominate a scrape, so threads are enough (httpx.Client is
thread-safe). Anything that touches jobs.db stays on the main thread.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar
from urllib.parse import urlparse

T = TypeVar("T")
R = TypeVar("R")


class RateLimiter:
    """Spaces request *starts* at least `interval` seconds apart per key.

    Requests may still overlap (a slow response doesn't hold up the next
    start), but a site never sees more than one new request per interval
    from this run.
    """

    def __init__(self, interval: float):
        self.interval = max(0.0, interval)
        self._lock = threading.Lock()
        self._next: dict[str, float] = {}

    def wait(self, key: str = "") -> None:
        if self.interval <= 0:
            return
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next.get(key, now))
            self._next[key] = start + self.interval
        delay = start - now
        if delay > 0:
            time.sleep(delay)


def host_of(url: str) -> str:
    return urlparse(url or "").netloc.lower()


def parallel_map(fn: Callable[[T], R], items: Iterable[T], workers: int) -> list[R]:
    """`[fn(x) for x in items]`, run on up to `workers` threads, results in input order.

    `fn` must handle its own errors; an exception here propagates.
    """
    items = list(items)
    if workers <= 1 or len(items) <= 1:
        return [fn(x) for x in items]
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        return list(pool.map(fn, items))
