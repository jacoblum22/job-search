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
from src.tailor.paths import load_config, resolve


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

    data = normalize(app_dir, load_config())
    # The full file is in requirements.json; print what the run needs to go on, including what was dropped.
    _out({"file": str(app_dir / "requirements.json"), "title": data.get("title"), "company": data.get("company"),
          "requirements": [{k: r.get(k) for k in ("id", "kind", "terms")}
                           for r in data.get("requirements") or [] if isinstance(r, dict)],
          **(data.get("_normalized") or {})})


@main.command("company-fetch")
@click.argument("company_dir", type=click.Path(file_okay=False, path_type=Path))
@click.argument("url")
def company_fetch(company_dir, url):
    """Step 1b: save one web page's own text as the next pages/<n>.txt."""
    from src.tailor.company import fetch_page

    _out(fetch_page(company_dir, url))


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

    ev = run_evidence(app_dir, load_config(), _jev())
    # The whole map (30 KB and more) is in evidence.json; printing it all buries the lists the run reads.
    reqs = ev.get("requirements") or []
    _out({"file": str(app_dir / "evidence.json"),
          "covered": f"{sum(r.get('status') == 'covered' for r in reqs)}/{len(reqs)}",
          "requirements": [{k: r.get(k) for k in ("id", "status", "strength", "method")} for r in reqs],
          "present": ev.get("present") or [], "absent": ev.get("absent") or [],
          "jev_said_no": len(ev.get("jev_said_no") or [])})


@main.command()
@click.argument("ids", nargs=-1, required=True)
def passages(ids):
    """Print vault passages by id (instead of searching vault-index.json)."""
    from src.tailor.sources import load_index

    index = load_index(load_config())
    _out({i: (index[i].get("text") if i in index else None) for i in ids})


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

    res = apply_edits(app_dir, rnd, load_config())
    # Before/after text of every edit is in applied.json; print only what needs attention.
    res["applied"] = [(a.get("edit") or {}).get("path") for a in res.get("applied") or []]
    res["file"] = str(app_dir / "drafts" / f"r{rnd}" / "applied.json")
    _out(res)


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

    cfg = load_config()
    _out(run_packet(app_dir, cfg))
    _refresh_dashboard(cfg)


@main.command()
@APP
def approve(app_dir):
    """Approve after every line of check.md is ticked."""
    from src.tailor.packet import approve as do_approve

    cfg = load_config()
    _out(do_approve(app_dir, cfg))
    _refresh_dashboard(cfg)


@main.command()
@APP
@click.argument("status", type=click.Choice(["applied", "callback", "interview", "offer", "rejected", "no_reply"]))
def outcome(app_dir, status):
    """Record what happened to an application."""
    from src.tailor.packet import record_outcome

    cfg = load_config()
    _out(record_outcome(app_dir, cfg, status))
    _refresh_dashboard(cfg)


def _refresh_dashboard(cfg) -> None:
    """Rebuild dashboard.html so a new application status shows without waiting for a scrape."""
    from src.dashboard import generate_dashboard
    from src.db import connect

    db = resolve(cfg, "db")
    if not db.exists():
        return
    conn = connect(db)
    try:
        generate_dashboard(conn, resolve(cfg, "dashboard"))
    finally:
        conn.close()


def run() -> None:
    # Output goes through a pipe, which Windows encodes in the ANSI code page: an arrow or an
    # em dash in a vault passage would crash the command or print as "?". The run reads UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    try:
        main(standalone_mode=True)
    except TailorError as e:
        click.echo(f"error: {e}", err=True)
        sys.exit(2)


if __name__ == "__main__":
    run()
