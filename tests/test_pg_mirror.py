"""The Postgres shadow copy (src/pg_mirror.py) against a real Postgres.

Runs when JOBSEARCH_PG_TEST_URL names a Postgres database the tests may write to
(each test works in its own schema and drops it); skipped otherwise. Never point it
at the Azure server.
"""

import json
import os
import sqlite3
import uuid

import pytest

from src import pg_mirror
from src.db import Job, connect, upsert_job
from src.enrich import ENRICH_SCHEMA
from src.retention import SCHEMA as PRUNED_SCHEMA
from src.tailor.store import ensure_table

PG_URL = os.environ.get("JOBSEARCH_PG_TEST_URL")


def test_pg_type_follows_sqlite_affinity():
    assert pg_mirror.pg_type("INTEGER") == "BIGINT"
    assert pg_mirror.pg_type("TEXT") == "TEXT"
    assert pg_mirror.pg_type("") == "TEXT"
    assert pg_mirror.pg_type("REAL") == "DOUBLE PRECISION"
    assert pg_mirror.pg_type("VARCHAR(20)") == "TEXT"


def test_coerce_names_the_row_that_doesnt_fit():
    assert pg_mirror._coerce(3.0, "BIGINT", "x") == 3
    assert pg_mirror._coerce("a\x00b", "TEXT", "x") == "ab"
    with pytest.raises(pg_mirror.MirrorError, match=r"jobs \{'id': 7\}\.score"):
        pg_mirror._coerce("high", "BIGINT", "jobs {'id': 7}.score")


def test_enabled_reads_settings():
    assert not pg_mirror.enabled({})
    assert not pg_mirror.enabled({"database": {"postgres_mirror": False}})
    assert pg_mirror.enabled({"database": {"postgres_mirror": True}})


needs_pg = pytest.mark.skipif(not PG_URL, reason="JOBSEARCH_PG_TEST_URL not set")


@pytest.fixture
def pg():
    psycopg = pytest.importorskip("psycopg")
    schema = f"t_{uuid.uuid4().hex[:10]}"
    admin = psycopg.connect(PG_URL, autocommit=True)
    admin.execute(f'CREATE SCHEMA "{schema}"')
    conn = psycopg.connect(PG_URL, options=f"-c search_path={schema}")
    yield conn
    conn.close()
    admin.execute(f'DROP SCHEMA "{schema}" CASCADE')
    admin.close()


def _job(n: int, **kw) -> Job:
    return Job(source="greenhouse", external_id=str(n), title=f"Data Analyst {n}", company="Acme",
               location="Vancouver, BC", description=kw.pop("description", "Python and SQL."),
               raw={"n": n}, **kw)


@pytest.fixture
def jobs_db(tmp_path):
    path = tmp_path / "jobs.db"
    conn = connect(path)
    ensure_table(conn)
    conn.executescript(PRUNED_SCHEMA + ENRICH_SCHEMA)
    for n in range(1, 6):
        upsert_job(conn, _job(n))
    conn.execute("UPDATE jobs SET tier = 'A', score = 71, score_reasons = ? WHERE id = 1",
                 (json.dumps(["+15 SQL"]),))
    conn.execute("INSERT INTO applications (job_id, folder, status, score) VALUES "
                 "(1, 'materials/applications/acme', 'ready_for_review', 71.8)")
    conn.execute("INSERT INTO pruned_jobs VALUES ('lever', 'old-1', '2026-10-01T00:00:00+00:00')")
    conn.commit()
    conn.close()
    return path


def _pg_rows(pg, table, order):
    return pg.execute(f'SELECT * FROM "{table}" ORDER BY {order}').fetchall()


