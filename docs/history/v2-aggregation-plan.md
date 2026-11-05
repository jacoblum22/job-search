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

Mechanism: search my own inbox by sender, parse new messages, track a
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
existing keyword classifier ([tier.py](../../src/tier.py)), replace it with LLM-based fit scoring,
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

- [src/db.py](../../src/db.py) — SQLite schema, `upsert_job` (insert-or-refresh on
  `(source, external_id)`), source cursors, `grouped_jobs()` for dedup-grouped display.
- [src/sources/adzuna.py](../../src/sources/adzuna.py), [src/sources/careerjet.py](../../src/sources/careerjet.py) —
  tested against the real APIs, real Vancouver jobs returned.
- [src/sources/workday.py](../../src/sources/workday.py) — wraps the existing `AsyncWorkdayScraper`
  unchanged, maps output into the shared `Job` schema. Tested against live UBC data.
- [src/dedup.py](../../src/dedup.py) — compound rapidfuzz match on (company, location, title).
  Tested with synthetic cases and a real cross-source duplicate (the same "Teck Resources —
  Data Scientist III" posting from both Adzuna and CareerJet).
- [src/dashboard.py](../../src/dashboard.py), [src/export_xlsx.py](../../src/export_xlsx.py) — static HTML
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

- **`years_experience` column.** Turns out [src/tier.py](../../src/tier.py) already had
  `parse_min_years_experience()`, built for the tier classifier's experience cutoff — reused
  it rather than writing a new parser. It's computed automatically in `Job.__post_init__` from
  the description, so every source gets it for free with no adapter changes. Shows up in both
  the dashboard and the xlsx export. Tested against real descriptions: correctly pulled 3, 5,
  8, 10, 12 years etc. out of real Adzuna/CareerJet postings.
- **Multi-user Gmail auth**, since this repo is going to be shared and a friend will connect
  their own inbox, not Jacob's. Built [src/gmail_client.py](../../src/gmail_client.py) +
  [scripts/gmail_auth.py](scripts/gmail_auth.py) using the standard OAuth "installed app" flow
  (`run_local_server()`) — opens the browser, user clicks Allow, zero copy-pasting. Each person
  needs their own lightweight Google Cloud project + OAuth client (Google requires this per
  app; there's no way around it), documented step-by-step in
  [gmail-setup.md](../gmail-setup.md). `credentials.json` and `token.json` are both gitignored —
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

**2026-09-18 — location filtering (Vancouver-area or remote only):**

Turned out the aggregator was pulling in a lot more than intended: Workday only filtered by
city keywords (no remote allowance), and Adzuna/CareerJet were scoped to `where=Vancouver, BC`
only. Tested empirically before building anything: a Canada-wide Adzuna search for "data
scientist" surfaced 12 remote-mentioning postings vs. only 7 from the Vancouver-scoped search
— genuinely remote jobs tagged with other cities (Ottawa, Calgary, Saskatoon) were being missed
entirely, not just mis-categorized.

Fix, decided with Jacob to filter at the source rather than just hide-in-dashboard (so the
aggregator stops wasting rows on irrelevant on-site postings from other cities), while keeping
everything visible/auditable rather than silently dropping anything:

- [src/location_filter.py](../../src/location_filter.py) — `classify_location()` returns
  `"vancouver"` / `"remote"` / `"other"`. Vancouver keyword list is generous (all Metro
  Vancouver municipalities) to avoid false negatives. Remote detection checks the location
  field (not description — too noisy) for "remote"/"wfh"/bare "Canada", with a guard against
  "Remote (United States)"-style non-Canada postings. Tested against 17 real location strings
  pulled from actual API responses — all correct.
- Every job gets `location_category` computed automatically (same pattern as
  `years_experience`) — visible as its own dashboard column + filter dropdown, and in the xlsx
  export. Nothing is hidden by default.
- Adzuna/CareerJet adapters now run **two search passes** per keyword: the existing
  Vancouver-scoped one (unchanged), plus a second `where=Canada` pass filtered down to only
  `is_remote()` matches before merging — this is what catches the Ottawa/Calgary/Saskatoon-
  tagged remote jobs without flooding in their on-site counterparts.
- Workday's per-source `location_filter` now also admits a job if `is_remote()` matches, so a
  remote posting from an org whose filter only lists specific cities doesn't get silently
  dropped before we even see it.

Tested end-to-end against live data: 127 jobs fetched, split 112 vancouver / 14 remote / only
**1** stray "other" (a Calgary job Adzuna's own geo-matching loosely included in the Vancouver-
scoped search — correctly flagged as "other" by the classifier and visible/filterable, not
hidden). Re-confirmed idempotency still holds after these changes (0 new / 0 merged on re-run).

**One dashboard bug found in testing**: added the new location-category filter dropdown but
forgot to wire up its `change` event listener — selecting a value did nothing. Caught by
actually clicking it in the browser rather than just checking the HTML rendered; fixed and
re-verified (111 → 14 shown when filtering to "Remote").

**2026-09-19 — `years_experience` false positives + low hit rate, investigated:**

Jacob flagged a specific bad value: a Champion Petfoods posting showed "35 years" required.
Root-caused to two separate issues, only one of which is fixable:

1. **Real bug**: [tier.py](../../src/tier.py)'s `parse_min_years_experience()` matched any bare "N
   years" in the text — no check that it was actually about experience. The Champion Petfoods
   description said "a reputation of trust spanning 35 years" (company history, not a job
   requirement) and the regex happily matched it, then `max()` picked it over any real
   (smaller) figure. Fixed by requiring the word "experience" within 80 characters of the
   match — tuned by testing against both false positives (company history, warranties, "21
   years of age") and real phrasings, including one where the gap between the number and
   "experience" was 66 characters ("3+ years of non-internship professional software
   development experience") — an earlier, narrower 50-char window I tried first actually broke
   that legitimate case, caught by testing against real Amazon posting text before settling on
   80. Recomputed against the existing DB (no need to re-fetch): 17 → 14 jobs with a value, net
   change reflecting the false positives removed.
2. **Not a bug — a real data limit**: Adzuna's and CareerJet's *search* endpoints only return
   truncated description snippets (Adzuna: ~500 chars, CareerJet: ~300 chars — confirmed by
   checking the raw API response, not something our code is doing). Experience requirements
   are often stated further down in a "Requirements" section that's simply not present in what
   we receive. This is why the column is empty most of the time — it's not a parsing failure,
   it's data we don't have. The only way to get the full text would be to fetch each job's own
   page (the `redirect_url`/`url`), which reopens the scraping-arbitrary-third-party-sites
   question we deliberately avoided elsewhere in this project. Left as-is for now — flagging
   the tradeoff rather than silently adding scraping.

**2026-09-19 (cont'd) — Workday location_category gap, found by actually running Workday.**

Jacob asked why the dashboard's source list only showed adzuna/careerjet — turned out every
test run since the location-filter work used `--skip-workday` for speed, so Workday simply
hadn't been re-run since those fields were added (confirmed: the DB genuinely only had
71+56=127 rows, no Workday). Ran it fresh to check it still worked with the new fields, and
that surfaced a real, related gap: 3/3 City of Vancouver postings were marked `other` because
that Workday board lists an internal facility code as the location ("LOC0049 Brookside
Utilities Building") with no city name at all — even though the employer itself, "City of
Vancouver," makes it unambiguous. A BCAA posting in "Victoria, BC" was correctly excluded in
the same check, confirming the classifier wasn't just being loose — Victoria isn't Vancouver
despite the name similarity.

Fixed by falling back to checking the **company name** for a Vancouver-area match when the
location text doesn't resolve one — `classify_location()` now takes an optional `company`
param. Verified this doesn't accidentally "fix" the Victoria/BCAA case (company name "BCAA"
doesn't mention Vancouver, so it correctly stays `other`). Recomputed against the existing DB:
3 rows corrected, all City of Vancouver.

**2026-09-30 — recall was the bottleneck, not experience parsing.**

A live run after merging email-alert-sources showed the pipeline was not "too strict on
descriptions": Adzuna snippets still had **0** parsed `years_experience` values. What actually
starved the set:

1. Workday/email matching was **title substring of the canonical phrase only** — "HR
   Coordinator" never matched "Human Resources".
2. `search.location: Canada` made the Adzuna *primary* pass national, so ingest filled with
   Toronto/Calgary on-site jobs; Vancouver+remote was a small slice.
3. API queries were only `intern` / `entry level`, page 1, 20 hits — no co-op/new-grad/alias
   queries, no pagination.
4. CareerJet **403 on the first query** aborted the whole source.
5. No Gmail token caused **all** email adapters to skip, even if Outlook was the inbox.

Fix (this change):

- [src/search_match.py](../../src/search_match.py) — shared `keep_job()` + `api_queries()` with
  alias table, title-only weak words (`recruiting`), noisy "events" not matching
  "in the event of", location gate via `classify_location(location, company)`.
- Settings: `location: Vancouver, BC`, `remote_sweep_location: Canada`,
  `require_relevant_location: true`, expanded `level_terms`, Adzuna `max_pages: 3` /
  `results_per_page: 50`.
- Adzuna paginates the documented `/search/{page}` path until a short page.
- CareerJet sends `User-Agent` as an HTTP header and **continues** after per-query 403.
- Email: `collect_alert_messages()` tries Gmail and Outlook independently
  (`{source}:gmail` / `{source}:outlook` cursors). Adapter signatures take `conn` first;
  inject `service=` in tests.
- Tests under `tests/` (`uv run pytest`).

**2026-10-01 — Adzuna, CareerJet, and Workday made to finish a run.**

Adzuna 503 used to abort the entire API source; CareerJet timeouts aborted the rest
of the keyword list; Workday `asyncio.gather` without `return_exceptions` could
drop every tenant if one board failed. Search snippets were never refreshed on
upsert (`last_seen` only).

- [src/http_retry.py](../../src/http_retry.py) — shared GET retries for 429/502/503/504 and
  network errors.
- Adzuna: per-query isolation, request pacing, pagination stop on persistent 503
  (keep pages already fetched), hydrate descriptions from `adzuna.ca/land/ad/{id}`
  JSON-LD (Adzuna has no details API; this is their public job page, not employer
  scraping).
- CareerJet: 90s read timeout, pagination via `page`/`pages`, per-query 403/timeout
  skip. Still snippet-only (no details API).
- Workday: `should_hydrate_record()` so HVAC/VP never get a details round-trip;
  `return_exceptions=True` per tenant; 503 retried like 429.
- `upsert_job` updates title/location/description/years/category when the new
  description is at least as long as the stored one.


