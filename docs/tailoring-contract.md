# Tailoring pipeline: build contract

This is the shared contract for `src/tailor/`, the package that turns one job posting into a tailored
resume and cover letter. The design (why each step exists) is in the project plan
`plans/full-tailoring-pipeline.md`; this file pins down **file layout, JSON shapes, function
signatures and CLI commands**, so modules can be built in parallel and still fit together.

## How the pipeline runs

The pipeline runs as a scheduled Claude Code task on Jake's PC (`docs/tailoring-runbook.md`).
Two kinds of steps alternate:

- **Code steps** are `uv run python -m src.tailor <command> <app-dir>` commands. They read and write
  JSON files in the application folder, call Jev when a key is configured, and never call Claude.
- **Claude steps** are done by the scheduled Claude session itself (or a Haiku subagent for company
  research), following a prompt file in `prompts/tailor/`. Each writes one JSON file with a fixed
  shape, which the next code step validates.

Code owns facts and every blocking decision. Claude writes. Jev answers cheap typed questions and
only ever produces flags or advisory evidence. **Everything must still work with no Jev key**: Jev
answers then come back `ok=False` and are treated as "unchecked" (gate flags) or skipped
(evidence falls back to the taxonomy, checklist items are marked unchecked).

## Paths (`src/tailor/paths.py`)

All personal data lives under the git-ignored `materials/`. Defaults, overridable in
`config/settings.yaml` under `tailor.paths`:

| Name | Default |
|---|---|
| `materials` | `materials/` |
| `applications` | `materials/applications/` |
| `companies` | `materials/companies/` |
| `bases` | `materials/resumes/bases/` |
| `vault_index` | `materials/profile/vault-index.json` |
| `rules` | `materials/docs/tailoring-rules.md` |
| `db` | `jobs.db` |
| `unknown_terms` | `materials/tailor/unknown-terms.csv` |

## Application folder

One folder per job: `materials/applications/<YYYY-MM-DD> <Company> - <Title>/` (filesystem-safe,
max 120 chars). Contents, in the order steps create them:

| File | Written by | Step |
|---|---|---|
| `app.json` | code | 0, updated by every step |
| `posting.md` | code | 0 |
| `requirements.json` | Claude, normalized by code | 1 |
| `evidence.json` | code | 2 |
| `plan.json` | code (base pick, relevance), then Claude adds the plan fields | 3 |
| `drafts/r<N>/edits.json` | Claude | 4 / 7 |
| `drafts/r<N>/cover-letter.json` | Claude | 4b / 7 |
| `drafts/r<N>/resume.yaml` | code (edits applied to the base) | 4 |
| `drafts/r<N>/applied.json` | code | 4 |
| `drafts/r<N>/check.json` | code | 5 |
| `drafts/r<N>/grade.json` | code | 6 |
| `drafts/r<N>/feedback.json` | code (input to the repair round) | 7 |
| `humanize/flags.json`, `humanize/patches.json` | code, then Claude | 8 |
| `final/` resume + letter `.yaml/.json/.docx/.pdf`, `parse.json` | code | 9 |
| `fit-notes.md`, `check.md` | code | 10 |

Company research lives outside the application folder, shared by every job at that company:
`materials/companies/<company-slug>/` with `facts.json`, `notes.md`, and `pages/<n>.txt` (saved page
text the facts quote from).

### `app.json`

```json
{
  "job_id": 123, "company": "Acme", "title": "Data Analyst", "url": "https://...",
  "tier": "A", "score": 64, "created": "2026-10-18",
  "status": "shortlisted",
  "gate": {"flags": [{"question": "seniority_fit", "text": "...", "answer": 1, "confidence": 0.8, "reason": "failed|unchecked"}],
           "flagged": true, "queue_rank": 4},
  "base_id": null,
  "rounds": [{"round": 1, "score": 71.5, "criticals": 0, "failed_items": 3}],
  "best_round": null,
  "history": [{"at": "2026-10-18T10:00:00Z", "step": "queue", "note": "..."}]
}
```

`status` moves `shortlisted → drafted → checked → ready_for_review → approved → applied`, or
`skipped`. The same fields (minus `rounds`/`history`) are mirrored in the `applications` table in
`jobs.db` (`src/tailor/store.py`): `job_id INTEGER PRIMARY KEY, folder, status, tier, score,
gate_flags TEXT (json), flagged INTEGER, queue_rank, base_id, created_at, updated_at, outcome,
outcome_at`.

