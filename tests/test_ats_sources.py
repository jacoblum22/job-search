"""Greenhouse / Lever / Ashby / SmartRecruiters / Workable adapters.

Fixtures in tests/fixtures/ats/ are real API responses captured Oct 2026
(long lists trimmed), so these tests pin the field names each feed uses.
"""

import json
from pathlib import Path

import httpx
import pytest

from src.sources import ashby, greenhouse, lever, smartrecruiters, workable
from src.sources.ats_common import location_ok, normalize_boards

FIXTURES = Path(__file__).parent / "fixtures" / "ats"


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeClient:
    """Serves fixture bodies by URL substring; anything else is a 404."""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append(url)
        req = httpx.Request(method, url)
        for needle, (status, body) in self.routes.items():
            if needle in url:
                return httpx.Response(status, json=body, request=req)
        return httpx.Response(404, json={"error": "not found"}, request=req)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("src.http_retry.time.sleep", lambda _s: None)


@pytest.mark.parametrize(
    "location, expected",
    [
        ("Burnaby, BC", True),
        ("Remote - Canada", True),
        ("Remote", True),
        ("Remote - North America", True),
        ("Canada", True),
        ("Toronto, ON", False),
        ("Remote - Sydney, New South Wales, Australia", False),
        ("Remote - New Zealand", False),
        ("Remote - Minneapolis, Minnesota, United States", False),
    ],
)
def test_location_ok(location, expected):
    assert location_ok(location) is expected


def test_normalize_boards_accepts_strings_and_skips_disabled():
    boards = normalize_boards(["later", {"slug": "klue", "name": "Klue"}, {"slug": "x", "enabled": False}, {}])
    assert boards == [{"slug": "later", "name": "later"}, {"slug": "klue", "name": "Klue"}]


def test_greenhouse_full_description_unescaped():
    jobs = greenhouse.parse_board(load("greenhouse_jobs.json"), {"slug": "momentenergy", "name": "Moment Energy"})
    assert jobs, "Surrey, BC postings should be kept"
    job = jobs[0]
    assert job.source == "greenhouse:momentenergy"
    assert job.external_id == "4355474009"
    assert job.location == "Surrey, BC"
    assert job.url.startswith("https://job-boards.greenhouse.io/momentenergy/jobs/")
    assert "&lt;" not in job.description and "<p>" not in job.description
    assert "About Moment Energy" in job.description
    assert len(job.description) > 1000


def test_greenhouse_missing_board_is_empty():
    client = FakeClient({"boards-api.greenhouse.io": (404, load("greenhouse_404.json"))})
    assert greenhouse.fetch_greenhouse_jobs(["nope"], client=client) == []


def test_lever_joins_lists_and_drops_out_of_area():
    jobs = lever.parse_board(load("lever_postings.json"), {"slug": "beedie", "name": "Beedie"})
    locations = {j.location for j in jobs}
    assert "Etobicoke, ON" not in locations
    assert locations <= {"Vancouver, BC", "Burnaby, BC"}
    job = jobs[0]
    assert job.title == "Accountant"
    assert job.company == "Beedie"
    assert job.posted_date and len(job.posted_date) == 10
    assert "## Desired Skills & Experience" in job.description
    assert "We value your interest in Beedie Capital" in job.description


def test_lever_missing_board_is_empty():
    client = FakeClient({"api.lever.co": (404, load("lever_404.json"))})
    assert lever.fetch_lever_jobs(["nope"], client=client) == []


def test_ashby_remote_region_and_empty_board():
    jobs = ashby.parse_board(load("ashby_board_linear.json"), {"slug": "linear", "name": "Linear"})
    assert [j.location for j in jobs] == ["Remote - North America"]  # the two Europe roles drop
    assert "At Linear" in jobs[0].description
    assert jobs[0].url.startswith("https://jobs.ashbyhq.com/linear/")
    assert ashby.parse_board(load("ashby_board.json"), {"slug": "spexi", "name": "Spexi"}) == []


def test_workable_merges_per_location_rows():
    jobs = workable.parse_board(load("workable_widget.json"), {"slug": "semios", "name": "Semios"})
    codes = [j.external_id for j in jobs]
    assert len(codes) == len(set(codes))
    assert all(location_ok(j.location) for j in jobs)
    accounting = next(j for j in jobs if j.external_id == "A9698F8F42")
    assert accounting.location == "Vancouver, British Columbia, Canada"
    # The widget's description already includes requirements and benefits.
    assert "We want you to succeed" in accounting.description
    assert "Why this is the opportunity for you" in accounting.description
    assert not any("Australia" in j.location or "New Zealand" in j.location for j in jobs)


def test_smartrecruiters_detail_sections_and_location_gate():
    listing = load("smartrecruiters_list.json")
    detail = load("smartrecruiters_detail.json")
    client = FakeClient(
        {
            "/postings/744000034588665": (200, detail),
            "/companies/OnActuate/postings": (200, listing),
        }
    )
    # Every OnActuate posting is outside Canada, so no detail call is spent.
    assert smartrecruiters.fetch_smartrecruiters_jobs(["OnActuate"], client=client) == []
    assert not any("/postings/7" in c for c in client.calls)

    job = smartrecruiters.to_job(listing["content"][0], detail, {"slug": "OnActuate", "name": "OnActuate"})
    assert job.location == "Gurugram, HR, India"
    assert job.url == "https://jobs.smartrecruiters.com/OnActuate/744000034588665-senior-executive-finance"
    assert "## Job Description" in job.description
    assert "## Qualifications" in job.description


