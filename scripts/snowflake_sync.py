"""Copy the job data to Snowflake and build the dbt models there (Azure plan, phase 9).

    uv run python scripts/snowflake_sync.py export           # Postgres tables -> Parquet files in Azure storage
    uv run python scripts/snowflake_sync.py export-history   # once: the dbt snapshot, so history carries over
    uv run python scripts/snowflake_sync.py make-key         # once: the key file Snowflake logs in with
    uv run python scripts/snowflake_sync.py check            # log in to Snowflake and say who you are
    uv run python scripts/snowflake_sync.py load             # run snowflake/load.sql (RAW tables <- newest files)
    uv run python scripts/snowflake_sync.py daily            # run_tailoring.ps1: export, load, dbt build --target sf_prod

`daily` does only the steps that are set up: nothing without JOBSEARCH_BLOB_URL in .env, just the
export until the SNOWFLAKE_* settings and snowflake/load.sql exist. Take JOBSEARCH_BLOB_URL out of
.env to turn the whole thing off (for example when the Snowflake trial ends).
See docs/snowflake-guide.md.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import pg_mirror, snowflake_sync as sf


def _pg():
    try:
        return pg_mirror.connect_pg()
    except Exception as e:  # noqa: BLE001 - reported plainly
        raise click.ClickException(f"couldn't connect to Postgres: {e}") from None


def _export(tables, history_copy=True) -> None:
    pg = _pg()
    try:
        container = sf.container_client()
        for e in sf.export(pg, container, tables, history_copy=history_copy):
            click.echo(f"exported {e.table}: {e.rows} rows -> {', '.join(e.paths)}")
    except sf.SnowflakeSyncError as e:
        raise click.ClickException(str(e)) from None
    finally:
        pg.close()


def _load() -> int:
    """Run load.sql; returns how many rows RAW.JOBS has afterwards."""
    if not sf.LOAD_SQL.exists():
        raise click.ClickException(f"{sf.LOAD_SQL.relative_to(ROOT)} doesn't exist yet")
    try:
        conn = sf.connect_snowflake()
    except sf.SnowflakeSyncError as e:
        raise click.ClickException(str(e)) from None
    try:
        for statement, first in sf.run_sql_file(conn):
            click.echo(f"{statement} -> {first}" if first is not None else statement)
        jobs = conn.cursor().execute("select count(*) from raw.jobs").fetchone()[0]
        click.echo(f"RAW.JOBS now has {jobs} rows")
        return jobs
    finally:
        conn.close()


@click.group()
def cli() -> None:
    load_dotenv(ROOT / ".env")


@cli.command()
def export() -> None:
    """Write the app's tables to Azure storage as Parquet."""
    _export(sf.TABLES)


@cli.command("export-history")
def export_history() -> None:
    """Write dbt's prod snapshot (analytics.jobs_snapshot) once, for loading into Snowflake."""
    _export([sf.HISTORY_TABLE], history_copy=False)


@cli.command("make-key")
def make_key() -> None:
    """Make the Snowflake login key (credentials/snowflake_key.p8) and print its public half."""
    try:
        public = sf.make_key()
    except sf.SnowflakeSyncError as e:
        raise click.ClickException(str(e)) from None
    click.echo(f"Private key saved to {sf.KEY_PATH} (git-ignored; never share it).")
    click.echo(f"Add to .env:  SNOWFLAKE_PRIVATE_KEY_PATH={sf.KEY_PATH}")
    click.echo("Public key, for ALTER USER ... SET RSA_PUBLIC_KEY = '<this>':")
    click.echo(public)


@cli.command()
def check() -> None:
    """Log in to Snowflake with the key file and show the account, role and warehouse."""
    try:
        conn = sf.connect_snowflake()
    except sf.SnowflakeSyncError as e:
        raise click.ClickException(str(e)) from None
    try:
        for k, v in sf.whoami(conn).items():
            click.echo(f"{k:>10}: {v}")
    finally:
        conn.close()


@cli.command()
def load() -> None:
    """Run snowflake/load.sql: replace the RAW tables with the newest files."""
    _load()


@cli.command()
def daily() -> None:
    """Export, load, then build the dbt models in Snowflake; skips whatever isn't set up yet."""
    if not os.environ.get(sf.BLOB_URL_ENV):
        click.echo(f"Snowflake: {sf.BLOB_URL_ENV} not set, skipped.")
        return
    _export(sf.TABLES)
    missing = sf.snowflake_configured()
    if missing or not sf.LOAD_SQL.exists():
        click.echo("Snowflake: export done; load and dbt skipped until the SNOWFLAKE_* settings "
                   "and snowflake/load.sql exist.")
        return
    if not _load():
        # An empty jobs table would make the snapshot mark every posting as removed.
        raise click.ClickException("RAW.JOBS is empty after the load; dbt build skipped")
    code = subprocess.run([sys.executable, str(ROOT / "scripts" / "dbt.py"),
                           "--no-use-colors", "build", "--target", "sf_prod"]).returncode
    if code:
        raise click.ClickException(f"dbt build in Snowflake failed (exit {code}); see dbt/logs/dbt.log")


if __name__ == "__main__":
    cli()
