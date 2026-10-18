"""Command line for the code steps: `uv run python -m src.tailor <command> ...`.

Each command is a thin wrapper; the work lives in the step modules. Commands
print a short JSON summary so the scheduled Claude session can read the result.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from src.tailor import TailorError
from src.tailor.paths import load_config


def _jev():
    from src.tailor.jev import JevClient

    return JevClient.from_env()


def _out(result) -> None:
    click.echo(json.dumps(result, indent=2, ensure_ascii=False, default=str))


APP = click.argument("app_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
ROUND = click.option("--round", "rnd", type=int, required=True, help="Draft round number (1, 2, 3)")


@click.group()
def main() -> None:
    """Tailoring pipeline code steps (see docs/tailoring-runbook.md)."""


@main.command()
@click.option("--limit", type=int, default=None, help="Max new application folders (default: tailor.daily_cap)")
@click.option("--job-id", type=int, multiple=True, help="Queue these jobs only (skips the tier/eligibility ordering)")
def queue(limit, job_id):
    """Step 0: pick eligible jobs, ask Jev's gate questions, create application folders."""
    from src.tailor.queue import run_queue

    cfg = load_config()
    _out([str(p) for p in run_queue(cfg, limit=limit, jev=_jev(), job_ids=list(job_id) or None)])


@main.command()
@APP
def requirements(app_dir):
    """Step 1: validate and normalize the requirements.json Claude wrote."""
    from src.tailor.requirements import normalize

    _out(normalize(app_dir, load_config()))


@main.command("company-verify")
@click.argument("company_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
def company_verify(company_dir):
    """Step 1b: check every company fact's quote against its saved page."""
    from src.tailor.company import verify_company

    _out(verify_company(company_dir))


@main.command()
@APP
def evidence(app_dir):
    """Step 2: evidence map, three buckets, PRESENT/ABSENT lists."""
    from src.tailor.evidence import run_evidence

    _out(run_evidence(app_dir, load_config(), _jev()))


@main.command()
@APP
def base(app_dir):
    """Step 3 (code part): pick the base resume and score candidate bullets."""
    from src.tailor.base import run_base

    _out(run_base(app_dir, load_config(), _jev()))


@main.command("apply-edits")
@APP
@ROUND
def apply_edits_cmd(app_dir, rnd):
    """Step 4: apply Claude's edits to the base through the gates."""
    from src.tailor.edits import apply_edits

    _out(apply_edits(app_dir, rnd, load_config()))


@main.command()
@APP
@ROUND
def check(app_dir, rnd):
    """Step 5: truth and quality checks on the resume and letter."""
    from src.tailor.checks import run_check

    _out(run_check(app_dir, rnd, load_config(), _jev()))


@main.command()
@APP
@ROUND
def grade(app_dir, rnd):
    """Step 6: ATS score + checklist judge."""
    from src.tailor.grade import run_grade

    _out(run_grade(app_dir, rnd, load_config(), _jev()))


@main.command("next-round")
@APP
def next_round_cmd(app_dir):
    """Step 7: stop, or write feedback.json for the next repair round."""
    from src.tailor.loop import next_round

    _out(next_round(app_dir, load_config()))


@main.command("humanize-flags")
@APP
def humanize_flags_cmd(app_dir):
    """Step 8a: list lines that sound AI-written."""
    from src.tailor.humanize import humanize_flags

    _out(humanize_flags(app_dir, load_config()))


@main.command("humanize-apply")
@APP
def humanize_apply_cmd(app_dir):
    """Step 8b: apply Claude's line patches with the number and style guards."""
    from src.tailor.humanize import humanize_apply

    _out(humanize_apply(app_dir, load_config()))


@main.command()
@APP
def render(app_dir):
    """Step 9: render, fit to one page, parse check."""
    from src.tailor.render import run_render

    _out(run_render(app_dir, load_config()))


@main.command()
@APP
def packet(app_dir):
    """Step 10: fit-notes.md, check.md and the status update."""
    from src.tailor.packet import run_packet

    _out(run_packet(app_dir, load_config()))


def run() -> None:
    try:
        main(standalone_mode=True)
    except TailorError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(2)


if __name__ == "__main__":
    run()
