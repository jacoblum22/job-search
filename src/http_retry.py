"""HTTP GET with retries for flaky job-board APIs (429/503/timeouts)."""

from __future__ import annotations

import logging
import time

import httpx

logger = logging.getLogger(__name__)

RETRY_STATUSES = frozenset({429, 502, 503, 504})


def request_with_retry(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    retries: int = 4,
    retry_statuses: frozenset[int] = RETRY_STATUSES,
    backoff: float = 1.5,
    **kwargs,
) -> httpx.Response:
    """Return the last response after retrying transient failures.

    Does not raise on 429/503 — the caller decides whether to stop pagination.
    Raises the last `httpx.RequestError` if every attempt is a network failure.
    Other HTTP statuses are returned as-is (caller may `raise_for_status`).
    """
    last_error: httpx.RequestError | None = None
    resp: httpx.Response | None = None
    attempts = max(1, retries)
    for attempt in range(attempts):
        try:
            resp = client.request(method, url, **kwargs)
        except httpx.RequestError as exc:
            last_error = exc
            wait = backoff * (attempt + 1)
            logger.warning(
                "%s %s network error (%s) — retry %d/%d in %.1fs",
                method,
                url.split("?")[0],
                type(exc).__name__,
                attempt + 1,
                attempts,
                wait,
            )
            time.sleep(wait)
            continue
        if resp.status_code in retry_statuses and attempt < attempts - 1:
            wait = backoff * (attempt + 1)
            logger.warning(
                "%s %s HTTP %s — retry %d/%d in %.1fs",
                method,
                url.split("?")[0],
                resp.status_code,
                attempt + 1,
                attempts,
                wait,
            )
            time.sleep(wait)
            continue
        return resp
    if resp is not None:
        return resp
    assert last_error is not None
    raise last_error
