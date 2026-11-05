import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "dbt_wrapper", Path(__file__).resolve().parent.parent / "scripts" / "dbt.py")
dbt_wrapper = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dbt_wrapper)


def test_connection_env_splits_url():
    env = dbt_wrapper.connection_env(
        "postgresql://jake%40x:p%40ss%2Fw@srv.postgres.database.azure.com:6432/jobsearch?sslmode=verify-full")
    assert env == {
        "DBT_PG_HOST": "srv.postgres.database.azure.com",
        "DBT_PG_PORT": "6432",
        "DBT_PG_USER": "jake@x",
        "DBT_PG_PASSWORD": "p@ss/w",
        "DBT_PG_DBNAME": "jobsearch",
        "DBT_PG_SSLMODE": "verify-full",
    }


def test_connection_env_defaults():
    env = dbt_wrapper.connection_env("postgres://u:p@localhost/jobsearch")
    assert env["DBT_PG_PORT"] == "5432"
    assert env["DBT_PG_SSLMODE"] == "require"


def test_connection_env_rejects_other_urls():
    with pytest.raises(ValueError):
        dbt_wrapper.connection_env("sqlite:///jobs.db")


def test_has_work(tmp_path):
    (tmp_path / "models").mkdir()
    (tmp_path / "models" / ".gitkeep").touch()
    assert not dbt_wrapper.has_work(tmp_path)
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / "jobs_snapshot.sql").write_text("select 1")
    assert dbt_wrapper.has_work(tmp_path)


def test_has_work_counts_yaml_snapshots(tmp_path):
    (tmp_path / "snapshots").mkdir()
    (tmp_path / "snapshots" / "jobs_snapshot.yml").write_text("snapshots: []")
    assert dbt_wrapper.has_work(tmp_path)