### `requirements.json` (Claude writes, `normalize` validates)

```json
{
  "title": "Data Analyst", "company": "Acme", "seniority": "entry|junior|mid|senior|unknown",
  "years_required": 2, "education": "Bachelor's in a quantitative field",
  "requirements": [
    {"id": "r1", "text": "Strong SQL", "kind": "must|nice", "tier": 1, "terms": ["SQL"],
     "weight": "role|boilerplate", "quote": "exact words from the posting"}
  ],
  "keywords": [{"term": "Looker", "weight": "role|boilerplate", "quote": "..."}],
  "responsibilities": ["..."],
  "company_facts": [{"fact": "...", "quote": "..."}],
  "hiring_contact": {"name": "Priya Shah", "role": "hiring_manager|recruiter", "quote": "..."}
}
```

`normalize` adds `canonical` (taxonomy display name or `null`) to every term, checks every `quote`
appears in `posting.md` (whitespace/case-insensitive) and drops items whose quote doesn't, sets
`hiring_contact` to `null` unless its quote is verbatim in the posting **and** contains the name,
and appends unknown terms to `unknown_terms`. Results are written back plus a `"_normalized"` block
listing what was dropped.

### `evidence.json`

```json
{
  "requirements": [{"id": "r1", "status": "covered|partial|missing", "strength": 0,
                     "passages": ["algaecal.sql-daily"], "method": "taxonomy|jev|none"}],
  "terms": [{"term": "SQL", "canonical": "SQL", "kind": "must|nice|keyword", "weight": "role|boilerplate",
             "passages": ["..."], "in_base": {"data-scientist": true}}],
  "buckets": {"data-scientist": {"matched": ["SQL"], "injectable": ["dbt"], "non_injectable": ["Tableau"],
                                  "current_pct": 62.5, "potential_pct": 81.0}},
  "present": ["SQL", "dbt"], "absent": ["Tableau"]
}
```

Strength: 0 none, 1 mentioned only in a skills list, 2 in a bullet, 3 in a bullet with a concrete
tool and scope. `present` = matched + injectable (vault-backed); `absent` = non-injectable.

### `plan.json`

Code part (`run_base`): `{"base_id", "base_scores": {base: potential_pct}, "jev_pick": base|null,
"bullet_relevance": {"experience/algaecal/algaecal.sql-daily": 3}, "candidate_passages": [ids],
"protected_paths": [paths that are the only cover for a matched must-have]}`.
Claude adds: `{"headline": "...|null", "summary_angle": "...", "swap_in": [passage ids],
"swap_out": [paths], "skills_order": [group ids]}`.

### `edits.json` (Claude writes)

```json
{"strategy": "nudge|keywords|full",
 "edits": [{"path": "experience/algaecal/algaecal.sql-daily", "action": "replace",
            "original": "current text", "value": "new text", "reason": "...", "sources": ["algaecal.sql-daily"]}]}
```

Paths: `summary`; `<section>/<entry id>/<bullet id>` for bullets; `<section>/<entry id>` for
`append` (new bullet, id `<entry>.new-<n>`); `skills/<group id>` for `add_skill` / `reorder`;
`<section>/<entry id>` with `action: "reorder"` and a list value of bullet ids. Actions:
`replace | append | remove | reorder | add_skill`. **Never editable:** `title, company, location,
dates, school, degree, name, url, contact`, any `id`, and `education` lines except coursework.
Gates (all must pass or the edit is rejected with a reason): path allowed, path resolves, not
locked, `replace.original` matches current text (case/whitespace-insensitive), `reorder` keeps
exactly the same items, every `sources` id exists in the vault index and is a `claim` passage,
`append`/`replace` must cite at least one source.

### `cover-letter.json` (Claude writes)

```json
{"greeting": "Dear Hiring Manager,",
 "paragraphs": [{"text": "...", "sources": ["algaecal.churn-models"], "company_facts": ["f2"]}],
 "sign_off": "Sincerely,\nJake Andersen-Lum"}
```

`company_facts` cite ids from the company's `facts.json` or `posting:<n>` for the n-th item of
`requirements.json.company_facts`.

### `check.json`

