# v2 Build Plan: Multi-Source Job Aggregation

Status: **in progress**. Workday + Adzuna + CareerJet are implemented and tested end-to-end
(DB, dedup, dashboard, xlsx export, CLI). Email-alert sources (LinkedIn/Indeed/Glassdoor) are
not wired in yet — see Progress Log at the bottom.

## Goal

One pipeline pulls jobs from 6 sources, dedups them, and surfaces everything in a single
reviewable spreadsheet + local HTML dashboard, without touching any code that isn't ours to
touch (i.e. no direct scraping of sites that prohibit it).

## Sources

| # | Source | Method | Notes |
|---|--------|--------|-------|
| 1 | Workday (UBC + City of Vancouver + TRIUMF + BCI + BCAA + TELUS, etc.) | Existing scraper | Unchanged — kept as-is, just feeds the new shared schema |
| 2 | LinkedIn | Gmail alert emails | `jobalerts-noreply@linkedin.com`. Not direct scraping — see Rejected Approaches |
| 3 | Indeed | Gmail alert emails | `donotreply@jobalert.indeed.com` |
| 4 | Glassdoor | Gmail alert emails | `noreply@glassdoor.com` |
| 5 | Adzuna | REST API | Free tier, `app_id` + `app_key` already obtained |
| 6 | CareerJet | REST API | Key obtained. Exact current endpoint/auth scheme TBD — see Open Items |

**Dropped: Jooble** — free tier is a 500-request *lifetime* cap (not daily), too small to
sustain an hourly-ish pipeline. Not worth building an adapter around.

## Storage

SQLite (`jobs.db`) is the source of truth. Per-job markdown files (existing cover-letter
workflow), the HTML dashboard, and the xlsx export are all **generated from this table** on
each run, so manual edits (e.g. marking a job "applied") survive re-scrapes instead of being
overwritten.

### `jobs` table

| Field | Notes |
|---|---|
| `id` | internal PK |
| `dedup_group_id` | groups the same real-world posting seen across multiple sources |
| `source` | `workday:ubc`, `linkedin`, `indeed`, `glassdoor`, `adzuna`, `jooble`, `careerjet` |
| `external_id` | source's own job ID where available (LinkedIn numeric ID, Indeed `jk`, etc.) |
| `title`, `company`, `location` | normalized (lowercased/trimmed) for matching + display copies |
| `description` | full text if available, else the alert-email snippet |
| `url` | link back to the original posting |
| `posted_date`, `first_seen`, `last_seen` | `last_seen` updates each run so we know a posting is still live |
| `status` | `new` / `applied` / `dismissed` / `expired` — must survive re-runs |
| `tier` | stub column — classification method deferred, see Tiering |
| `raw` | original JSON/HTML blob for debugging parsers |

No salary fields in v1 — descoped as too inconsistent across sources to normalize cleanly right now.

## Dedup

Normalize `(title, company, location)`. Fuzzy-match (e.g. `rapidfuzz`) new postings against
jobs first seen in the last ~45 days. A match merges into the existing `dedup_group_id`
(tracking which sources saw it) instead of creating a duplicate row.

## Email ingestion (LinkedIn / Indeed / Glassdoor)

Mechanism: search `jacobdavidandersenlum@gmail.com` by sender, parse new messages, track a
per-source "last processed" cursor in the DB so re-runs don't reprocess old mail.

Parsing notes, from live samples pulled during planning:

- **LinkedIn** — multi-job digest, plaintext-parseable. Job ID lives in the
  `/jobs/view/{id}/` URL path — stable dedup key. A single email can contain multiple alert
  sections (one per saved search), each with its own job list. Must filter out
  `messages-noreply@linkedin.com` ("industry trends" emails, not job alerts) — only
  `jobalerts-noreply@linkedin.com` is the real source.
- **Indeed** — multi-job digest, mostly clean plaintext. Job key lives in the `jk=` URL
  param — stable dedup key.
- **Glassdoor** — heavy nested-table HTML email; the plaintext conversion is unusable
  (garbled/mangled). Must parse the raw `html_body` with BeautifulSoup instead. The stable
  per-job ID param in the real anchor `href` wasn't fully resolved during planning — needs
  confirming against a real `html_body` fetch when this adapter gets built.

## API sources

| | Method | Auth | Params |
|---|---|---|---|
| **Adzuna** | GET `api.adzuna.com/v1/api/jobs/ca/search/{page}` | `app_id` + `app_key` as query params | `what`, `where`, `results_per_page` |
| **CareerJet** | GET `search.api.careerjet.net/v4/query` | HTTP Basic auth, key as username, blank password | `keywords`, `location`, `locale_code`, `user_ip` (real client IP, not a placeholder), `user_agent`, **plus a `Referer` header matching the site registered on the publisher dashboard** (`jacoblum.com`) — all four are required or the API rejects the request |

