# Job search

Jake's job search tooling. It collects entry-level data, ML and software postings
for Vancouver and remote roles into one database, scores them, shows them on a
dashboard, and tailors a resume and cover letter for the best ones.

How a job moves through it:

1. **Collect** with `scripts/aggregate.py` (runs twice a day from Task Scheduler). Postings
   go into `jobs.db`.
2. **Score.** Every run rescores all jobs into tiers A to D (`src/score.py`, weights under
   `score:` in `config/settings.yaml`). The run also rebuilds `dashboard.html` and `export.xlsx`.
3. **Tailor.** `python -m src.tailor queue` creates one folder per job under
   `materials/applications/`. The steps in [docs/tailoring-runbook.md](docs/tailoring-runbook.md)
   then draft, check and render it. The resume and letter you send end up in that folder's `final/`.

## Setup

- [Python 3.11+](https://www.python.org/downloads/) and [uv](https://docs.astral.sh/uv/)
- `uv sync --all-groups` (includes pytest)
- Copy `.env.example` to `.env` and `config/contact.example.yaml` to `config/contact.yaml`.
- Email alerts: [docs/gmail-setup.md](docs/gmail-setup.md) or [docs/outlook-setup.md](docs/outlook-setup.md)

## Multi-source aggregator

The current job-search workflow is `scripts/aggregate.py`: Workday boards, Adzuna,
CareerJet, company boards on Greenhouse/Lever/Ashby/SmartRecruiters/Workable, and
LinkedIn/Indeed/Glassdoor **alert emails** (Gmail and/or Outlook) are normalized
into `jobs.db`, then `dashboard.html` and `export.xlsx`.

Company boards live in `config/ats_boards.yaml` (Workday tenants there are added
to `settings.yaml`'s `sources:`): Greenhouse, Lever, Ashby, SmartRecruiters,
Workable, Oracle HCM, iCIMS/Jibe, SuccessFactors, Taleo, ADP, UKG, Dayforce,
PeopleSoft, BambooHR, Pinpoint, Breezy, Rippling, Teamtailor, Jobvite, JazzHR
and Humi, plus plain custom careers pages (`html:`, e.g. PHSA). The same file
turns on whole-market feeds: Job Bank, BC Public Service and Hacker News "Who
is hiring?". These sources return the full posting, so they skip snippet
enrichment. `--skip-ats` leaves them all out.

Old postings are aged out: every run skips and deletes jobs posted more than
30 days ago (or, with no posted date, first seen that long ago), and remembers
them in a `pruned_jobs` table so they aren't scraped again. Jobs marked
`applied` are kept. Change the window with `retention: {max_age_days: N}` in
`settings.yaml`; 0 turns it off.

```bash
uv run python scripts/aggregate.py -v
uv run pytest
```

Search behaviour lives in `config/settings.yaml` (`search:`) and
`src/search_match.py`:

- **Queries** — canonical keywords, aliases (e.g. HR intern), and level terms
  (intern, co-op, new grad, …). Adzuna paginates (`max_pages`) and retries
  429/503; one failed query does not abort the source. Search snippets are
  replaced with Adzuna’s own land/ad JSON-LD when the listing is worth hydrating.
- **CareerJet** — paginates (`page` / `pages`), retries timeouts, skips 403s
  per query (no details API; snippets only).
- **Workday** — skips detail-fetches for titles that cannot match (HVAC, VP);
  one failed tenant does not abort the others. Re-runs refresh stored text.
- **Keep rules** — same phrase table on title *or* precise description phrases;
  API hits are re-checked. Senior title words and `max_years_experience` apply.
- **Location** — primary API geo is Metro Vancouver; a Canada **remote sweep**
  keeps WFH tagged in other cities. On-site Toronto/Calgary is not stored
  (`require_relevant_location`).
- **Mail** — optional; missing Gmail no longer disables Outlook. See
  [docs/gmail-setup.md](docs/gmail-setup.md) and [docs/outlook-setup.md](docs/outlook-setup.md).

Tune phrases in `src/search_match.py` (`DEFAULT_ALIASES`) or
`search.keyword_aliases` in YAML.

## Experience vault passage index

Tailored resumes and cover letters cite vault passages by id
(`algaecal.sql-daily`), so every claim can be checked against the vault.
Ids live in the vault files as Obsidian block ids at the end of each bullet,
table row or header line (`- Wrote SQL in BigQuery every day. ^sql-daily`);
the file's prefix is the `<!-- id: algaecal -->` comment on its first line.
Editing a bullet's text keeps its id. Don't reuse an id for a different fact.

```bash
# After adding new bullets to the vault: give them ids, then rebuild the index
uv run python scripts/vault_index.py --assign
# Rebuild only (fails if a passage has no id or an id is used twice)
uv run python scripts/vault_index.py
# Look up one passage
uv run python scripts/vault_index.py --show algaecal.sql-daily
```

The index is written to `materials/profile/vault-index.json` (git-ignored).
It warns when an id from the previous build disappeared, since drafts citing it
would break. Each passage is marked `use: claim`, `interview-only` (manager
feedback, departure) or `guidance` (framing rules, "do not claim" notes), and
`ai_assisted: true` for projects built mostly by Claude Code.

## Resumes

The four base resumes are YAML files in `materials/resumes/bases/`. Render one to Word and PDF
(through Word on Windows, LibreOffice elsewhere) with
`uv run python scripts/render_resume.py materials/resumes/bases/<base>.yaml`.
The format is described in [docs/resume-format.md](docs/resume-format.md).

## Folders

```
├── src/                 # Library code
│   ├── sources/         #   One adapter per job source (Workday, Adzuna, ATS boards, alert emails)
│   ├── tailor/          #   Tailoring pipeline (python -m src.tailor <step>)
│   ├── db.py, score.py, dedup.py, retention.py, dashboard.py, resume.py, ...
├── scripts/             # Command-line entry points (aggregate, rescore, render_resume, vault_index, ...)
├── prompts/tailor/      # Instructions for the Claude steps of the tailoring pipeline
├── config/              # settings.yaml (search, sources, score, tailor), ats_boards.yaml, contact.yaml
├── docs/                # Runbook, contracts, setup guides; docs/history/ has the old plans
├── tests/
├── materials/           # Personal files, git-ignored (see materials/README.md on the PC)
└── jobs.db, dashboard.html, export.xlsx   # Generated every run, git-ignored
```

`materials/` is never committed because this repo is public. It holds:

- `applications/`: one folder per tailored job
- `companies/`: company research
- `resumes/bases/`: the base resumes
- `profile/`: experience vault and screening answers
- `docs/`: tailoring rules
- `tailor/`: shared pipeline state
- `archive/`: older material
