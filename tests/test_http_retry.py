import httpx

from src.http_retry import request_with_retry


def test_retries_503_then_ok(monkeypatch):
    monkeypatch.setattr("src.http_retry.time.sleep", lambda _s: None)
    hits = {"n": 0}

    class Client:
        def request(self, method, url, **kwargs):
            hits["n"] += 1
            req = httpx.Request(method, url)
            if hits["n"] < 3:
                return httpx.Response(503, request=req)
            return httpx.Response(200, request=req, text="ok")

    resp = request_with_retry(Client(), "GET", "https://example.com/x")
    assert resp.status_code == 200
    assert hits["n"] == 3


def test_network_error_exhausted(monkeypatch):
    monkeypatch.setattr("src.http_retry.time.sleep", lambda _s: None)

    class Client:
        def request(self, method, url, **kwargs):
            raise httpx.ConnectError("nope", request=httpx.Request(method, url))

    try:
        request_with_retry(Client(), "GET", "https://example.com/x", retries=2)
        raise AssertionError("expected ConnectError")
    except httpx.ConnectError:
        pass
