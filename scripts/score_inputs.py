"""Copy the scoring files (experience vault index, skill record) into the shared Postgres
database, so the Azure scrape job scores jobs the way the desktop does (src/score_inputs.py,
docs/azure-scrape-job.md).

    uv run python scripts/score_inputs.py push     # desktop: save changed files to Postgres
    uv run python scripts/score_inputs.py status   # what Postgres holds, and when it was saved

run_tailoring.ps1 pushes after every run, and a desktop scrape pushes too.
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src import score_inputs  # noqa: E402
from src.db import MAIN_DB, backend, connect  # noqa: E402


@click.command()
@click.argument("action", type=click.Choice(["push", "status"]), default="push")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=ROOT / "config" / "settings.yaml")
def main(action: str, config_path: Path) -> None:
    load_dotenv(ROOT / ".env")
    if backend() != "postgres":
        click.echo("The main database is jobs.db (JOBSEARCH_DB isn't postgres); nothing to share.")
        return
    score_cfg = (yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}).get("score")
    conn = connect(MAIN_DB)
    try:
        if action == "push":
            if not score_inputs.ready(score_cfg):
                raise click.ClickException("The vault index isn't here (settings.yaml score.vault_gaps.index)")
            changed = score_inputs.push(conn, score_cfg)
            click.echo(f"Saved {', '.join(changed)}" if changed else "Postgres already has the current files.")
        else:
            conn.executescript(score_inputs.SCHEMA)
            rows = conn.execute("SELECT name, updated_at, length(body) FROM score_inputs ORDER BY name").fetchall()
            for name, at, size in rows:
                click.echo(f"  {name:<45} {size:>8} chars  saved {at}")
            if not rows:
                click.echo("Postgres holds no scoring files yet.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
