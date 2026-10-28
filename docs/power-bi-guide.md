# Power BI guide (Azure plan, phase 7)

The Power BI report reads the summary tables dbt rebuilds every morning (`docs/dbt-guide.md`)
and shows them on three pages: Market, Funnel and Posting life. It's built in Power BI Desktop,
the free Windows app, on the desktop PC. The Power BI website (the "service") needs a work or
school email, so the report lives as files in this repo instead of being published there.

## What's already set up

| Piece | Where | What it does |
| --- | --- | --- |
| Read-only login | `scripts/powerbi_login.py` | Makes `powerbi_reader`, a Postgres login that can only read the `analytics` schema. It can't change anything or see the app's own tables (`score_inputs` holds vault files). |
| Report folder | `powerbi/` | Where the report is saved as a Power BI project (`.pbip`), which is plain text files git can track. |
| Git rules | `.gitignore` | Keeps `cache.abf` (the saved copy of every row, application outcomes included) and per-PC settings out of the public repo. |

## One-time setup (desktop)

```powershell
cd C:\Users\Nelly\job-search
git checkout jake; git pull
uv run python scripts/powerbi_login.py create   # prints the password once
uv run python scripts/powerbi_login.py check    # "yes" for each analytics table, "blocked" for the app's
```

Running `create` again gives the login a new password (then update it in Power BI under
File > Options and settings > Data source settings).

## Connecting Power BI

Get data > PostgreSQL database:

- Server: `jobsearch-pg-jake.postgres.database.azure.com`
- Database: `jobsearch`
- Data connectivity mode: Import (a copy of the data, refreshed when you press Refresh)
- When asked for credentials, pick the **Database** tab: user `powerbi_reader` and the password
  `create` printed. Power BI keeps it in Windows, never in the report files.

In the list that opens, tick the tables under `analytics` whose names start with `fct_`, `agg_`
or `dim_`. Their column descriptions (from dbt) show as tooltips.

The desktop's internet address is already allowed through the Postgres firewall, because the app
connects from there. On another PC, Power BI won't connect until that PC's address is added.

## Saving

File > Save as > choose "Power BI project files (*.pbip)" and save into `powerbi/` as
`job-search.pbip`. If that file type isn't offered, turn it on under File > Options and settings >
Options > Preview features > "Power BI Project (.pbip) save option", restart, and save again.

Before committing, `git status` should show files under `powerbi/` but never a `cache.abf`.

## Refreshing

The 9:00 run rebuilds the tables; press Refresh in Power BI after that to pull the new data.