```json
{"criticals": [{"code": "invented_number", "message": "...", "path": "...", "doc": "resume|letter"}],
 "warnings": [{"code": "...", "message": "...", "path": "...", "doc": "..."}],
 "flags": [{"code": "jev_unsupported", "message": "...", "path": "...", "doc": "...", "source": "jev"}],
 "reverted": ["paths reverted to the base text"],
 "metrics": {"alignment": 0.0, "preservation": 0.0, "baseline": 0.0, "lift": 0.0, "borrowed_rate": 0.0}}
```

Codes are short snake_case strings; the full list lives in `src/tailor/checks.py`.

### `grade.json`

```json
{"ats": {"total": 78.0, "components": {"keyword": 80, "skills": 75, "title": 100, "sections": 100, "dates": 100}},
 "checklist": [{"id": "must.r1", "question": "...", "passed": true, "confidence": 0.9, "source": "jev|code|unchecked"}],
 "score": 76.2, "stuffing": false,
 "feedback": ["Must-have 'dbt' isn't shown; passage resess.pipeline supports it."]}
```

`score` = 0.6 × ATS total + 0.4 × checklist pass rate × 100 (unchecked items count as passed for the
score but are listed). `feedback` is built by code from failed items; it never quotes the checklist
question wording.

### `feedback.json` (input to a repair round)

`{"round": 2, "criticals": [...from check], "failed_items": [...from grade feedback], "sections":
[paths of sections allowed to change]}`. Claude may only edit inside `sections`.

### Humanize

`flags.json`: `[{"path", "text", "reasons": ["banned:leverage", "dash"]}]`. Claude writes
`patches.json`: `[{"path", "replacement"}]`. Code rejects a patch that changes, adds or removes a
number, touches a path not in `flags.json`, or uses a banned phrase not protected; the whole pass is
reverted if the warning count goes up.

## Modules and owners

| Module | Owns | Public functions |
|---|---|---|
| `paths.py`, `cli.py`, `appdir.py` | skeleton (done) | `load_config()`, `resolve(name)`, `AppDir` helpers |
| `store.py`, `queue.py` | step 0 | `ensure_table(conn)`, `upsert_app(conn, app)`, `run_queue(cfg, limit, jev) -> list[Path]` |
| `jev.py` | Jev client | `JevClient.from_env()`, `client.ask(state, questions) -> list[Answer]`, `FakeJev`, `strip_identity(text, contact)` |
| `taxonomy.py`, `requirements.py`, `evidence.py`, `base.py` | steps 1-3 (code) | `normalize(app_dir, cfg)`, `run_evidence(app_dir, cfg, jev)`, `run_base(app_dir, cfg, jev)` |
| `phrases.py` | shared (done) | `scan(text, posting, own_texts, letter=False) -> list[Hit]`, `is_protected(phrase, posting, own_texts)` |
| `edits.py`, `checks.py`, `metrics.py`, `letter.py` | steps 4-5 | `apply_edits(app_dir, round, cfg)`, `run_check(app_dir, round, cfg, jev)` |
| `grade.py`, `loop.py`, `humanize.py` | steps 6-8 | `run_grade(app_dir, round, cfg, jev)`, `next_round(app_dir, cfg) -> dict`, `humanize_flags(app_dir, cfg)`, `humanize_apply(app_dir, cfg)` |
| `render.py`, `parsecheck.py`, `company.py`, `packet.py` | steps 1b (verify), 9, 10 | `verify_company(company_dir)`, `run_render(app_dir, cfg)`, `parse_check(pdf, source)`, `run_packet(app_dir, cfg)` |
| `prompts/tailor/*.md`, `docs/tailoring-runbook.md`, `scripts/skills_crosscheck.py` | Claude steps + skills growth | |

Every public `run_*` / `apply_*` function takes the application folder as a `Path`, reads its
inputs from files, writes its outputs to files, appends to `app.json.history`, and returns the
output dict. They raise `TailorError` (from `src/tailor/__init__.py`) with a human-readable message
when an input file is missing or malformed.

## Tests

Each module gets `tests/test_tailor_<module>.py`, using fixtures in `tests/fixtures/tailor/`
(synthetic vault index, base resume, posting). **No personal data in fixtures**: the repo is public.
Use invented people and companies. Tests never hit the network; Jev is replaced by `FakeJev`.
