"""Run dbt against the job database in Azure Postgres (Azure plan, phase 6; docs/dbt-guide.md).

    uv run python scripts/dbt.py debug              # check the connection
    uv run python scripts/dbt.py build              # build into your dev schemas
    uv run python scripts/dbt.py build --target prod
    uv run python scripts/dbt.py daily              # run_tailoring.ps1: build prod, if there's anything to build

Anything other than `daily` is passed straight to dbt. The connection comes from
JOBSEARCH_PG_URL in the git-ignored .env, split into the DBT_PG_* variables dbt/profiles.yml
reads, so no password ever sits in a tracked file. dbt runs in its own environment (dbt/pyproject.toml).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
DBT_DIR = ROOT / "dbt"
URL_ENV = "JOBSEARCH_PG_URL"


def connection_env(url: str) -> dict[str, str]:
    """The DBT_PG_* variables for a postgresql:// connection string."""
    parts = urlsplit(url)
    if parts.scheme not in ("postgres", "postgresql") or not parts.hostname:
        raise ValueError(f"{URL_ENV} isn't a postgresql://user:password@host/db URL")
    sslmode = parse_qs(parts.query).get("sslmode", ["require"])[0]
    return {
        "DBT_PG_HOST": parts.hostname,
        "DBT_PG_PORT": str(parts.port or 5432),
        "DBT_PG_USER": unquote(parts.username or ""),
        "DBT_PG_PASSWORD": unquote(parts.password or ""),
        "DBT_PG_DBNAME": unquote(parts.path.lstrip("/")) or "postgres",
        "DBT_PG_SSLMODE": sslmode,
    }


def has_work(dbt_dir: Path = DBT_DIR) -> bool:
    """Whether the project has any model or snapshot yet; before then the daily build is skipped.
    Snapshots are usually YAML since dbt 1.9, so .yml files count too."""
    return any(f.suffix in (".sql", ".yml", ".yaml")
               for d in ("models", "snapshots") for f in (dbt_dir / d).rglob("*"))


def main(argv: list[str]) -> int:
    load_dotenv(ROOT / ".env")
    url = os.environ.get(URL_ENV)
    if not url:
        print(f"{URL_ENV} isn't set (.env); dbt needs the Postgres connection string.", file=sys.stderr)
        return 2
    args = argv or ["--help"]
    if args[0] == "daily":
        if not has_work():
            print("dbt: no models or snapshots yet, nothing to build.")
            return 0
        args = ["--no-use-colors", "build", "--target", "prod"]
    env = {**os.environ, **connection_env(url), "DBT_PROFILES_DIR": str(DBT_DIR)}
    cmd = ["uv", "run", "--quiet", "--project", str(DBT_DIR), "dbt", *args]
    return subprocess.run(cmd, cwd=DBT_DIR, env=env).returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
