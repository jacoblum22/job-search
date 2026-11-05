"""Re-score every job in jobs.db and rebuild the dashboard, without scraping.

Use after editing the `score:` weights in config/settings.yaml:

    uv run python scripts/rescore.py            # rescore + rebuild dashboard
    uv run python scripts/rescore.py --top 25   # also print the best 25
"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.dashboard import generate_dashboard  # noqa: E402
from src.db import connect, grouped_jobs  # noqa: E402
from src.score import rescore_all  # noqa: E402


@click.command()
@click.option("--config", "config_path", type=click.Path(exists=True, path_type=Path),
              default=PROJECT_ROOT / "config" / "settings.yaml")
@click.option("--db", "db_path", type=click.Path(path_type=Path), default=PROJECT_ROOT / "jobs.db")
@click.option("--dashboard", "dashboard_path", type=click.Path(path_type=Path),
              default=PROJECT_ROOT / "dashboard.html")
@click.option("--top", type=int, default=15, help="How many top-scored jobs to print")
def main(config_path: Path, db_path: Path, dashboard_path: Path, top: int) -> None:
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    conn = connect(db_path)
    counts = rescore_all(conn, cfg.get("score", {}))
    click.echo("Rows per tier: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    groups = [g for g in grouped_jobs(conn) if g["score"] is not None and g["status"] == "new"]
    groups.sort(key=lambda g: g["score"], reverse=True)
    for g in groups[:top]:
        click.echo(f"{g['score']:>4}  {g['tier']}  {g['title']} | {g['company']}")
        click.echo(f"         {g['score_reasons']}")

    generate_dashboard(conn, dashboard_path)
    conn.close()
    click.echo(f"Dashboard: {dashboard_path}")


if __name__ == "__main__":
    main()
