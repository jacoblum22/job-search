import httpx

from src.sources.careerjet import _search


class _Forbidden:
    def request(self, method, url, **kwargs):
        req = httpx.Request(method, url)
        return httpx.Response(403, request=req)


def test_careerjet_403_returns_empty_not_raise(monkeypatch):
    monkeypatch.setattr("src.http_retry.time.sleep", lambda _s: None)
    jobs, status = _search(
        _Forbidden(),
        "public affairs intern",
        "Vancouver, BC",
        "en_CA",
        "1.1.1.1",
        {"Referer": "https://example.com", "User-Agent": "x"},
        "affid",
    )
    assert jobs == []
    assert status == 403


def test_careerjet_paginates(monkeypatch):
    monkeypatch.setattr("src.http_retry.time.sleep", lambda _s: None)
    monkeypatch.setattr("src.sources.careerjet.time.sleep", lambda _s: None)
    pages_seen: list[int] = []

    class Client:
        def request(self, method, url, **kwargs):
            params = kwargs.get("params") or {}
            page = int(params.get("page", 1))
            pages_seen.append(page)
            req = httpx.Request(method, url)
            jobs = [
                {
                    "url": f"https://example.com/{page}",
                    "title": f"HR Intern {page}",
                    "company": "Co",
                    "locations": "Vancouver",
                    "description": "hi",
                    "date": None,
                }
            ]
            return httpx.Response(
                200,
                request=req,
                json={"type": "JOBS", "pages": 2, "jobs": jobs},
            )

    jobs, status = _search(
        Client(),
        "hr intern",
        "Vancouver, BC",
        "en_CA",
        "1.1.1.1",
        {"Referer": "https://example.com"},
        "affid",
        max_pages=3,
        request_pause=0,
    )
    assert status == 200
def test_careerjet_circuit_stops_after_three_403s(monkeypatch):
    monkeypatch.setattr("src.sources.careerjet._public_ip", lambda _c: "1.1.1.1")
    monkeypatch.setattr("src.http_retry.time.sleep", lambda _s: None)
    monkeypatch.setattr("src.sources.careerjet.time.sleep", lambda _s: None)
    calls = {"n": 0}

    class Client:
        def request(self, method, url, **kwargs):
            calls["n"] += 1
            req = httpx.Request(method, url)
            return httpx.Response(403, request=req)

    from src.sources.careerjet import fetch_careerjet_jobs

    jobs = fetch_careerjet_jobs(
        keywords=["a", "b", "c", "d", "e"],
        location="Vancouver, BC",
        referer="https://example.com",
        client=Client(),
        remote_sweep_location=None,
        request_pause=0,
        affid="test-affid",
    )
    assert jobs == []
    assert calls["n"] == 3
