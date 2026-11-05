# Job database in Azure Postgres (Azure plan, phases 3 and 4)

Phase 3 keeps a shadow copy of jobs.db in Azure Database for PostgreSQL; nothing reads
it. Phase 4 makes Postgres the main database: every task and the dashboard read and
write it, and a daily SQLite backup lands in `backups/`. Code: `src/pg_mirror.py`
(the mirror), `src/pg_cutover.py` (cutover, backup, rollback), `src/pgdb.py` (Postgres
behind the sqlite3 calls the code makes), `scripts/pg_mirror.py` (all commands).
Phase 4 is described [below](#phase-4-postgres-as-the-main-database).
Phase 5 (the scrape as an Azure job that writes this database) is in
[azure-scrape-job.md](azure-scrape-job.md).

## What it does

- `sync` reads jobs.db read-only, in one snapshot, and makes every table in Postgres
  match it: new rows inserted, changed rows updated, rows gone from jobs.db (retention,
  expired postings) deleted. All tables change in one transaction, or none do.
- Tables and columns come from jobs.db, so a column added later reaches Postgres on the
  next sync. Postgres types follow SQLite's own type rules (INTEGER to BIGINT, TEXT to
  TEXT, REAL to DOUBLE PRECISION). Each Postgres row has a `_row_hash` column, which is
  how a sync knows what changed and how `check` compares the two.
- `check` prints row counts per table on both sides and how many rows differ.
- Both append a line to `logs/pg-mirror.jsonl`; `history` prints them.
- `run_tailoring.ps1` runs `sync --if-enabled` after each daily run. It does nothing
  until `database.postgres_mirror` is `true` in settings.yaml, and a failure is only a
  warning in `logs/tailoring.log`.

## One-time setup on the desktop

Normal PowerShell in `C:\Users\Nelly\job-search` (Azure CLI is signed in).

1. Create the server. Burstable B1ms with 32 GB is inside the 12-month free tier
   (750 hours of B1ms, 32 GB storage, 32 GB backup). High availability, geo-redundant
   backup and storage auto-grow are off by default and are left off, so it can't grow
   past the free amounts. Takes about 10 minutes.

   ```powershell
   # a new subscription has to register the Postgres provider once (MissingSubscriptionRegistration)
   az provider register --namespace Microsoft.DBforPostgreSQL --wait
   $ip = (Invoke-RestMethod https://api.ipify.org)
   $bytes = New-Object byte[] 24
   [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
   $pw = ([Convert]::ToBase64String($bytes) -replace '[+/=]', '') + 'Aa1'
   # $null =: az prints the admin password in its result, so keep it off the screen
   $null = az postgres flexible-server create `
     --resource-group rg-job-search --name jobsearch-pg-jake --location canadacentral `
     --tier Burstable --sku-name Standard_B1ms --storage-size 32 --version 16 `
     --admin-user jobsearch_admin --admin-password $pw `
     --public-access $ip --yes
   ```

   `--public-access $ip` makes the only firewall rule this computer's public IP. If the
   name `jobsearch-pg-jake` is taken (names are global), pick another and use it below.

2. Check it came out as planned (expect Standard_B1ms, Burstable, 32, Disabled, Disabled,
   Disabled, Ready):

   ```powershell
   az postgres flexible-server show -g rg-job-search -n jobsearch-pg-jake `
     --query "{sku:sku.name, tier:sku.tier, storageGb:storage.storageSizeGb, autoGrow:storage.autoGrow, ha:highAvailability.mode, geoBackup:backup.geoRedundantBackup, state:state}" -o table
   ```

3. Make the database and save the connection string to `.env` (git-ignored; the
   password never goes anywhere else). In the same window, so `$pw` is still set:

   ```powershell
   az postgres flexible-server db create -g rg-job-search --server-name jobsearch-pg-jake --name jobsearch
   Add-Content .env "`nJOBSEARCH_PG_URL=postgresql://jobsearch_admin:$pw@jobsearch-pg-jake.postgres.database.azure.com:5432/jobsearch?sslmode=require"
   ```

   Azure refuses connections without TLS, and `sslmode=require` encrypts every
   connection.

4. First copy, then check:

   ```powershell
   uv sync
   uv run python scripts/pg_mirror.py sync
   ```

   It prints rows per table and ends with "All tables match." Exit code 2 means a table
   differs; 1 means it couldn't connect or a value didn't fit (the message names the
   table, row and column).

5. Turn on the daily sync: `postgres_mirror: true` under `database:` in
   `config/settings.yaml` (on since Oct 28 2026; jobsearch-pg-jake, firewall 75.157.102.114).

## Over the week

`uv run python scripts/pg_mirror.py history` shows each day's sync and check. Phase 3
is done after seven days of `match`. Run `check` any time without changing anything.

## Firewall

Only addresses with a rule can connect. The desktop's IP is added at creation. To add
another (a laptop, or a new home IP):

```powershell
az postgres flexible-server firewall-rule create -g rg-job-search --server-name jobsearch-pg-jake `
  --name laptop --start-ip-address 203.0.113.7 --end-ip-address 203.0.113.7
az postgres flexible-server firewall-rule list -g rg-job-search --server-name jobsearch-pg-jake -o table
```

