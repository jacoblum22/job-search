# Architecture & Design Decisions

Notes on key design decisions and the reasoning behind them.

## Scraping Approach

The UBC Workday site is a JavaScript SPA, so browser automation (Playwright) was the initial plan. However, we discovered its underlying REST API:

- **`POST /wday/cxs/{tenant}/{site}/jobs`** — paginated job listings (20 per page)
- **`GET /wday/cxs/{tenant}/{site}/job/{path}`** — full job details (HTML description, metadata)

These endpoints are publicly accessible with no authentication or anti-bot measures, so we use direct HTTP calls via `httpx` — no browser automation needed. This is ~100× faster and avoids the ~150 MB Playwright browser download.

## Multi-Source Architecture

The same Workday CXS API pattern works for **every** organisation running Workday — only the `tenant`, `wd` instance number, and `site` identifiers change. The scraper accepts these as constructor parameters and the CLI loops through all enabled sources defined in `config/settings.yaml`.

Current Vancouver-area sources:

| Source | Tenant | Jobs |
|--------|--------|------|
| UBC | `ubc.wd10` / `ubcstaffjobs` | ~190 |
| City of Vancouver | `cityofvancouver.wd5` / `COV` | ~17 |
| TRIUMF | `triumf.wd10` / `careers-at-triumf-job-postings` | ~20 |
| BCI | `bci.wd10` / `BCI_Careers` | ~9 |
| BCAA | `bcaa.wd3` / `bcaacareers` | ~46 |
| TELUS International | `telusinternational.wd3` / `External` | ~52 |

Large global employers (Salesforce, NVIDIA, Autodesk, Activision Blizzard) are configured but disabled by default because they list thousands of jobs worldwide. They should be enabled once location-based filtering is added.

The `--source` CLI flag allows scraping a single source by name (e.g. `--source UBC`).

Each job's metadata includes a `source` field for traceability.

## Tier Classification

Rather than reading every job manually, an automated tier system classifies postings into four buckets: **HIGH**, **MID-HIGH**, **MID**, and **LOW**. This is a purely keyword-based heuristic (no LLM inference) for speed and predictability.

Classification order matters — earlier checks take priority:

1. **Location exclusion** → LOW (too far from Vancouver)
2. **Experience requirements** (>5 years) → LOW
3. **Title/category exclusion keywords** → LOW (trades, clinical, senior leadership)
4. **Description exclusion keywords** (≥2 matches) → LOW (wet-lab/bench science)
5. **Title match for priority keywords** → HIGH (data, research, software, etc.)
6. **Description match** (≥2 skill keywords) → HIGH
7. **Title match for mid-high keywords** → MID-HIGH (education, children, etc.)
8. **Default** → MID

The description exclusion check (step 4) intentionally runs *before* the HIGH checks so that a "Research Assistant" role requiring wet-lab skills gets correctly demoted despite the title match.

All keywords are configured in `config/settings.yaml`, not hardcoded.

## File Format

Job descriptions are stored as markdown with YAML frontmatter. This format:

- Is human-readable and diffable
- Works natively with most editors and tools
- Allows structured metadata queries (tier, status, date)
- Sorts alphabetically by tier prefix (`A-high` > `B-midhigh` > `C-mid` > `D-low`)

## Cover Letter Export Pipeline

The export process is two-step:

1. **Markdown → DOCX** via `python-docx` (cross-platform)
2. **DOCX → PDF** via Word COM automation (Windows only, falls back gracefully)

Using a single persistent Word COM instance for PDF conversion avoids the startup cost per file that `docx2pdf` incurs.

## Future Enhancements

- Non-Workday sources (Greenhouse API, government job boards)
- Location-based filtering for large global employers
- Job-resume match scoring (LLM-based fit assessment)
- Application status tracker
- Resume variant generator (emphasise different skills per job)
