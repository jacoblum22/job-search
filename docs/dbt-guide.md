# dbt guide (Azure plan, phase 6)

dbt turns the app's raw tables in Azure Postgres into clean, tested tables that Power BI
(phase 7) reads. The plumbing is done: dbt is installed in its own environment, it connects
with the password from `.env`, and the 9:00 run builds it every day. 

## What's already set up

| Piece | Where | What it does |
| --- | --- | --- |
| dbt Core 1.12 + dbt-postgres 1.11 | `dbt/pyproject.toml` | Its own uv environment, separate from the app's. dbt v2 doesn't support Postgres, so this is v1. |
| Connection | `dbt/profiles.yml` | No secrets. `scripts/dbt.py` splits `JOBSEARCH_PG_URL` from `.env` into `DBT_PG_*` variables. |
| Targets | `dbt/profiles.yml` | `dev` (default) builds into `dbt_dev*` schemas while you work. `prod` builds `analytics*`, which Power BI will read. |
| Run command | `scripts/dbt.py` | `uv run python scripts/dbt.py <any dbt command>` |
| Daily build | `scripts/run_tailoring.ps1` | `dbt.py daily` = `dbt build --target prod` after each run, (skipped only while the project is empty). A failure is logged, never stops the run. |
| Snowflake (phase 9) | `dbt/profiles.yml`, `dbt/macros/cross_database.sql` | Targets `sf_dev` / `sf_prod` build the same models in Snowflake. Where the two databases write SQL differently, models call a macro from `cross_database.sql`. See `docs/snowflake-guide.md`. |

Run everything from `C:\Users\Nelly\job-search`:

```powershell
uv run python scripts/dbt.py debug                 # connection check: "All checks passed!"
uv run python scripts/dbt.py build                 # build + test everything in dev
uv run python scripts/dbt.py build -s stg_jobs     # just one model
uv run python scripts/dbt.py build --target prod   # what the daily run does
uv run python scripts/dbt.py docs generate; uv run python scripts/dbt.py docs serve
```

dbt's own log is `dbt/logs/dbt.log`. The SQL it actually ran is in `dbt/target/run/`.

## The raw tables

These are in the `public` schema of database `jobsearch`. They're the app's tables: dbt only reads them.

| Table | One row per | Notes |
| --- | --- | --- |
| `jobs` | posting from one source | Key `id`. The same job on two boards shares a `dedup_group_id`. Dates (`first_seen`, `last_seen`, `posted_date`) are **text** (ISO strings), and `raw` is JSON as text. `tier` is A, B, C, D or skip. Deleted 30 days after its posted date (else `first_seen`), or when the posting expires, unless it has an application. |
| `pruned_jobs` | deleted posting | Tombstone: `source`, `external_id`, `pruned_at`. Only the key survives, which is why you need a snapshot. |
| `applications` | tailored packet | Key `job_id` (joins `jobs.id`). `status` is the packet's state, `outcome` is applied, callback, interview, offer, rejected or no_reply. |
| `enrich_attempts` | try at fetching a full description | `ok` is 0 or 1. |
| `source_cursors` | key/value | `aggregate:last_run` holds the last scrape's summary as JSON (per-source counts, host, duration). |
| `score_inputs` | **never model this** | Your personal vault files, stored for the Azure scrape. Leave it out of `sources.yml`. |

## What's built

Jake wrote the sources and the snapshot. Claude wrote staging, the tests and the marts at Jake's request.

| Layer | Files | What it is |
| --- | --- | --- |
| Sources | `models/staging/_sources.yml` | The app's five tables in `public` (never `score_inputs`), with a freshness check on `jobs`. |
| Snapshot | `snapshots/jobs_snapshot.yml` | Every version of every job, kept after the cleanup deletes it. Prod history starts Oct 28 2026. |
| Staging (views) | `models/staging/stg_app__*.sql` | One per table: renamed, text dates as real dates, enrich codes named, scrape summary JSON split out, company names trimmed. |
| Seeds | `seeds/company_aliases.csv`, `seeds/company_not_duplicates.csv` | Alternate employer names mapped to one name; look-alikes that are really different employers. |
| Tests | `_stg_app__models.yml`, `_marts__models.yml`, `_seeds.yml`, `tests/` | Keys unique and present, allowed values, applications point at real jobs. `assert_company_names_unique` (warn) lists look-alike employer names not yet in the seed. |
| Marts (tables) | `models/marts/` | What Power BI reads, below. |

| Mart | One row per | Power BI page |
| --- | --- | --- |
| `fct_postings` | posting open today, the same job on several boards merged | Market |
| `fct_posting_life` | board copy of a posting ever snapshotted, open or deleted | Posting life (days listed) |
| `agg_postings_daily` | day, board and tier: new postings | Market: sources over time |
| `fct_applications` | tailored packet, with cumulative funnel steps | Funnel |
| `dim_companies` | employer (aliases merged) | every page |
| `dim_days` | calendar day | every date axis |

Power BI reads the prod schema `analytics`, which the 9:00 run rebuilds. Descriptions for every
mart column are in `_marts__models.yml`; `dbt.py docs generate` then `dbt.py docs serve` shows them
with the lineage graph.

When the duplicate-company check warns: a real duplicate gets a row in `company_aliases.csv`
(subsidiaries map to the parent brand), two different employers get a row in
`company_not_duplicates.csv`.

Not built yet: skills over time needs a `job_skills` table the scrape fills from the app's one
skill matcher (Python, never a SQL copy). Deadlines and "closed" postings are also worked out in
Python, so they aren't in the marts.

## Rules

- Never commit a password: `profiles.yml` only names `env_var`s. `dbt/target/` and `dbt/logs/`
  are git-ignored.
- Never model `score_inputs`, and keep personal text (vault, letters) out of models. The repo is public.
- dbt never writes to `public`: only to its own `dbt_dev*` and `analytics*` schemas.
- Develop in `dev`; prod is what the daily run and Power BI use.
