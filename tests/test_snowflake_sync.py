import io
from datetime import date, datetime

import pyarrow.parquet as pq
from click.testing import CliRunner

import importlib.util
from pathlib import Path

from src import snowflake_sync as sf

_spec = importlib.util.spec_from_file_location(
    "snowflake_cli", Path(__file__).resolve().parent.parent / "scripts" / "snowflake_sync.py")
snowflake_cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(snowflake_cli)


def test_parquet_keeps_types_and_nulls():
    cols = [("id", 20), ("score", 701), ("title", 25), ("dbt_valid_to", 1114), ("ok", 16)]
    rows = [(1, 71.5, "Data Analyst", datetime(2026, 10, 28, 9, 0), True),
            (2, None, None, None, None)]
    t = pq.read_table(io.BytesIO(sf.parquet_bytes(cols, rows)))
    assert t.column_names == ["id", "score", "title", "dbt_valid_to", "ok"]
    assert str(t.schema.field("id").type) == "int64"
    assert str(t.schema.field("score").type) == "double"
    assert str(t.schema.field("title").type) == "string"
    assert str(t.schema.field("dbt_valid_to").type) == "timestamp[us]"
    assert t.to_pylist()[1] == {"id": 2, "score": None, "title": None, "dbt_valid_to": None, "ok": None}
    assert t.to_pylist()[0]["dbt_valid_to"] == datetime(2026, 10, 28, 9, 0)  # not shifted


def test_parquet_of_empty_table():
    t = pq.read_table(io.BytesIO(sf.parquet_bytes([("source", 25)], [])))
    assert t.num_rows == 0 and t.column_names == ["source"]


def test_blob_paths():
    assert sf.blob_paths("jobs", date(2026, 10, 29)) == (
        "jobs/latest/jobs.parquet", "jobs/history/2026-10-29.parquet")
    assert sf.blob_paths("analytics.jobs_snapshot", date(2026, 10, 29))[0] == \
        "jobs_snapshot/latest/jobs_snapshot.parquet"


def test_expired_only_old_history():
    names = ["jobs/latest/jobs.parquet", "jobs/history/2026-09-28.parquet",
             "jobs/history/2026-09-29.parquet", "jobs/history/2026-10-29.parquet"]
    assert sf.expired(names, date(2026, 10, 29)) == ["jobs/history/2026-09-28.parquet"]


class FakeContainer:
    def __init__(self, names=()):
        self.blobs = {n: b"" for n in names}

    def upload_blob(self, name, data, overwrite=False):
        assert overwrite
        self.blobs[name] = data

    def list_blobs(self):
        return [type("B", (), {"name": n})() for n in list(self.blobs)]

    def delete_blob(self, name):
        del self.blobs[name]


def test_export_writes_latest_and_history_and_prunes(monkeypatch):
    monkeypatch.setattr(sf, "read_table", lambda pg, t: ([("source", 25)], [("lever",)]))
    box = FakeContainer(["jobs/history/2026-01-01.parquet"])
    done = sf.export(None, box, ["jobs"], today=date(2026, 10, 29))
    assert done[0].rows == 1
    assert set(box.blobs) == {"jobs/latest/jobs.parquet", "jobs/history/2026-10-29.parquet"}


def test_history_export_writes_latest_only(monkeypatch):
    monkeypatch.setattr(sf, "read_table", lambda pg, t: ([("id", 20)], []))
    box = FakeContainer()
    sf.export(None, box, [sf.HISTORY_TABLE], today=date(2026, 10, 29), history_copy=False)
    assert set(box.blobs) == {"jobs_snapshot/latest/jobs_snapshot.parquet"}


def test_daily_skips_without_blob_url(monkeypatch):
    monkeypatch.setattr(snowflake_cli, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv(sf.BLOB_URL_ENV, raising=False)
    result = CliRunner().invoke(snowflake_cli.cli, ["daily"])
    assert result.exit_code == 0 and "skipped" in result.output


def test_daily_exports_only_until_snowflake_is_set_up(monkeypatch, tmp_path):
    monkeypatch.setattr(snowflake_cli, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv(sf.BLOB_URL_ENV, "https://x.blob.core.windows.net/c")
    for k in sf.SNOWFLAKE_ENV:
        monkeypatch.delenv(k, raising=False)
    calls = []
    monkeypatch.setattr(snowflake_cli, "_export", lambda tables, history_copy=True: calls.append("export"))
    monkeypatch.setattr(snowflake_cli, "_load", lambda: calls.append("load") or 0)
    result = CliRunner().invoke(snowflake_cli.cli, ["daily"])
    assert result.exit_code == 0, result.output
    assert calls == ["export"]


def test_read_table_drops_bookkeeping_column():
    class Col:
        def __init__(self, name, type_code):
            self.name, self.type_code = name, type_code

    class Cur:
        description = [Col("source", 25), Col("_row_hash", 25), Col("ok", 20)]
        def execute(self, q): self.q = q
        def fetchall(self): return [("lever", "abc", 1)]
        def __enter__(self): return self
        def __exit__(self, *a): pass

    class Pg:
        def cursor(self): return Cur()

    cols, rows = sf.read_table(Pg(), "enrich_attempts")
    assert cols == [("source", 25), ("ok", 20)] and rows == [("lever", 1)]


def test_make_key_writes_private_and_returns_public(tmp_path):
    from cryptography.hazmat.primitives import serialization

    path = tmp_path / "credentials" / "k.p8"
    public = sf.make_key(path)
    key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    assert key.key_size == 2048
    assert "\n" not in public and public.startswith("MIIB")
    import pytest
    with pytest.raises(sf.SnowflakeSyncError):
        sf.make_key(path)  # never overwrites


def test_daily_skips_dbt_when_load_leaves_jobs_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(snowflake_cli, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv(sf.BLOB_URL_ENV, "https://x.blob.core.windows.net/c")
    for k in sf.SNOWFLAKE_ENV:
        monkeypatch.setenv(k, "x")
    load_sql = tmp_path / "load.sql"
    load_sql.write_text("select 1;")
    monkeypatch.setattr(sf, "LOAD_SQL", load_sql)
    monkeypatch.setattr(snowflake_cli, "_export", lambda tables, history_copy=True: None)
    monkeypatch.setattr(snowflake_cli, "_load", lambda: 0)
    ran = []
    monkeypatch.setattr(snowflake_cli.subprocess, "run", lambda *a, **k: ran.append(a))
    result = CliRunner().invoke(snowflake_cli.cli, ["daily"])
    assert result.exit_code != 0 and "empty" in result.output
    assert ran == []
