"""A read-only Postgres login for Power BI (Azure plan, phase 7; docs/power-bi-guide.md).

    uv run python scripts/powerbi_login.py create   # make the login (or give it a new password)
    uv run python scripts/powerbi_login.py check    # show what it can and can't read

The login, powerbi_reader, can only read the schema dbt's prod build writes (analytics). It can't
change anything and can't see the app's own tables in public, so score_inputs (personal vault
files) stays out of reach. Power BI asks for the password once and keeps it in Windows; it is
printed here once and never written to a file.

Runs as the admin login in JOBSEARCH_PG_URL (.env). dbt rebuilds the analytics tables every day
as that same login, and the default privileges set here give each rebuilt table to the reader too.
"""

from __future__ import annotations

import secrets
import sys
from pathlib import Path

import click
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import pg_mirror

READER = "powerbi_reader"
SCHEMA = "analytics"
# Tables the reader must never see; check fails if it can.
PRIVATE = ("public.score_inputs", "public.jobs", "public.applications")


def grant_sql(reader: str = READER, schema: str = SCHEMA) -> list[str]:
    """Everything the reader is given: connect, look inside analytics, read what's there now and
    whatever dbt (running as the admin login) creates there later."""
    return [
        f'GRANT CONNECT ON DATABASE "{{db}}" TO {reader}',
        f"GRANT USAGE ON SCHEMA {schema} TO {reader}",
        f"GRANT SELECT ON ALL TABLES IN SCHEMA {schema} TO {reader}",
        f"ALTER DEFAULT PRIVILEGES IN SCHEMA {schema} GRANT SELECT ON TABLES TO {reader}",
    ]


def _connect():
    load_dotenv(ROOT / ".env")
    try:
        return pg_mirror.connect_pg()
    except Exception as e:  # noqa: BLE001 - reported plainly
        click.echo(f"Couldn't connect to Postgres: {e}", err=True)
        raise SystemExit(1) from None


def _create(pg) -> str:
    from psycopg import sql

    password = secrets.token_urlsafe(24)
    with pg.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (READER,))
        verb = "ALTER" if cur.fetchone() else "CREATE"
        cur.execute(sql.SQL(verb + " ROLE {} LOGIN PASSWORD {}").format(
            sql.Identifier(READER), sql.Literal(password)))
        cur.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        cur.execute("SELECT current_database()")
        db = cur.fetchone()[0]
        for stmt in grant_sql():
            cur.execute(stmt.replace("{db}", db))
    pg.commit()
    return password


def _check(pg) -> bool:
    ok = True
    with pg.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (READER,))
        if not cur.fetchone():
            click.echo(f"{READER} doesn't exist yet; run `create`.")
            return False
        cur.execute(
            "SELECT table_name, has_table_privilege(%s, format('%%I.%%I', table_schema, table_name), 'SELECT')"
            " FROM information_schema.tables WHERE table_schema = %s ORDER BY table_name",
            (READER, SCHEMA))
        rows = cur.fetchall()
        click.echo(f"Can read in {SCHEMA}:")
        for name, can in rows:
            click.echo(f"  {'yes' if can else 'NO '}  {name}")
            ok &= can
        if not rows:
            click.echo("  (nothing there yet; run dbt's prod build first)")
        click.echo("Must not read:")
        for table in PRIVATE:
            cur.execute("SELECT to_regclass(%s) IS NOT NULL", (table,))
            if not cur.fetchone()[0]:
                continue
            cur.execute("SELECT has_table_privilege(%s, %s, 'SELECT')", (READER, table))
            can = cur.fetchone()[0]
            click.echo(f"  {'CAN READ (wrong)' if can else 'blocked'}  {table}")
            ok &= not can
    return ok


@click.command()
@click.argument("action", type=click.Choice(["create", "check"]))
def main(action: str) -> None:
    pg = _connect()
    try:
        if action == "create":
            password = _create(pg)
            click.echo(f"Login: {READER}\nPassword (shown once; paste it into Power BI): {password}")
        ok = _check(pg)
    finally:
        pg.close()
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
