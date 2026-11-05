"""Copy the job tables to Snowflake (Azure plan, phase 9; docs/snowflake-guide.md).

Every day the app's tables in Postgres are written out as Parquet files (a compact file format
that keeps each column's type) into an Azure storage container. Snowflake reads them from there:
the SQL in snowflake/load.sql (Jake's) replaces the RAW tables with the newest files, and then dbt
builds the same models it builds in Postgres.

    <container>/<table>/latest/<table>.parquet      today's full copy, replaced every day
    <container>/<table>/history/<YYYY-MM-DD>.parquet one per day, deleted after 30 days

Settings, all in the git-ignored .env:
    JOBSEARCH_BLOB_URL   https://<storage account>.blob.core.windows.net/<container>
    SNOWFLAKE_*          the Snowflake login (dbt/profiles.yml lists them)
The storage login is the Azure CLI's (`az login` on the desktop), so no storage key is kept anywhere.
"""

from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parent.parent
BLOB_URL_ENV = "JOBSEARCH_BLOB_URL"
LOAD_SQL = ROOT / "snowflake" / "load.sql"
# The tables dbt's sources read (dbt/models/staging/_sources.yml), all in Postgres's public schema.
TABLES = ("jobs", "applications", "pruned_jobs", "enrich_attempts", "source_cursors")
# The prod snapshot, copied once so Snowflake's history starts where Postgres's did.
HISTORY_TABLE = "analytics.jobs_snapshot"
SKIP_COLUMNS = {"_row_hash"}  # pg_mirror's bookkeeping column, not job data
KEEP_DAYS = 30
SNOWFLAKE_ENV = ("SNOWFLAKE_ACCOUNT", "SNOWFLAKE_USER", "SNOWFLAKE_PRIVATE_KEY_PATH",
                 "SNOWFLAKE_ROLE", "SNOWFLAKE_WAREHOUSE", "SNOWFLAKE_DATABASE")

# Postgres type codes (pg_type oids) to Parquet types; anything else is written as text.
_INT_OIDS = {20, 21, 23}            # bigint, smallint, integer
_FLOAT_OIDS = {700, 701, 1700}      # real, double precision, numeric
_TIMESTAMP_OID = 1114               # timestamp without a zone (dbt's snapshot columns, UTC)
_TIMESTAMPTZ_OID = 1184
_BOOL_OID = 16


class SnowflakeSyncError(RuntimeError):
    pass


@dataclass
class Export:
    table: str
    rows: int
    paths: list[str]


def parquet_bytes(columns: list[tuple[str, int]], rows: Iterable[tuple]) -> bytes:
    """A Parquet file of the rows. columns are (name, Postgres type code) as psycopg describes them."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    def arrow_type(oid: int):
        if oid in _INT_OIDS:
            return pa.int64()
        if oid in _FLOAT_OIDS:
            return pa.float64()
        if oid == _TIMESTAMP_OID:
            # no zone, like the snapshot columns dbt makes in Snowflake (TIMESTAMP_NTZ)
            return pa.timestamp("us")
        if oid == _TIMESTAMPTZ_OID:
            return pa.timestamp("us", tz="UTC")
        if oid == _BOOL_OID:
            return pa.bool_()
        return pa.string()

    rows = list(rows)
    arrays = []
    for i, (_, oid) in enumerate(columns):
        typ = arrow_type(oid)
        values = [r[i] for r in rows]
        if oid in _FLOAT_OIDS:
            values = [None if v is None else float(v) for v in values]
        elif oid == _TIMESTAMPTZ_OID:
            values = [None if v is None else v.astimezone(timezone.utc) for v in values]
        elif typ == pa.string():
            values = [None if v is None else str(v) for v in values]
        arrays.append(pa.array(values, type=typ))
    table = pa.Table.from_arrays(arrays, names=[c for c, _ in columns])
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    return buf.getvalue()


def blob_paths(table: str, day: date) -> tuple[str, str]:
    """(latest, history) paths of a table's file inside the container."""
    name = table.split(".")[-1]
    return f"{name}/latest/{name}.parquet", f"{name}/history/{day.isoformat()}.parquet"