## Run / schedule model

- **Workday + 2 API sources**: hourly
- **Email-alert polling**: every 5–10 minutes — near-real-time without standing up Gmail
  push/Pub-Sub infrastructure (which would need a public always-on webhook endpoint; not
  worth it for digest emails that only arrive every few hours anyway)
- Each run: ingest → normalize → dedup → write to DB → regenerate dashboard + xlsx export

## Output

- **`dashboard.html`** — static file, regenerated every run, sortable/filterable table,
  opened locally in a browser. No server required.
- **`export.xlsx`** — same data as a spreadsheet.
- Existing per-job markdown files — regenerated from the DB, preserving the current
  cover-letter drafting workflow.

## Tiering

**Deferred** — not part of this build pass. Options on the table for later: keep the
existing keyword classifier ([tier.py](src/tier.py)), replace it with LLM-based fit scoring,
or run both side by side (cheap keyword pass + LLM score for close calls). Decide before
wiring the `tier` column into the dashboard.

## Credentials

Adzuna `app_id`/`app_key`, CareerJet key → local `.env`, gitignored, loaded via
`python-dotenv`. Never hardcoded or committed.

## Rejected approaches

- **Agent Reach** (GitHub tool) — general web-access tool, not job-search-specific (Twitter,
  Reddit, YouTube, GitHub, Bilibili, XiaoHongShu, etc.). Its LinkedIn access goes through
  `mcporter` → a LinkedIn MCP server using a real logged-in session cookie (`li_at`) with
  `patchright`, an "undetected" Playwright fork built specifically to evade LinkedIn's bot
  detection. Rejected — this risks the actual LinkedIn account (job history, network) getting
  flagged or banned, which is exactly the risk the email-alert approach was chosen to avoid.
- **Direct scraping of LinkedIn/Indeed/Glassdoor** — same ToS/anti-bot risk as above.

## Source verification (2026-09-17)

Before building the pipeline, every source was smoke-tested live to confirm it actually
returns usable, identifiable job data:

- **Adzuna** — live GET request against real Vancouver "data scientist" postings returned
  clean JSON: `id`, `title`, `company.display_name`, `location.display_name`, `description`,
  `redirect_url`, `created` date, `category`. Matches the schema directly.
- **CareerJet** — first two attempts failed (`Missing param user_ip or user_agent`, then
  `Invalid user_ip`, then `Undeclared referrer`) until the request included a **real** public
  IP, a `user_agent`, and a `Referer` header matching the site registered on the publisher
  dashboard (`jacoblum.com`, the placeholder domain from setup). With all four present, it
  returns real Vancouver jobs: `title`, `company`, `locations`, `date`, `description`, and a
  tracked `jobviewtrack.com` redirect `url`. No standalone numeric job ID — the `url` itself
  is the unique/dedup key.
- **Glassdoor email** — pulled the raw `html_body` of a real alert email. Plaintext
  conversion is unusable (confirms HTML parsing is required, as already planned), but the
  raw HTML contains `jobListingId=<numeric>` on every job card — a clean, stable dedup key.
  Open item resolved.
- **LinkedIn / Indeed email** — already confirmed from earlier live samples (job ID in the
  `/jobs/view/{id}/` URL path for LinkedIn, `jk=` param for Indeed).
- **Workday** — existing scraper already works in production; not re-verified.

## Open items to settle before/during build

1. Decide application-status tracking scope — just the `status` column, or something richer
   (notes field, applied-date, etc.).
2. Decide tiering approach (keyword / LLM / both) before wiring the dashboard's tier column.

## Suggested build order

1. SQLite schema + DB module
2. Adzuna / CareerJet adapters (simplest — pure API, immediate payoff)
3. Workday adapter refactor to write into the shared schema (reuse existing
   `scraper.py`/`parser.py`/`writer.py`, feed the new DB alongside or instead of markdown)
4. Email-alert adapters for LinkedIn / Indeed / Glassdoor (Gmail search + per-source parser)
5. Dedup pass
6. Dashboard + xlsx export generation
7. Scheduling (hourly APIs/Workday, 5–10 min email poll)

## Progress log

**2026-09-17 — steps 1, 2, 3, 5, 6 implemented and tested against live data:**