def test_smartrecruiters_fetches_detail_for_local_matching_title():
    listing = load("smartrecruiters_list.json")
    detail = load("smartrecruiters_detail.json")
    post = dict(listing["content"][0], name="Data Analyst")
    post["location"] = {"city": "Vancouver", "region": "BC", "country": "ca", "fullLocation": "Vancouver, BC, Canada"}
    client = FakeClient(
        {
            "/postings/744000034588665": (200, detail),
            "/companies/Acme/postings": (200, {"totalFound": 1, "content": [post]}),
        }
    )
    jobs = smartrecruiters.fetch_smartrecruiters_jobs(
        [{"slug": "Acme", "name": "Acme"}], search={"keywords": ["data analyst"]}, client=client
    )
    assert [j.title for j in jobs] == ["Data Analyst"]
    assert "## Job Description" in jobs[0].description


def test_one_bad_board_does_not_sink_the_rest():
    client = FakeClient({"/boards/good/": (200, load("greenhouse_jobs.json"))})
    jobs = greenhouse.fetch_greenhouse_jobs(["bad", "good"], client=client)
    assert jobs and all(j.source == "greenhouse:good" for j in jobs)


def _aggregate_module():
    import importlib.util

    path = Path(__file__).parents[1] / "scripts" / "aggregate.py"
    spec = importlib.util.spec_from_file_location("aggregate_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_merge_boards_adds_new_workday_tenants_only(tmp_path):
    boards = tmp_path / "boards.yaml"
    boards.write_text(
        "bc_locations: &bc\n  - Vancouver\n"
        "workday:\n"
        "  - {name: CIBC dup, tenant: cibc, site: search}\n"
        "  - {name: Clio, tenant: clio, wd: wd3, site: cliocareersite, location_filter: *bc}\n"
        "greenhouse:\n  - later\n",
        encoding="utf-8",
    )
    cfg = {"sources": [{"name": "CIBC", "tenant": "cibc", "site": "search"}], "search": {}}
    merged = _aggregate_module().merge_boards(cfg, boards)
    assert [s["name"] for s in merged["sources"]] == ["CIBC", "Clio"]
    assert merged["sources"][1]["location_filter"] == ["Vancouver"]
    assert merged["ats_boards"] == {"greenhouse": ["later"]}


def test_shipped_board_list_names_are_not_vancouver_words():
    """A Workday source named e.g. "X Vancouver" would keep every posting worldwide."""
    import yaml

    from src.location_filter import is_vancouver_area

    data = yaml.safe_load((Path(__file__).parents[1] / "config" / "ats_boards.yaml").read_text(encoding="utf-8"))
    names = [s["name"] for s in data["workday"]]
    assert names and not [n for n in names if is_vancouver_area(n)]
    from src.sources.registry import BOARD_PLATFORMS, FEEDS

    for platform in BOARD_PLATFORMS:
        assert normalize_boards(data[platform]), platform
    assert set(data) - {"bc_locations", "workday", "feeds"} <= set(BOARD_PLATFORMS)
    assert set(data["feeds"]) <= set(FEEDS)


def test_dashboard_refreshes_after_each_source(tmp_path, monkeypatch):
    from src.db import Job

    module = _aggregate_module()
    dashboard = tmp_path / "dashboard.html"
    jobs_per_redraw = []

    def job(ext):
        return Job(source="t", external_id=ext, title=f"Data Analyst {ext}", company="C", location="Vancouver, BC",
                   description="Analyze data with SQL and Python. " * 20)

    def first(boards, search):
        return [job("first")]

    def second(boards, search):
        return [job("second")]

    real_generate = module.generate_dashboard

    def recording_generate(conn, path):
        jobs_per_redraw.append(conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])
        return real_generate(conn, path)

    monkeypatch.setattr(module, "generate_dashboard", recording_generate)
    monkeypatch.setattr(module, "BOARD_PLATFORMS", {"a": first, "b": second})
    cfg = {"search": {"keywords": ["data analyst"]}, "enrich": {"enabled": False},
           "ats_boards": {"a": ["x"], "b": ["y"]}}
    module.run(cfg, db_path=tmp_path / "jobs.db", dashboard_path=dashboard, xlsx_path=tmp_path / "x.xlsx",
               skip_workday=True, skip_apis=True, skip_email=True, workday_limit=0)
    # Drawn once after each source is saved (1 job, then 2), then once at the end.
    assert jobs_per_redraw == [1, 2, 2]
    assert "Data Analyst second" in dashboard.read_text(encoding="utf-8")


def test_wait_lock_takes_the_lock_once_the_other_run_finishes(tmp_path, monkeypatch):
    module = _aggregate_module()
    lock = tmp_path / ".aggregate.lock"
    monkeypatch.setattr(module, "LOCK_PATH", lock)
    lock.write_text("123")
    sleeps = []

    def other_run_finishes(seconds):
        sleeps.append(seconds)
        lock.unlink()

    monkeypatch.setattr(module.time, "sleep", other_run_finishes)
    assert module._wait_for_lock(60, poll_seconds=5)
    assert sleeps == [5] and lock.read_text() != "123"


def test_wait_lock_gives_up_while_a_fresh_lock_is_held(tmp_path, monkeypatch):
    module = _aggregate_module()
    lock = tmp_path / ".aggregate.lock"
    monkeypatch.setattr(module, "LOCK_PATH", lock)
    lock.write_text("123")
    monkeypatch.setattr(module.time, "sleep", lambda s: None)
    assert not module._wait_for_lock(0)
    assert lock.read_text() == "123"