@needs_pg
def test_first_sync_copies_every_table_and_counts_match(jobs_db, pg):
    stats = pg_mirror.sync(jobs_db, pg)
    assert stats["jobs"] == {"rows": 5, "inserted": 5, "updated": 0, "deleted": 0}
    assert stats["applications"]["inserted"] == 1
    assert stats["pruned_jobs"]["inserted"] == 1
    assert set(stats) == {"jobs", "applications", "pruned_jobs", "enrich_attempts", "source_cursors"}

    report = pg_mirror.check(jobs_db, pg)
    assert all(r["match"] for r in report.values()), report

    lite = sqlite3.connect(jobs_db)
    want = lite.execute("SELECT id, title, score, score_reasons, raw FROM jobs ORDER BY id").fetchall()
    got = [tuple(r) for r in pg.execute("SELECT id, title, score, score_reasons, raw FROM jobs ORDER BY id")]
    assert got == want
    assert pg.execute("SELECT score FROM applications").fetchone()[0] == 71.8


@needs_pg
def test_second_sync_sends_only_what_changed(jobs_db, pg):
    pg_mirror.sync(jobs_db, pg)
    assert pg_mirror.sync(jobs_db, pg)["jobs"] == {"rows": 5, "inserted": 0, "updated": 0, "deleted": 0}

    conn = connect(jobs_db)
    upsert_job(conn, _job(6))
    conn.execute("UPDATE jobs SET status = 'applied' WHERE id = 2")
    conn.execute("DELETE FROM jobs WHERE id = 3")  # retention pruned it
    conn.commit()
    conn.close()

    stats = pg_mirror.sync(jobs_db, pg)["jobs"]
    assert stats == {"rows": 5, "inserted": 1, "updated": 1, "deleted": 1}
    assert [r[0] for r in pg.execute("SELECT id FROM jobs ORDER BY id")] == [1, 2, 4, 5, 6]
    assert pg.execute("SELECT status FROM jobs WHERE id = 2").fetchone()[0] == "applied"
    assert all(r["match"] for r in pg_mirror.check(jobs_db, pg).values())


@needs_pg
def test_check_reports_drift_and_missing_tables(jobs_db, pg):
    assert pg_mirror.check(jobs_db, pg)["jobs"]["postgres"] is None
    pg_mirror.sync(jobs_db, pg)
    pg.execute("DELETE FROM jobs WHERE id = 4")
    pg.commit()
    report = pg_mirror.check(jobs_db, pg)
    assert report["jobs"] == {"sqlite": 5, "postgres": 4, "differ": 1, "match": False}
    assert report["applications"]["match"]


@needs_pg
def test_a_column_added_to_jobs_db_reaches_postgres(jobs_db, pg):
    pg_mirror.sync(jobs_db, pg)
    lite = sqlite3.connect(jobs_db)
    lite.execute("ALTER TABLE jobs ADD COLUMN salary TEXT")
    lite.execute("UPDATE jobs SET salary = '60k' WHERE id = 1")
    lite.commit()
    lite.close()
    assert pg_mirror.sync(jobs_db, pg)["jobs"]["updated"] == 5  # every row's hash now has the column
    assert pg.execute("SELECT salary FROM jobs WHERE id = 1").fetchone()[0] == "60k"


@needs_pg
def test_a_bad_value_rolls_back_the_whole_sync(jobs_db, pg):
    pg_mirror.sync(jobs_db, pg)
    lite = sqlite3.connect(jobs_db)
    lite.execute("UPDATE applications SET status = 'approved'")
    lite.execute("UPDATE jobs SET score = 'high' WHERE id = 5")  # SQLite allows it; Postgres won't
    lite.commit()
    lite.close()
    with pytest.raises(pg_mirror.MirrorError, match="score"):
        pg_mirror.sync(jobs_db, pg)
    assert pg.execute("SELECT status FROM applications").fetchone()[0] == "ready_for_review"


@needs_pg
def test_mirror_never_writes_jobs_db(jobs_db, pg):
    before = jobs_db.read_bytes()
    pg_mirror.sync(jobs_db, pg)
    pg_mirror.check(jobs_db, pg)
    assert jobs_db.read_bytes() == before