def expired(names: Iterable[str], today: date, keep_days: int = KEEP_DAYS) -> list[str]:
    """History files older than keep_days."""
    cutoff = today - timedelta(days=keep_days)
    out = []
    for n in names:
        m = re.search(r"/history/(\d{4}-\d{2}-\d{2})\.parquet$", n)
        if m and date.fromisoformat(m.group(1)) < cutoff:
            out.append(n)
    return out


def read_table(pg, table: str) -> tuple[list[tuple[str, int]], list[tuple]]:
    """Every row of a Postgres table, minus the bookkeeping columns."""
    from psycopg import sql

    schema, _, name = table.rpartition(".")
    ident = sql.Identifier(schema or "public", name)
    with pg.cursor() as cur:
        cur.execute(sql.SQL("SELECT * FROM {}").format(ident))
        keep = [i for i, d in enumerate(cur.description) if d.name not in SKIP_COLUMNS]
        columns = [(cur.description[i].name, cur.description[i].type_code) for i in keep]
        rows = [tuple(r[i] for i in keep) for r in cur.fetchall()]
    return columns, rows


def container_client(url: str | None = None):
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import ContainerClient

    url = url or os.environ.get(BLOB_URL_ENV)
    if not url:
        raise SnowflakeSyncError(f"{BLOB_URL_ENV} is not set (add it to .env)")
    return ContainerClient.from_container_url(
        url, credential=DefaultAzureCredential(exclude_interactive_browser_credential=True))


def export(pg, container, tables: Iterable[str] = TABLES, today: date | None = None,
           history_copy: bool = True) -> list[Export]:
    """Write each table to the container as Parquet and drop history files past KEEP_DAYS."""
    today = today or datetime.now(timezone.utc).date()
    done = []
    for table in tables:
        columns, rows = read_table(pg, table)
        data = parquet_bytes(columns, rows)
        latest, history = blob_paths(table, today)
        paths = [latest, history] if history_copy else [latest]
        for path in paths:
            container.upload_blob(path, data, overwrite=True)
        done.append(Export(table, len(rows), paths))
    if history_copy:
        old = expired((b.name for b in container.list_blobs()), today)
        for name in old:
            container.delete_blob(name)
    return done


def snowflake_configured() -> list[str]:
    """The SNOWFLAKE_* settings still missing from the environment (empty when all are set)."""
    return [k for k in SNOWFLAKE_ENV if not os.environ.get(k)]


def connect_snowflake():
    import snowflake.connector

    missing = snowflake_configured()
    if missing:
        raise SnowflakeSyncError(f"missing in .env: {', '.join(missing)}")
    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        authenticator="SNOWFLAKE_JWT",
        private_key_file=os.environ["SNOWFLAKE_PRIVATE_KEY_PATH"],
        role=os.environ["SNOWFLAKE_ROLE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        login_timeout=30,
    )


def run_sql_file(conn, path: Path = LOAD_SQL) -> list[tuple[str, Any]]:
    """Run every statement in a .sql file in order; returns (statement start, first result row)."""
    text = path.read_text(encoding="utf-8")
    out = []
    for cur in conn.execute_string(text, remove_comments=True):
        first = cur.fetchone() if cur.description else None
        out.append((" ".join(cur.query.split())[:60], first))
    return out


KEY_PATH = ROOT / "credentials" / "snowflake_key.p8"


def make_key(path: Path = KEY_PATH) -> str:
    """Make the key pair Snowflake logs in with: the private half goes to path (git-ignored, never
    shared), the public half is returned for ALTER USER ... SET RSA_PUBLIC_KEY. Never overwrites."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    if path.exists():
        raise SnowflakeSyncError(f"{path} already exists; delete it first to make a new key")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    public = key.public_key().public_bytes(serialization.Encoding.PEM,
                                           serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return "".join(line for line in public.splitlines() if "-----" not in line)


def whoami(conn) -> dict[str, str]:
    row = conn.cursor().execute(
        "select current_account(), current_user(), current_role(), current_warehouse(), "
        "current_database(), current_region()").fetchone()
    keys = ("account", "user", "role", "warehouse", "database", "region")
    return dict(zip(keys, (str(v) for v in row)))
