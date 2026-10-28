# dbt guide (Azure plan, phase 6)

dbt turns the app's raw tables in Azure Postgres into clean, tested tables that Power BI
(phase 7) reads. The plumbing is done: dbt is installed in its own environment, it connects
with the password from `.env`, and the 9:00 run builds it every day. **Every source, model,
snapshot and test in `dbt/` is yours to write.** Claude reviews each one, but doesn't write them,
so you can honestly put dbt on your resume.

## What's already set up

| Piece | Where | What it does |
| --- | --- | --- |
| dbt Core 1.12 + dbt-postgres 1.11 | `dbt/pyproject.toml` | Its own uv environment, separate from the app's. dbt v2 doesn't support Postgres, so this is v1. |
| Connection | `dbt/profiles.yml` | No secrets. `scripts/dbt.py` splits `JOBSEARCH_PG_URL` from `.env` into `DBT_PG_*` variables. |
| Targets | `dbt/profiles.yml` | `dev` (default) builds into `dbt_dev*` schemas while you work. `prod` builds `analytics*`, which Power BI will read. |
| Run command | `scripts/dbt.py` | `uv run python scripts/dbt.py <any dbt command>` |
| Daily build | `scripts/run_tailoring.ps1` | `dbt.py daily` = `dbt build --target prod` after each run, once the project has a model or snapshot (.sql or .yml). A failure is logged, never stops the run. |

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

## Lessons

Do them in order, one PR each (into `jake`), and ask Claude to review the PR. Each lesson says
what to build, not how: the "Read" links are where the how lives.

### 1. Sources

Declare the raw tables so models can say `{{ source('app', 'jobs') }}` instead of `public.jobs`.

- Do: `dbt/models/staging/_sources.yml` with the five tables above (not `score_inputs`), a
  description for each table and its key columns, and a freshness check on `jobs` (should
  warn if nothing was seen in 36 hours). Tip: freshness needs a timestamp; `loaded_at_field`
  can be an expression like `last_seen::timestamptz`.
- Check: `dbt.py source freshness` passes.
- Read: [Sources](https://docs.getdbt.com/docs/build/sources), [source freshness](https://docs.getdbt.com/docs/build/sources#source-data-freshness).

### 2. The snapshot (do this early)

A snapshot only remembers what it has seen since its first run, and the cleanup deletes
postings after 30 days. Every day before it runs is history Power BI never gets.

- Do: one snapshot of `jobs` in `dbt/snapshots/`. Decide:
  - `unique_key`: what identifies a posting?
  - `strategy`: `timestamp` on `last_seen` would write a new version every day, because every
    scrape touches it. `check` with chosen `check_cols` only records real changes. Which
    columns are real changes (title, tier, score, status, description...)? Storing a new copy
    of a long `description` on every edit costs space; your call.
  - `hard_deletes`: what should happen when the cleanup deletes a row? (`invalidate` closes
    its last version; `new_record` adds a "deleted" row.)
- Check: build it twice; the second run adds nothing. Then the snapshot's rows with
  `dbt_valid_to is null` should equal the jobs count. Note dev and prod each keep their own
  snapshot table; only the prod one (built daily) is the real history.
- Read: [Snapshots](https://docs.getdbt.com/docs/build/snapshots), [snapshot configs](https://docs.getdbt.com/reference/snapshot-configs).
- Merging this starts the daily history, so merge it before the marts.

### 3. Staging models

One `stg_` model per source table: rename, cast, clean. No joins, no business logic.

- Do: `stg_jobs`, `stg_applications`, `stg_pruned_jobs`, `stg_source_cursors` (plus
  `stg_enrich_attempts` if you want it) in `dbt/models/staging/`. Cast the text dates to real
  types, turn `ok` into a boolean, pull a few fields out of the JSON (`::jsonb ->> 'field'`).
  Keep `description` and `raw` out of `stg_jobs` unless a mart needs them.
- Set staging to `view` and marts to `table` in `dbt_project.yml` (`models:` block).
- Explore first: `select distinct status from jobs`, same for `applications.status` and
  `jobs.location_category`. You'll need the real values for tests.
- Read: [How we structure dbt projects: staging](https://docs.getdbt.com/best-practices/how-we-structure/2-staging).

### 4. Tests

- Do, in each folder's `_models.yml`: `unique` + `not_null` on keys,
  `accepted_values` on `tier` and the status/outcome columns, `relationships` from
  applications to jobs.
- Duplicate companies: the same employer shows up under two names (UBC vs University of
  British Columbia, CIBC vs Canadian Imperial Bank of Commerce), which splits counts. Make a
  seed `company_aliases.csv` (alias, canonical name) and a singular test in `dbt/tests/` that
  fails when two different company names in the data look like the same employer and aren't
  mapped yet. How you define "look like" is the interesting part.
- Read: [Data tests](https://docs.getdbt.com/docs/build/data-tests), [seeds](https://docs.getdbt.com/docs/build/seeds).

### 5. Marts

What Power BI reads. Suggested set, in `dbt/models/marts/`:

| Model | Grain | Feeds |
| --- | --- | --- |
| `dim_companies` | company (aliases merged) | everything |
| `fct_postings` | posting (one per `dedup_group_id`, not per source) | Market page |
| `fct_source_runs` or `agg_sources_daily` | source per day | Market page: sources |
| `fct_applications` | application | Funnel page |
| `fct_posting_life` | posting, from the snapshot | Posting life page: days open |
| `dim_days` | calendar day | every date axis |

- Tip: `dim_days` with `generate_series` in plain SQL, or the
  [dbt_utils](https://hub.getdbt.com/dbt-labs/dbt_utils/latest/) `date_spine` macro
  (`packages.yml`, then `dbt.py deps`).
- Skills over time needs one row per posting per skill. The app's skill matcher is in Python
  (one matcher, never a second one in SQL), so ask Claude to add a `job_skills` table the
  scrape fills; that part is plumbing.
- Check: mart counts match the dashboard (A/B counts, applications by status).
- Read: [Marts](https://docs.getdbt.com/best-practices/how-we-structure/4-marts), [ref](https://docs.getdbt.com/reference/dbt-jinja-functions/ref).

### 6. Docs

- Do: descriptions on every mart and its columns, then `dbt.py docs generate` and
  `docs serve` to see the lineage graph. A screenshot of it is good portfolio material.

## Rules

- Never commit a password: `profiles.yml` only names `env_var`s. `dbt/target/` and `dbt/logs/`
  are git-ignored.
- Never model `score_inputs`, and keep personal text (vault, letters) out of models. The repo is public.
- dbt never writes to `public`: only to its own `dbt_dev*` and `analytics*` schemas.
- Develop in `dev`; prod is what the daily run and Power BI use.
