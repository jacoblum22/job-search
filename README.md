# UBC Job Scraper

Automated scraper for UBC's Workday staff job board. Fetches job postings via the Workday REST API, classifies them into fit tiers, and stores structured Markdown files to streamline the job application process.

## Setup

### Prerequisites

- [Python 3.11+](https://www.python.org/downloads/)
- [uv](https://docs.astral.sh/uv/) (fast Python package manager)

### Installation

```bash
# Clone the repository
git clone <repo-url> && cd <repo-dir>

# Create a virtual environment and install dependencies
uv sync --all-groups   # includes pytest
```

## Multi-source aggregator

The current job-search workflow is `scripts/aggregate.py`: Workday boards, Adzuna,
CareerJet, company boards on Greenhouse/Lever/Ashby/SmartRecruiters/Workable, and
LinkedIn/Indeed/Glassdoor **alert emails** (Gmail and/or Outlook) are normalized
into `jobs.db`, then `dashboard.html` and `export.xlsx`.

Company boards live in `config/ats_boards.yaml` (Workday tenants there are added
to `settings.yaml`'s `sources:`). The five public ATS feeds return the full
posting, so those jobs skip snippet enrichment. `--skip-ats` leaves them out.

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
  `GMAIL_SETUP.md` and `OUTLOOK_SETUP.md`.

Tune phrases in `src/search_match.py` (`DEFAULT_ALIASES`) or
`search.keyword_aliases` in YAML.

## Usage (legacy UBC markdown scrape)

```bash
# Scrape all current UBC staff job listings
uv run python scripts/scrape.py

# Preview jobs without writing files
uv run python scripts/scrape.py --dry-run

# Limit the number of jobs scraped
uv run python scripts/scrape.py --limit 50

# Convert cover letter markdown to Word/PDF
uv run python scripts/export.py
```

New job descriptions appear in `job_descriptions/` as `.md` files with YAML frontmatter, prefixed by tier (e.g. `A-high-JR23613-programmer-analyst-i.md`).

## Project Structure

```
├── profile/              # Personal documents (resume, cover letter template, etc.)
├── job_descriptions/     # Scraped job descriptions (.md with YAML frontmatter)
├── cover_letters/        # Tailored cover letters
│   ├── markdown/         #   Source markdown files
│   ├── docx/             #   Generated Word documents
│   └── pdf/              #   Generated PDFs
├── src/                  # Source code
│   ├── scraper.py        #   Workday API client (sync + async)
│   ├── parser.py         #   HTML → Markdown conversion & field extraction
│   ├── tier.py           #   Job fit classification (HIGH → LOW)
│   └── writer.py         #   Markdown file generation with frontmatter
├── scripts/              # CLI entry points
│   ├── scrape.py         #   Job scraper CLI
│   └── export.py         #   Cover letter DOCX/PDF exporter
├── config/
│   └── settings.yaml     # Tier classification keywords & scraper settings
├── pyproject.toml        # Project metadata & dependencies
└── PLAN.md               # Detailed project plan
```

## Tier Classification

Jobs are automatically classified into four tiers based on title, description, location, and experience requirements:

| Tier | Prefix | Meaning |
|------|--------|---------|
| HIGH | `A-high` | Strong match — tech, data, research roles with relevant skills |
| MID-HIGH | `B-midhigh` | Good secondary fit — education, easy entry-level roles |
| MID | `C-mid` | Neutral — worth a quick glance |
| LOW | `D-low` | Wrong fit — too senior, wrong field, too far, etc. |

Tier keywords and thresholds are fully configurable in `config/settings.yaml`.

## Workflow

1. Run `uv run python scripts/scrape.py` to fetch current UBC staff job listings
2. Review new jobs in `job_descriptions/` (sorted by tier prefix)
3. Draft tailored cover letters in `cover_letters/markdown/`
4. Run `uv run python scripts/export.py` to generate DOCX and PDF versions
5. Apply on Workday with the tailored cover letter

## Configuration

Edit `config/settings.yaml` to adjust:

- Tier classification keywords (high, mid-high, low title/description keywords)
- Location exclusion keywords
- Experience year filter threshold
