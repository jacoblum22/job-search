import importlib.util
from pathlib import Path

from src.db import Job, connect, upsert_job

_spec = importlib.util.spec_from_file_location(
    "prune_unwanted", Path(__file__).resolve().parent.parent / "scripts" / "prune_unwanted.py"
)
prune = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(prune)

SEARCH = {"keywords": ["data analyst"]}


def _job(ext_id, title, desc="Short snippet"):
    return Job(source="adzuna", external_id=ext_id, title=title, company="Acme",
               location="Vancouver, BC", description=desc, url="https://example.com/" + ext_id)


def test_unwanted_rows_only_irrelevant_snippets(tmp_path):
    conn = connect(tmp_path / "jobs.db")
    upsert_job(conn, _job("keep", "Data Analyst"))
    upsert_job(conn, _job("drop", "HVAC Technician"))
    upsert_job(conn, _job("full", "HVAC Technician", desc="x" * 1200))
    titles = [r[2] for r in prune.unwanted_rows(conn, SEARCH)]
    assert titles == ["HVAC Technician"]
    assert len(titles) == 1
