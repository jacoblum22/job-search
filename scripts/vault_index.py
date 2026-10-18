"""Build the passage index for the experience vault.

Every bullet, table row, header field and paragraph in the vault gets a stable id
(``algaecal.sql-daily``) stored in the vault file as an Obsidian block id. The
index is a git-ignored JSON file the tailoring pipeline reads to cite and check
claims.

    uv run python scripts/vault_index.py            # check ids, write the index
    uv run python scripts/vault_index.py --assign   # first add ids to new passages
    uv run python scripts/vault_index.py --show algaecal.sql-daily
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import click

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.vault import assign_ids, build_index, to_json, vault_files  # noqa: E402

DEFAULT_VAULT = PROJECT_ROOT / "materials" / "profile" / "experience-vault"
DEFAULT_OUT = PROJECT_ROOT / "materials" / "profile" / "vault-index.json"


@click.command()
@click.option("--vault", type=click.Path(exists=True, file_okay=False, path_type=Path), default=DEFAULT_VAULT)
@click.option("--out", type=click.Path(path_type=Path), default=DEFAULT_OUT)
@click.option("--assign", is_flag=True, help="Add ids to passages that don't have one (edits the vault files)")
@click.option("--check", is_flag=True, help="Only report problems; don't write the index")
@click.option("--show", "show_id", help="Print one passage by id")
def main(vault: Path, out: Path, assign: bool, check: bool, show_id: str | None) -> None:
    if assign:
        for path in vault_files(vault):
            added = assign_ids(path)
            if added:
                click.echo(f"{path.relative_to(vault)}: added {len(added)} ids")

    passages, problems = build_index(vault)
    if show_id:
        match = [p for p in passages if p.id == show_id]
        click.echo(json.dumps(to_json(match), indent=2, ensure_ascii=False) if match else f"No passage {show_id}")
        return

    for problem in problems:
        click.echo(f"PROBLEM {problem}", err=True)

    # Ids that disappeared since the last build would break citations in drafts.
    if out.exists():
        old = {p["id"] for p in json.loads(out.read_text(encoding="utf-8"))["passages"]}
        gone = sorted(old - {p.id for p in passages})
        for pid in gone:
            click.echo(f"REMOVED {pid} (was in the last index)", err=True)

    files = len({p.file for p in passages})
    click.echo(f"{len(passages)} passages in {files} files, {len(problems)} problems")
    if problems:
        click.echo("Run with --assign to add missing ids; fix duplicates by hand.", err=True)
        sys.exit(1)
    if check:
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "vault": str(vault),
        "passages": to_json(passages),
    }
    out.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    click.echo(f"Wrote {out}")


if __name__ == "__main__":
    main()
