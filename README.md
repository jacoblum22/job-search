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
uv sync
```

## Usage

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
