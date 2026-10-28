# Postgres shadow copy (Azure plan, phase 3)

jobs.db stays the only database anything reads. Phase 3 keeps a copy of it in Azure
Database for PostgreSQL so phase 4 (switching over) starts from a copy that has
matched for a week. Code: `src/pg_mirror.py`, `scripts/pg_mirror.py`.

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

## Rollback

Set `postgres_mirror: false`. Nothing reads Postgres, so nothing else changes. To stop
paying anything after the free year, `az postgres flexible-server stop` (it restarts
itself after 7 days) or delete the server.

## Tests

`tests/test_pg_mirror.py` runs against a real Postgres when `JOBSEARCH_PG_TEST_URL`
names a scratch database (each test uses its own schema and drops it); without it the
Postgres tests are skipped. Never point it at the Azure server.