If the desktop's own IP changes, the sync logs "Couldn't connect"; add the new IP the
same way.

## Rollback (phase 3)

Set `postgres_mirror: false`. Nothing reads Postgres, so nothing else changes. To stop
paying anything after the free year, `az postgres flexible-server stop` (it restarts
itself after 7 days) or delete the server.

## Phase 4: Postgres as the main database

### How the switch works

- `JOBSEARCH_DB=postgres` in `.env` is the switch. `src/db.py` `connect()` reads it each
  time, and for the project's own `jobs.db` path (every script's default) opens
  Postgres at `JOBSEARCH_PG_URL` instead. Any other path is still a SQLite file (tests,
  backups, the skills-review snapshot). Nothing in settings.yaml or the scheduled tasks
  changes, and a running dashboard follows the switch on its next page load.
- Every writer goes through `connect()`: the scrape (`aggregate.py`, enrichment,
  retention, dedup, scoring), the tailoring commands, the dashboard server,
  `browser_queue.py` (the Chrome task), `rescore.py`, `prune_unwanted.py`,
  `backfill_descriptions.py`. The skills review reads a SQLite snapshot made by
  `pg_mirror.py export`.
- `src/pgdb.py` takes the SQLite-flavoured SQL the code sends (`?` and `:name`
  placeholders, `INSERT OR IGNORE`, `char(10)`, the SCHEMA DDL) and returns rows that
  read like sqlite3 rows. PRAGMA and sqlite_master are refused; code uses
  `db.table_columns` / `db.has_table`, which work on both.

### Cutover (once)

`cutover` refuses while the dashboard answers on port 8765, a scrape holds
`.aggregate.lock`, or a tailoring run is going. It then:

1. syncs the mirror and checks it (stops unless every table matches);
2. replaces the mirror's tables with the app's own schema (ids become identity columns
   that continue after the highest id SQLite ever gave out; defaults, unique keys and
   indexes as in SQLite; no `_row_hash`) and copies every row, in one transaction;
3. compares every row of jobs.db with Postgres, value for value, and checks jobs.db's
   bytes didn't change during the copy (else it drops the copied tables, so the next
   mirror sync rebuilds them, and stops);
4. writes `JOBSEARCH_DB=postgres` to `.env` and moves jobs.db to
   `backups/jobs-sqlite-at-cutover-<time>.db`.

Desktop, normal PowerShell in `C:\Users\Nelly\job-search` (stop and start the dashboard
task from an admin PowerShell if a normal one is refused):

```powershell
git pull origin jake; uv sync
uv run python scripts/pg_mirror.py history     # the phase 3 syncs and checks
uv run python scripts/pg_mirror.py check       # must end "All tables match."
Stop-ScheduledTask -TaskName JobSearch-Dashboard
uv run python scripts/pg_mirror.py cutover
Start-ScheduledTask -TaskName JobSearch-Dashboard
```

Don't run it while the 6:45 PM Chrome task is going (it writes descriptions).

### Every day

`run_tailoring.ps1` runs `pg_mirror.py daily` after the run. Once Postgres is the main
database that writes `backups/jobs-<date>.db` (a SQLite copy with the app's schema,
newest 14 kept); before the cutover it is the mirror sync. `backup` makes one any time.

### Check

A day of runs with no errors in `logs\tailoring.log` and `logs\dashboard.log`, the
dashboard's counts match the day before, and `pg_mirror.py history` shows the backup.

### Rollback

```powershell
Stop-ScheduledTask -TaskName JobSearch-Dashboard
uv run python scripts/pg_mirror.py rollback                  # Postgres back to jobs.db
# or, when Postgres can't be reached (desktop IP changed, server down):
uv run python scripts/pg_mirror.py rollback --from-backup    # newest backups/jobs-<date>.db
Start-ScheduledTask -TaskName JobSearch-Dashboard
```

`rollback` writes Postgres to jobs.db (with the same ids), clears `JOBSEARCH_DB`, and
renames the Postgres tables `pre_rollback_*` so a mirror sync can start a fresh copy.
`--from-backup` loses whatever changed since that backup.

### If the desktop's IP changes

Postgres refuses connections from an address without a firewall rule, so after the
cutover the scrape, tailoring and dashboard all fail with "Couldn't connect" / a
connection timeout. Add the new IP (Firewall, above) and everything works again; or roll
back from the backup.

## Tests

`tests/test_pg_mirror.py` and `tests/test_pg_backend.py` run against a real Postgres when `JOBSEARCH_PG_TEST_URL`
names a scratch database (each test uses its own schema and drops it); without it the
Postgres tests are skipped. Never point it at the Azure server.
