import json

import httpx

from src.db import Job, connect, upsert_job
from src.enrich import description_from_html, enrich_descriptions, needs_enrichment

FULL = "Requires 2 years of experience in analysis. " * 30


def _page(desc: str) -> str:
    ld = json.dumps({"@type": "JobPosting", "description": f"<p>{desc}</p>"})
    return f'<html><head><script type="application/ld+json">{ld}</script></head><body></body></html>'


def _job(ext_id="1", url="https://www.adzuna.ca/details/1?utm_medium=api", desc="Short snippet…", **kw):
    return Job(
        source=kw.get("source", "adzuna"),
        external_id=ext_id,
        title=kw.get("title", "Data Analyst"),
        company="Acme",
        location="Vancouver, BC",
        description=desc,
        url=url,
    )


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_description_from_json_ld():
    text = description_from_html(_page("Requires 2 years of experience in analysis."))
    assert "2 years" in text and "<p>" not in text


def test_description_from_graph_and_escaped_html():
    ld = json.dumps({"@graph": [{"@type": "WebPage"}, {"@type": ["JobPosting"], "description": "&lt;b&gt;Python&lt;/b&gt; required"}]})
    html = f'<script type="application/ld+json">{ld}</script>'
    assert description_from_html(html) == "**Python** required"


def test_description_fallback_container():
    html = '<div class="adp-body"><p>Build dashboards in Power BI.</p></div>'
    assert "Power BI" in description_from_html(html)


def test_needs_enrichment():
    assert needs_enrichment(_job())
    assert not needs_enrichment(_job(desc=FULL))
    assert not needs_enrichment(_job(url=""))
    assert not needs_enrichment(_job(url="https://www.linkedin.com/jobs/view/1"))
    assert not needs_enrichment(_job(url="https://jobviewtrack.com/v2/abc"))


def test_enrich_replaces_snippet_and_recomputes_years():
    job = _job()
    stats = enrich_descriptions([job], client=_client(lambda r: httpx.Response(200, text=_page(FULL))), host_pause=0)
    assert stats["enriched"] == 1
    assert job.description.startswith("Requires 2 years")
    assert job.years_experience == 2


def test_enrich_failures_are_skipped_not_raised(monkeypatch):
    monkeypatch.setattr("src.http_retry.time.sleep", lambda s: None)

    def handler(request):
        if "/2" in request.url.path:
            raise httpx.ConnectError("boom")
        if "/3" in request.url.path:
            return httpx.Response(200, text="<html>Job no longer available</html>")
        return httpx.Response(404)

    jobs = [_job(str(i), url=f"https://example.com/{i}") for i in (1, 2, 3)]
    stats = enrich_descriptions(jobs, client=_client(handler), host_pause=0)
    assert stats["failed"] == 3
    assert all(j.description == "Short snippet…" for j in jobs)


def test_should_fetch_and_cap():
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(200, text=_page(FULL))

    jobs = [_job(str(i), url=f"https://example.com/{i}", title="HVAC Tech" if i == 0 else "Data Analyst") for i in range(4)]
    stats = enrich_descriptions(
        jobs,
        client=_client(handler),
        host_pause=0,
        max_fetches=2,
        should_fetch=lambda j: "HVAC" not in j.title,
    )
    assert len(calls) == 2
    assert stats["enriched"] == 2 and stats["capped"] == 1
    assert jobs[0].description == "Short snippet…"


def test_db_reuses_stored_and_skips_recent_failures(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    upsert_job(conn, _job("stored", desc=FULL))
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(404)

    client = _client(handler)
    stored, dead = _job("stored"), _job("dead", url="https://example.com/dead")
    stats = enrich_descriptions([stored, dead], conn=conn, client=client, host_pause=0)
    assert stats["reused"] == 1 and stats["failed"] == 1
    assert stored.description == FULL
    assert calls == ["https://example.com/dead"]

    # Second run: the dead link isn't refetched.
    stats = enrich_descriptions([_job("dead", url="https://example.com/dead")], conn=conn, client=client, host_pause=0)
    assert stats["skipped_recent"] == 1
    assert len(calls) == 1


def test_db_does_not_refetch_enriched_but_unstored(tmp_path):
    # Enriched, then dropped by the filters (never upserted): the next run
    # must move on to other listings rather than refetch it.
    conn = connect(tmp_path / "jobs.db")
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(200, text=_page(FULL))

    client = _client(handler)
    enrich_descriptions([_job("a", url="https://example.com/a")], conn=conn, client=client, host_pause=0)
    stats = enrich_descriptions(
        [_job("a", url="https://example.com/a"), _job("b", url="https://example.com/b")],
        conn=conn,
        client=client,
        host_pause=0,
        max_fetches=1,
    )
    assert calls == ["https://example.com/a", "https://example.com/b"]
    assert stats["skipped_recent"] == 1 and stats["enriched"] == 1


def test_backfill_updates_stored_snippets(tmp_path):
    from src.enrich import backfill_stored

    conn = connect(tmp_path / "jobs.db")
    upsert_job(conn, _job("x", url="https://example.com/x"))
    upsert_job(conn, _job("y", url="https://www.linkedin.com/jobs/view/1"))
    stats = backfill_stored(
        conn, client=_client(lambda r: httpx.Response(200, text=_page(FULL))), host_pause=0
    )
    assert stats["enriched"] == 1
    rows = dict(conn.execute("SELECT external_id, description FROM jobs").fetchall())
    assert rows["x"].startswith("Requires 2 years")
    assert rows["y"] == "Short snippet…"


def test_worth_keeping_drops_irrelevant_snippets_only():
    from src.enrich import worth_keeping

    def wanted(j):
        return "Data" in j.title

    assert worth_keeping(_job("a"), wanted)  # relevant snippet: kept, to be filled
    assert not worth_keeping(_job("b", title="HVAC Technician"), wanted)  # irrelevant snippet: dropped
    assert worth_keeping(_job("c", title="HVAC Technician", desc=FULL), wanted)  # full posting: kept


def test_backfill_records_attempts_and_skips_recent_failures(tmp_path):
    from src.enrich import backfill_stored

    conn = connect(tmp_path / "jobs.db")
    upsert_job(conn, _job("x", url="https://example.com/x"))
    calls = []

    def handler(r):
        calls.append(str(r.url))
        return httpx.Response(404)

    backfill_stored(conn, client=_client(handler), host_pause=0)
    stats = backfill_stored(conn, client=_client(handler), host_pause=0)
    assert len(calls) == 1
    assert stats["skipped_recent"] == 1
