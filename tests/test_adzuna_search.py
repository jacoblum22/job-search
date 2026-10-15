from src.sources.adzuna import _search, _to_job


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _Status:
    def __init__(self, code):
        self.status_code = code

    def raise_for_status(self):
        raise AssertionError("should not raise")

    def json(self):
        raise AssertionError("no json")


class _Client:
    def __init__(self):
        self.pages: list[int] = []

    def request(self, method, url, **kwargs):
        return self.get(url, params=kwargs.get("params"))

    def get(self, url, params=None):
        page = int(url.rstrip("/").rsplit("/", 1)[-1])
        self.pages.append(page)
        if page == 1:
            results = [
                {
                    "id": i,
                    "title": f"Job {i}",
                    "company": {"display_name": "Co"},
                    "location": {"display_name": "Vancouver"},
                    "description": "x",
                    "redirect_url": "https://example.com",
                    "created": None,
                }
                for i in range(2)
            ]
            return _Resp({"results": results, "count": 3})
        return _Resp(
            {
                "results": [
                    {
                        "id": 99,
                        "title": "Job 99",
                        "company": {"display_name": "Co"},
                        "location": {"display_name": "Vancouver"},
                        "description": "x",
                        "redirect_url": "https://example.com",
                        "created": None,
                    }
                ],
                "count": 3,
            }
        )


def test_adzuna_paginates_until_short_page(monkeypatch):
    monkeypatch.setattr("src.http_retry.time.sleep", lambda _s: None)
    client = _Client()
    jobs = _search(client, "ba intern", "Vancouver, BC", "ca", 2, 5, "id", "key")
    assert client.pages == [1, 2]
    assert len(jobs) == 3
    assert {j.external_id for j in jobs} == {"0", "1", "99"}


def test_adzuna_503_keeps_prior_pages(monkeypatch):
    monkeypatch.setattr("src.http_retry.time.sleep", lambda _s: None)
    monkeypatch.setattr("src.sources.adzuna.time.sleep", lambda _s: None)

    class Client:
        def request(self, method, url, **kwargs):
            if url.endswith("/search/1"):
                return _Resp(
                    {
                        "results": [
                            {
                                "id": 7,
                                "title": "A",
                                "company": {"display_name": "Co"},
                                "location": {"display_name": "Vancouver"},
                                "description": "x",
                                "redirect_url": "https://example.com",
                                "created": None,
                            }
                        ]
                        * 2,
                        "count": 100,
                    }
                )
            return _Status(503)

    jobs = _search(Client(), "events", "Canada", "ca", 2, 3, "id", "key")
    assert [j.external_id for j in jobs] == ["7", "7"]


def test_to_job_skips_missing_title():
    assert _to_job({"id": 1}) is None


def test_to_job_accepts_numeric_zero_id():
    job = _to_job(
        {
            "id": 0,
            "title": "Zero",
            "company": {},
            "location": {},
            "description": "",
        }
    )
    assert job is not None
    assert job.external_id == "0"

