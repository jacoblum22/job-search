# The daily scrape in Azure (Azure plan, phase 5)

Every morning an Azure Container Apps job runs `scripts/aggregate.py` (every source)
against the Azure Postgres database, so new postings arrive whether or not the desktop is
on. Tailoring, the dashboard, the Chrome task and the skills review stay on the desktop.

| Piece | What it is |
| --- | --- |
| Image | `ghcr.io/jacoblum22/job-search-scrape:jake`, built from `Dockerfile` by `.github/workflows/scrape-image.yml` on every push to `jake` that touches code or config (after the tests pass). Built from the repo only: no `materials/`, `.env`, `token.json`. |
| Job | `job-search-scrape` in environment `cae-job-search`, resource group `rg-job-search`, Canada Central. Schedule `0 14 * * *` UTC (7:00 Vancouver summer time, 6:00 winter). 1 vCPU, 2 GiB, 60 min timeout, no retries. |
| Secrets | From the desktop's `.env` (`JOBSEARCH_PG_URL`, Adzuna, CareerJet, Himalayas) and `token.json` (Gmail), stored as Container Apps secrets. `scripts/azure_job_spec.py` builds the definition, `scripts/azure_scrape_job.ps1 deploy` sends it. |
| Database access | Postgres firewall rule `AllowAzureServices` (0.0.0.0): the Consumption plan has no fixed outbound IP. Anyone connecting still needs the password and TLS. |

## How it fits with the desktop

- **One scrape at a time, across machines.** On top of `.aggregate.lock` (this machine), a
  scrape holds a Postgres advisory lock for its whole run (`src/db.py` `try_scrape_lock`),
  released by itself if the scrape dies. A desktop scrape started while the Azure job runs
  waits (`--wait-lock`) or skips. `pg_mirror.py rollback` refuses while either is running.
- **The tailoring run doesn't scrape twice.** `run_tailoring.ps1` passes
  `--skip-if-fresh 6`: if a full run finished in the last 6 hours (the morning job), the
  scrape step exits 4 and the log says so. If the Azure job failed or didn't run, the
  desktop scrapes as before, so a bad morning costs nothing but time.
- **Scoring uses the vault.** `src/score.py` subtracts points for tools the experience
  vault doesn't show, read from `materials/profile/vault-index.json` and
  `materials/tailor/skill-record.json`. Those are personal and never in the image, so the
  desktop saves them to a `score_inputs` table (`scripts/score_inputs.py push`, run after
  every tailoring run and by any desktop scrape) and the job writes them back out before
  scoring. With no vault in reach the job stops before scraping instead of rescoring every
  job without it.
- **What the last run did.** Every run records a summary (where it ran, image, minutes,
  new jobs, per-source downloaded/kept/errors) in `source_cursors`:
  `uv run python scripts/aggregate.py --show-last-run`.

## One-time setup (desktop, normal PowerShell, `C:\Users\Nelly\job-search`)

1. Pull the branch with this change: `git pull origin jake`, then `uv sync`.
2. After the merge, GitHub builds the image (repo, **Actions** tab, "Scrape image"). The
   first time, make the package public so Azure can pull it without a password: GitHub,
   your profile, **Packages**, `job-search-scrape`, **Package settings**, **Change
   visibility**, Public. It holds only what's already in the public repo.
3. `.\scripts\azure_scrape_job.ps1 setup` (extension, providers, environment, firewall rule;
   a few minutes).
4. `.\scripts\azure_scrape_job.ps1 deploy` (saves the vault files to Postgres, then creates
   the job with the secrets).
5. `.\scripts\azure_scrape_job.ps1 run`, wait about 10 minutes, then
   `.\scripts\azure_scrape_job.ps1 status`. Compare the per-source counts with a desktop run
   (`logs\full_aggregate.log`): a source that reads 0 or errors only from Azure is being
   blocked by Azure's IPs (CareerJet and Adzuna were the expected risks).

Run `deploy` again after changing a key in `.env` or reconnecting Gmail (`token.json`).
New code needs no deploy: each run pulls the `:jake` image, and `--show-last-run` names
the image's commit.

## Gmail

The job reads alert emails with the refresh token from `token.json`. If the Google Cloud
project's OAuth consent screen is in **Testing**, Google expires that refresh token after 7
days, on the desktop as well. To stop that, set the consent screen to **In production**
(Google Cloud console, APIs & Services, OAuth consent screen, Publish app); a personal app
keeps working unverified, with a warning screen on the next sign-in. Then reconnect
(`uv run python scripts/gmail_auth.py`) and `deploy`. A failing Gmail read is logged per
source; the other sources still run.

## Cost

Consumption plan free grant per month: 180,000 vCPU-seconds and 360,000 GiB-seconds. One
10-minute run a day at 1 vCPU / 2 GiB uses about 18,000 and 36,000: about 10% of the grant,
so $0. The environment costs nothing on its own; Log Analytics is free for the first 5 GB a
month. Pushing to ghcr is free for a public package.

## Turning it off

- Pause: `az containerapp job update -n job-search-scrape -g rg-job-search --cron-expression "0 14 31 2 *"`
  (a date that never comes); the desktop's tailoring run scrapes again on its own once the
  last Azure run is older than 6 hours.
- Remove: `az containerapp job delete -n job-search-scrape -g rg-job-search --yes`, then
  `az postgres flexible-server firewall-rule delete -g rg-job-search --server-name jobsearch-pg-jake --name AllowAzureServices --yes`.