- [src/db.py](src/db.py) — SQLite schema, `upsert_job` (insert-or-refresh on
  `(source, external_id)`), source cursors, `grouped_jobs()` for dedup-grouped display.
- [src/sources/adzuna.py](src/sources/adzuna.py), [src/sources/careerjet.py](src/sources/careerjet.py) —
  tested against the real APIs, real Vancouver jobs returned.
- [src/sources/workday.py](src/sources/workday.py) — wraps the existing `AsyncWorkdayScraper`
  unchanged, maps output into the shared `Job` schema. Tested against live UBC data.
- [src/dedup.py](src/dedup.py) — compound rapidfuzz match on (company, location, title).
  Tested with synthetic cases and a real cross-source duplicate (the same "Teck Resources —
  Data Scientist III" posting from both Adzuna and CareerJet).
- [src/dashboard.py](src/dashboard.py), [src/export_xlsx.py](src/export_xlsx.py) — static HTML
  (vanilla JS sort/filter, verified interactively in-browser) and xlsx export, both grouped by
  dedup cluster.
- [scripts/aggregate.py](scripts/aggregate.py) — CLI tying it all together. Confirmed
  idempotent: running it twice in a row does not grow the DB or dashboard.

**Two real bugs found and fixed during testing** (not caught by planning — only surfaced by
running against live data):

1. `src/dashboard.py` originally used `str.format()` to inject values into the HTML template,
   but the template's own CSS/JS is full of literal `{}` — `.format()` choked on it
   immediately. Switched to plain token replacement (`__GENERATED_AT__` etc.) instead.
2. **CareerJet's `url` field is not stable** — it mints a fresh `jobviewtrack.com` tracking
   URL on every single API call, even for the exact same query seconds apart (confirmed by
   calling it twice back-to-back). The adapter originally hashed this URL as `external_id`,
   which made every CareerJet job look "new" on every run and the DB grew unbounded on
   re-runs (119 → 178 rows after one repeat run). Fixed by hashing normalized
   `(title, company, location)` instead — stable across repeated calls for the same posting.

Also tightened dedup's location matching: `fuzz.ratio` scored "Vancouver, BC" vs. "Greater
Vancouver, British Columbia" (the same posting, phrased at different granularity by two
sources) too low to match (54) because it penalizes the length difference. Switched to
`fuzz.token_set_ratio`, which correctly scores that pair at 87 while still keeping genuinely
different cities apart (Nanaimo vs. Greater Vancouver scores 30).

**2026-09-17 (cont'd) — two more additions:**

- **`years_experience` column.** Turns out [src/tier.py](src/tier.py) already had
  `parse_min_years_experience()`, built for the tier classifier's experience cutoff — reused
  it rather than writing a new parser. It's computed automatically in `Job.__post_init__` from
  the description, so every source gets it for free with no adapter changes. Shows up in both
  the dashboard and the xlsx export. Tested against real descriptions: correctly pulled 3, 5,
  8, 10, 12 years etc. out of real Adzuna/CareerJet postings.
- **Multi-user Gmail auth**, since this repo is going to be shared and a friend will connect
  their own inbox, not Jacob's. Built [src/gmail_client.py](src/gmail_client.py) +
  [scripts/gmail_auth.py](scripts/gmail_auth.py) using the standard OAuth "installed app" flow
  (`run_local_server()`) — opens the browser, user clicks Allow, zero copy-pasting. Each person
  needs their own lightweight Google Cloud project + OAuth client (Google requires this per
  app; there's no way around it), documented step-by-step in
  [GMAIL_SETUP.md](GMAIL_SETUP.md). `credentials.json` and `token.json` are both gitignored —
  per-person, never committed. Verified the error paths (missing credentials.json, missing
  token.json) give clear messages pointing at the setup doc; the actual browser consent click
  is Jacob's own action to do interactively, not something automatable here.

**Not yet done:**

- Email-alert adapters (LinkedIn/Indeed/Glassdoor). The parsing logic can be built and
  unit-tested against the real sample emails already pulled during planning, but *live*
  ingestion needs its own Gmail API access — separate from this session's Gmail connector,
  which a standalone script can't reuse. That means a one-time setup step on Jacob's end:
  a Google Cloud project with the Gmail API enabled, an OAuth consent screen, and a
  downloaded `credentials.json` + one-time browser auth to produce a reusable `token.json`.
  Flagging this now since it blocks the email sources specifically, not the rest of the
  pipeline.
- New dependencies added: `python-dotenv`, `rapidfuzz`, `openpyxl` (via `uv add`).
- Scheduling (step 7) — not started.
- Tiering — still deferred per the earlier decision.
