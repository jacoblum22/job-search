"""The scrape as an Azure Container Apps job (Azure plan, phase 5; docs/azure-scrape-job.md):
the vault files in the shared database, the shared scrape lock, the last-run record and
--skip-if-fresh.

The Postgres tests run when JOBSEARCH_PG_TEST_URL names a scratch database (see
tests/test_pg_backend.py); skipped otherwise.
"""

import importlib.util
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src import db, score_inputs
from src.db import connect, set_cursor

PG_URL = os.environ.get("JOBSEARCH_PG_TEST_URL")
needs_pg = pytest.mark.skipif(not PG_URL, reason="JOBSEARCH_PG_TEST_URL not set")
CFG = {"vault_gaps": {"index": "materials/profile/vault-index.json",
                      "record": "materials/tailor/skill-record.json"}}


def _aggregate():
    path = Path(__file__).parents[1] / "scripts" / "aggregate.py"
    spec = importlib.util.spec_from_file_location("aggregate_azure_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _vault(root: Path, index: str = '{"passages": []}', record: str | None = "{}") -> None:
    (root / "materials/profile").mkdir(parents=True)
    (root / "materials/profile/vault-index.json").write_text(index, encoding="utf-8")
    if record is not None:
        (root / "materials/tailor").mkdir(parents=True)
        (root / "materials/tailor/skill-record.json").write_text(record, encoding="utf-8")


def test_vault_files_go_from_the_desktop_to_the_job_through_the_database(tmp_path):
    desktop, job = tmp_path / "desktop", tmp_path / "job"
    _vault(desktop)
    job.mkdir()
    conn = connect(tmp_path / "shared.db")

    assert not score_inputs.ready(CFG, job)
    assert score_inputs.sync(conn, CFG, desktop) == ("push", [
        "materials/profile/vault-index.json", "materials/tailor/skill-record.json"])
    assert score_inputs.push(conn, CFG, desktop) == []  # unchanged: nothing written again
    assert score_inputs.sync(conn, CFG, job)[0] == "pull"
    assert score_inputs.ready(CFG, job)
    assert (job / "materials/tailor/skill-record.json").read_text(encoding="utf-8") == "{}"

    (desktop / "materials/tailor/skill-record.json").write_text('{"x": 1}', encoding="utf-8")
    assert score_inputs.push(conn, CFG, desktop) == ["materials/tailor/skill-record.json"]
    assert score_inputs.pull(conn, CFG, job) == ["materials/tailor/skill-record.json"]
    assert json.loads((job / "materials/tailor/skill-record.json").read_text(encoding="utf-8")) == {"x": 1}


def test_no_vault_configured_means_nothing_to_share(tmp_path):
    conn = connect(tmp_path / "shared.db")
    assert score_inputs.ready({}, tmp_path)
    assert score_inputs.sync(conn, {}, tmp_path) == ("pull", [])


def test_skip_if_fresh_reads_the_last_full_run(tmp_path):
    agg = _aggregate()
    conn = connect(tmp_path / "jobs.db")
    now = datetime(2026, 10, 28, 16, 0, tzinfo=timezone.utc)
    assert agg.fresh_run(conn, 6, now) is None
    finished = (now - timedelta(hours=2)).isoformat(timespec="seconds")
    set_cursor(conn, agg.LAST_FULL_RUN_KEY, json.dumps({"finished": finished, "host": "azure", "new": 3}))
    assert agg.fresh_run(conn, 6, now)["host"] == "azure"
    assert agg.fresh_run(conn, 1, now) is None
    set_cursor(conn, agg.LAST_FULL_RUN_KEY, "not json")
    assert agg.fresh_run(conn, 6, now) is None


def test_lock_is_only_the_file_on_sqlite(tmp_path, monkeypatch):
    agg = _aggregate()
    monkeypatch.setattr(agg, "LOCK_PATH", tmp_path / ".aggregate.lock")
    assert agg._acquire_lock()
    assert not agg._acquire_lock()
    agg._release_lock()
    assert not (tmp_path / ".aggregate.lock").exists()


@pytest.fixture
def shared_pg(monkeypatch):
    psycopg = pytest.importorskip("psycopg")
    name = f"t_{uuid.uuid4().hex[:10]}"
    admin = psycopg.connect(PG_URL, autocommit=True)
    admin.execute(f'CREATE SCHEMA "{name}"')
    sep = "&" if "?" in PG_URL else "?"
    monkeypatch.setenv("JOBSEARCH_DB", "postgres")
    monkeypatch.setenv("JOBSEARCH_PG_URL", f"{PG_URL}{sep}options=-csearch_path%3D{name}")
    yield
    admin.execute(f'DROP SCHEMA "{name}" CASCADE')
    admin.close()


@needs_pg
def test_shared_lock_keeps_a_second_machine_out(tmp_path, monkeypatch, shared_pg):
    agg = _aggregate()
    monkeypatch.setattr(agg, "LOCK_PATH", tmp_path / "desktop.lock")
    conn = connect(db.MAIN_DB)
    assert not db.scrape_lock_held(conn)

    held = db.try_scrape_lock()  # the Azure job, mid-run
    assert held is not None and db.scrape_lock_held(conn)
    assert not agg._acquire_lock()  # the desktop's file lock is free, the shared one isn't
    assert not (tmp_path / "desktop.lock").exists()

    held.release()
    assert agg._acquire_lock()
    assert db.scrape_lock_held(conn)
    agg._release_lock()
    assert not db.scrape_lock_held(conn)
    conn.close()


@needs_pg
def test_score_inputs_round_trip_through_postgres(tmp_path, shared_pg):
    _vault(tmp_path / "desktop", record=None)
    (tmp_path / "job").mkdir()
    conn = connect(db.MAIN_DB)
    assert score_inputs.push(conn, CFG, tmp_path / "desktop") == ["materials/profile/vault-index.json"]
    assert score_inputs.pull(conn, CFG, tmp_path / "job") == ["materials/profile/vault-index.json"]
    assert score_inputs.ready(CFG, tmp_path / "job")
    conn.close()


def test_job_spec_puts_every_key_in_a_secret():
    spec_path = Path(__file__).parents[1] / "scripts" / "azure_job_spec.py"
    s = importlib.util.spec_from_file_location("azure_job_spec_test", spec_path)
    mod = importlib.util.module_from_spec(s)
    s.loader.exec_module(mod)
    body = mod.spec({"JOBSEARCH_PG_URL": "postgresql://u:p@h/db?sslmode=require", "ADZUNA_APP_ID": "a",
                     "ADZUNA_APP_KEY": "", "CAREERJET_AFFID": None}, '{"refresh_token": "r"}', "/env/id", "canadacentral")
    conf = body["properties"]["configuration"]
    assert conf["triggerType"] == "Schedule" and conf["scheduleTriggerConfig"]["cronExpression"] == mod.CRON
    assert [x["name"] for x in conf["secrets"]] == ["pg-url", "adzuna-app-id", "gmail-token"]
    env = body["properties"]["template"]["containers"][0]["env"]
    assert all("value" not in e for e in env)  # only secret references, never plain values
    assert {e["name"] for e in env} == {"JOBSEARCH_PG_URL", "ADZUNA_APP_ID", "GMAIL_TOKEN_JSON"}
    with pytest.raises(Exception):
        mod.spec({}, None, "/env/id", "canadacentral")


def test_sources_that_block_azure_are_left_to_the_desktop(tmp_path, monkeypatch):
    agg = _aggregate()
    assert agg.cloud_skip({"cloud_sources": {"skip": ["CareerJet"]}}) == ["careerjet"]
    assert agg.cloud_skip({}) == []
    calls = []

    def run_with(host, only=None):
        calls.clear()
        monkeypatch.setattr(agg, "HOST", host)
        cfg = {"cloud_sources": {"skip": ["careerjet"]}, "api_sources": {"adzuna": {"enabled": False}},
               "search": {}, "score": {}, "enrich": {"enabled": False}}
        monkeypatch.setattr(agg, "fetch_careerjet_jobs", lambda **kw: calls.append("careerjet") or [])
        monkeypatch.setattr(agg, "generate_dashboard", lambda *a, **k: None)
        monkeypatch.setattr(agg, "generate_xlsx", lambda *a, **k: None)
        agg.run(cfg, db_path=tmp_path / f"{host}.db", dashboard_path=tmp_path / "d.html",
                xlsx_path=tmp_path / "x.xlsx", skip_workday=True, skip_apis=False, skip_email=True,
                workday_limit=0, skip_ats=True, only=only)
        return list(calls)

    assert run_with("azure") == []                          # the Azure job leaves it out
    assert run_with("DESKTOP", only={"careerjet"}) == ["careerjet"]
    assert run_with("DESKTOP") == ["careerjet"]
