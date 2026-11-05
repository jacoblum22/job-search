# Snowflake guide (Azure plan, phase 9)

Snowflake is a data warehouse: a database built for analysis that runs in the cloud. Phase 9
puts a copy of the job data in a Snowflake free trial and builds the same dbt models there,
so "Snowflake" on the resume comes from real use. Postgres stays the app's database and Power
BI keeps reading Postgres; Snowflake is a second copy, rebuilt every day.

The trial lasts 30 days from sign-up (or until its free credit runs out). After that the account
is suspended: you can still log in, but nothing runs. No card is needed.

## How the data gets there

```
Postgres (the app's tables)
   |  scripts/snowflake_sync.py export, every day after the 9:00 run
   v
Azure storage container: one Parquet file per table
   |  snowflake/load.sql (Jake writes it), run by snowflake_sync.py load
   v
Snowflake database, schema RAW: one table per app table
   |  dbt build --target sf_prod
   v
Snowflake schema ANALYTICS: the same staging views and marts as Postgres
```

Parquet is a file format for tables: compact, and it remembers each column's type (whole
number, decimal, text, time). The files sit in the container like this:

| Path | What it is |
| --- | --- |
| `<table>/latest/<table>.parquet` | Today's full copy of the table, replaced every day. Load this one. |
| `<table>/history/<YYYY-MM-DD>.parquet` | That day's copy, kept 30 days. |
| `jobs_snapshot/latest/jobs_snapshot.parquet` | Written once by `export-history`: dbt's snapshot from Postgres, so the history Postgres has collected since Oct 28 2026 carries over to Snowflake. |

Tables: `jobs`, `applications`, `pruned_jobs`, `enrich_attempts`, `source_cursors`. Columns
and types are the same as in Postgres (dates are text, as they are there). `score_inputs` is
never copied.

## What's already built (Claude)

| Piece | Where | What it does |
| --- | --- | --- |
| Export | `src/snowflake_sync.py`, `scripts/snowflake_sync.py` | Reads each table from Postgres, writes Parquet, uploads it. Logs in to Azure storage as you (the Azure CLI's `az login`), so no storage key is kept anywhere. |
| Login key | `snowflake_sync.py make-key` | Makes the key file Snowflake logs in with (no password). |
| Loader | `snowflake_sync.py load` | Runs every statement in `snowflake/load.sql`, in order. |
| dbt targets | `dbt/profiles.yml` | `sf_dev` (schema `DBT_DEV`) and `sf_prod` (schema `ANALYTICS`), next to the Postgres `dev` and `prod`. |
| Models on both | `dbt/macros/cross_database.sql` | The few places Postgres and Snowflake write the same thing differently (regular expressions, time zones, JSON, a list of days). Each model calls a macro; dbt picks the version for the database it's building in. Postgres results are unchanged. |
| Sources | `dbt/models/staging/_sources.yml` | Read `public` in Postgres and `RAW` in Snowflake. |
| Daily run | `scripts/run_tailoring.ps1` | `snowflake_sync.py daily` after the Postgres dbt build: export, then load and `dbt build --target sf_prod` once those are set up. Each step is skipped until it's set up; a failure is only logged. |

## What Jake writes

| File | When it runs | What it does |
| --- | --- | --- |
| `snowflake/setup.sql` | Once, pasted into a Snowflake worksheet | The warehouse (the computer that runs queries), the database and schemas, a role and a user for the scripts, and the link to the Azure storage container. |
| `snowflake/load.sql` | Every day, by `snowflake_sync.py load` | Replaces each RAW table with the newest file. |

The lessons walk through both. Snowflake turns unquoted names into capitals (`raw.jobs` is
`RAW.JOBS`), and the dbt user needs its time zone set to UTC (`ALTER USER ... SET TIMEZONE =
'UTC'`) so dates come out the same as in Postgres.

## Setup steps (on the desktop, `C:\Users\Nelly\job-search`)

Before signing up for the trial:

1. `git pull` and `uv sync`, then `uv sync --project dbt`.
2. Make the storage account and container (any name of 3 to 24 lowercase letters and digits,
   unique across Azure), and give yourself permission to write files into it:

   ```powershell
   $acct = "jobsearchlake<something>"
   az storage account create -n $acct -g rg-job-search -l canadacentral --sku Standard_LRS --kind StorageV2 --allow-blob-public-access false --min-tls-version TLS1_2
   az storage container create --account-name $acct -n snowflake --auth-mode login
   $me = az ad signed-in-user show --query id -o tsv
   $scope = az storage account show -n $acct -g rg-job-search --query id -o tsv
   az role assignment create --assignee $me --role "Storage Blob Data Contributor" --scope $scope
   Add-Content .env "`nJOBSEARCH_BLOB_URL=https://$acct.blob.core.windows.net/snowflake"
   ```

   The permission can take a few minutes to start working.
3. `uv run python scripts/snowflake_sync.py export`, then `export-history`. Check the files in
   the Azure portal: Storage accounts > your account > Containers > snowflake.

After signing up (pick Microsoft Azure, region Canada Central, the same as the rest):

4. `uv run python scripts/snowflake_sync.py make-key` and add the line it prints to `.env`.
5. Write and run `snowflake/setup.sql` (lessons), then add to `.env`:

   ```
   SNOWFLAKE_ACCOUNT=<orgname>-<accountname>
   SNOWFLAKE_USER=...
   SNOWFLAKE_ROLE=...
   SNOWFLAKE_WAREHOUSE=...
   SNOWFLAKE_DATABASE=...
   SNOWFLAKE_PRIVATE_KEY_PATH=C:\Users\Nelly\job-search\credentials\snowflake_key.p8
   ```

6. `uv run python scripts/snowflake_sync.py check` (shows the account, role and warehouse).
7. Write `snowflake/load.sql`, then `snowflake_sync.py load`.
8. `uv run python scripts/dbt.py build --target sf_dev`, then `--target sf_prod`.

From then on the 9:00 run keeps Snowflake current. When the trial ends, take
`JOBSEARCH_BLOB_URL` out of `.env` to stop the daily step.

## Rules

- Never commit the key file (`*.p8` is git-ignored) or anything from `.env`.
- The container stays private (`--allow-blob-public-access false`): it holds application outcomes.
- Keep the warehouse X-Small with auto-suspend on, so the free credit lasts the whole trial.
