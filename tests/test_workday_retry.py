import asyncio

import httpx

import src.scraper as scraper
from src.scraper import AsyncWorkdayScraper


def test_listing_retries_dropped_connection_and_5xx(monkeypatch):
    monkeypatch.setattr(scraper, "RETRY_BACKOFF", 0)
    calls = []

    def handler(request):
        calls.append(request.method)
        if len(calls) == 1:
            raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
        if len(calls) == 2:
            return httpx.Response(503)
        return httpx.Response(200, json={"total": 0, "jobPostings": []})

    async def run():
        async with AsyncWorkdayScraper(tenant="t", site="s", source_name="T") as s:
            s._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            return await s.list_all_jobs()

    assert asyncio.run(run()) == []
    assert calls == ["POST", "POST", "POST"]


def test_gives_up_after_retries(monkeypatch):
    monkeypatch.setattr(scraper, "RETRY_BACKOFF", 0)

    def handler(request):
        raise httpx.RemoteProtocolError("Server disconnected")

    async def run():
        async with AsyncWorkdayScraper(tenant="t", site="s", source_name="T") as s:
            s._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            await s.list_all_jobs()

    try:
        asyncio.run(run())
    except httpx.RemoteProtocolError:
        pass
    else:
        raise AssertionError("expected the last error to propagate")
