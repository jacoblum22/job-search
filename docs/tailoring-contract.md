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
| `skill_record` | `materials/tailor/skill-record.json` |
| `jev_cache` | `materials/tailor/jev-cache.json` |

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
| `review/input.md`, `review/notes.md`, `review/response.json` (pass 1; later passes in `review/pass<N>/`) | code, then a fresh reviewer, then Claude (the review round) | 7b |
| `humanize/flags.json`, `humanize/patches.json` | code, then Claude | 8 |
| `final/` resume + letter `.yaml/.json/.docx/.pdf`, `parse.json` | code | 9 |
| `fit-notes.md`, `check.md` | code | 10 |

Company research lives outside the application folder, shared by every job at that company:
`materials/companies/<company-slug>/` with `facts.json`, `notes.md` (the research step's notes),
`verified.md` (written by `company-verify`), and `pages/<n>.txt` (page text saved by `company-fetch`,
which the facts quote from).

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
and appends unknown non-boilerplate terms to `unknown_terms`. Each requirement also gets a
`canonical` list parallel to its `terms` list. Results are written back plus a `"_normalized"` block
listing what was dropped.

### `evidence.json`

```json
{
  "requirements": [{"id": "r1", "status": "covered|partial|missing", "strength": 0,
                     "passages": ["algaecal.sql-daily"], "method": "taxonomy|jev|confirmed|none (or a+b)",
                     "confirm_key": "collaboration/teamwork",
                     "candidates": [{"passage": "soft.data-team", "value": 0.35}]}],
  "terms": [{"term": "SQL", "canonical": "SQL", "kind": "must|nice|keyword", "weight": "role|boilerplate",
             "raw": ["SQL"], "passages": ["..."], "related": ["..."], "in_base": {"data-scientist": true}}],
  "buckets": {"data-scientist": {"matched": ["SQL"], "injectable": ["dbt"], "related": ["A/B testing"],
                                  "non_injectable": ["Tableau"],
                                  "current_pct": 62.5, "potential_pct": 81.0}},
  "present": ["SQL", "dbt"], "absent": ["Tableau"]
}
```

Strength: 0 none, 1 mentioned only in a skills list, 2 in a bullet, 3 in a bullet with a concrete
tool and scope. `passages` hold only passages that use the posting's own wording (or the skill's
canonical name), strongest first, capped at `evidence.max_passages` (8). Passages that match only
through a taxonomy synonym ("experimentation" for A/B testing) go in `related` (at most 3); a term
backed only that way lands in the `related` bucket, is not in `present`, and may be written only
in the passage's own wording. `present` = matched + injectable; `absent` = everything else except
boilerplate terms (perks, EEO text), which never reach `absent`, `non_injectable` or the
unknown-terms log.

A term the taxonomy doesn't know (`canonical: null`) is matched by its plain words, so each such
passage or base line counts only after Jev answers yes to "does this text show the candidate has
<term>?"; with no Jev it counts as absent. A requirement backed only by `related` passages is
`partial` with `method: "related"`. A degree requirement (Bachelor's, Master's, PhD) is decided
against the vault's degree passages with `method: "degree"`: covered when the candidate holds that
level or higher, else missing, and Jev's second look skips it.

Jev's second look also covers every soft-skill requirement, a requirement whose soft term only a
self-description or skills list backs, and one only a synonym matched (`related`). A yes adds
`+jev` to the method (`taxonomy+jev`) and reorders `passages`: real bullets Jev agreed with first,
most confident first, then the taxonomy's other finds, then self-descriptions (extra-skills.md)
and skills-list lines. soft-skills.md rows are evidence, ranked as the note they cite.

Pairs in the shared reject list are never matched: a rejected `(term, passage)` pair is left out of
`passages`, `related` and Jev's second look, and `(term, "base")` means the base resumes don't
count as having the term. Jev's answers to the unknown-term question are cached in `jev-cache.json`
by question and text, so a repeated question is answered from the cache (also when Jev is
unreachable).
`jev_said_no` lists every unknown-term match Jev answered no to (`{"term", "passage", "text"}`,
passage `base:<id>` for a base line); `check.md` shows them, with the failed Jev checklist items,
under "Jev said no: check for false rejections". Each failed checklist item is a `- [ ] Reviewed` line
saying what Jev judged (src/tailor/explain.py); checklist items keep `req_id`, `bullet` or `sentence`
so the page can name the requirement, bullet or sentence a question was about. The letter's opening and closing sentences are
checked by two separate Jev questions (`letter.opener`, `letter.closer`), each quoting its sentence.

### `plan.json`

Code part (`run_base`): `{"base_id", "base_scores": {base: current_pct}, "reachable_pct": potential_pct of the chosen base, "jev_pick": base|null,
"bullet_relevance": {"experience/algaecal/algaecal.sql-daily": 3}, "candidate_passages": [ids],
"protected_paths": [paths that are the only cover for a matched must-have]}`.
Claude adds: `{"headline": "...|null", "summary_angle": "...", "swap_in": [passage ids],
"swap_out": [paths], "skills_order": [group ids], "evidence_drops": [{"term", "passage", "reason"}]}`.
`evidence_drops` lists matches Claude read and rejected (passage `"base"` for an accidental match
in the base resume); `check.md` shows them. `apply-edits` copies them into the skill record's
`not_shown` list (`{"term", "passage", "reason", "job_id", "added", "undone"?}`, see below),
so later jobs skip them, and `grade` leaves rejected passages out of its repair notes. In `check.md`
each drop is a `- [ ] Set aside  - [ ] Undo` line in plain words (exactly one must be ticked before
`approve`), ending in `<!-- undo: term | passage -->` (the pair
`approve` reads), with the passage quoted and "first set aside on this job" when this job added it;
ticking Undo and running `approve` marks that entry `undone`, which stops it applying and keeps it
from being re-added, and records the pair as a candidate confirm (below).

Claude may also add `"evidence_adds": [{"term", "passage", "reason"}]`: a claim passage that plainly
shows a skill the matching missed, with `term` the skill's name (the taxonomy name, not the
posting's sentence). The term then counts as backed for this application (`grade` adds it to the
evidence it scores against), and `apply-edits` copies it into the skill record's `has` list.

### The skill record: `skill-record.json`

One file every application reads and adds to: `{"has": [...], "lacks": [...], "not_shown": [...]}`.
It is the only record of which skills the candidate has; the taxonomy lists which skills exist and
the vault holds the stories. The tier score reads it too (`score.vault_gaps.record`,
`src/vault_gaps.py`): a tool with a `jake` or `plan` entry in `has` counts as one Jake has even if
no passage names it, a tool in `lacks` never counts, and a `not_shown` pair stops that passage
counting for that tool. Before the record existed the three lists were `evidence-confirms.json`,
`known-gaps.json` and `evidence-rejects.json` in the same folder; they are read once while
`skill-record.json` doesn't exist, and the first save writes all three into it.

#### `has`: confirmed matches

`[{"term", "passage", "source": "jake|plan|jev", "reason", "job_id", "added", "value"?, "undone"?}]`,
the reverse of `not_shown`. Pairs are keyed by skill: `term` is the
taxonomy name or soft-skill category (`rejects.req_keys` gives a requirement's keys: its terms
plus the soft-skill categories its wording falls under, else its own text), so a passage
confirmed for "collaborate across departments" also counts for "strong team player". Sources:

- `jake`: picked "This shows it" (or "Shows the skill" on a drop) in check.md. Wins over any `not_shown` pair.
- `plan`: the plan's `evidence_adds`. A `not_shown` pair wins over it.
- `jev`: Jev said yes with at least `evidence.jev_remember` (0.8) to a real bullet for a soft
  requirement with exactly one soft-skill key. A `not_shown` pair wins over it. Its stored `value` is reused
  instead of asking Jev again.

In the evidence step a `jake` or `plan` confirm always counts: its passage is put first in the
term's and requirement's `passages`, Jev isn't asked about it, a soft requirement it backs is
`covered` (`method` "confirmed"), and the plan's drops can't re-reject it. A requirement still
missing, or covered only by strength-1 lines, keeps the passages Jev came closest to accepting
(`candidates`: real bullets, value at least `evidence.review_candidate_min`, at most
`evidence.review_candidates`) and the key a pick would confirm (`confirm_key`, omitted when the
requirement mixes skills). `check.md` lists them under "Could these show it?" and the plan's adds
under "Evidence the plan added", each as `- [ ] Doesn't show it  - [ ] This shows it  ...
<!-- confirm: key | passage -->`, an exclusive pair. On `approve`, "This shows it" adds a `jake`
confirm (and undoes a reject of the pair); "Doesn't show it" marks the pair's confirms `undone` and
adds a reject, so it isn't suggested again. Pairs already decided aren't listed.

#### `lacks`: known gaps

`[{"skill", "note"?, "added"}]`: skills the candidate has said they don't have, keyed like
confirms (`rejects.key`, so "node.js" and "Node.js" are one skill). In the evidence step a known
gap's term gets no passages, related passages or base match (a skills-list mention or a plan or
Jev confirm isn't evidence of it), Jev isn't asked about it, and a requirement made only of known
gaps gets no "Could these show it?" candidates. Grade then treats a must made only of known gaps
as a fit gap. A `jake` confirm for the same skill takes it off the list.

### `edits.json` (Claude writes)

```json
{"strategy": "nudge|keywords|full",
 "edits": [{"path": "experience/algaecal/algaecal.sql-daily", "action": "replace",
            "original": "current text", "value": "new text", "reason": "...", "sources": ["algaecal.sql-daily"]}]}
```

Paths: `summary`; `<section>/<entry id>/<bullet id>` for bullets; `<section>/<entry id>` for
`append` (new bullet, id `<entry>.new-<n>`); `skills/<group id>` for `add_skill` / `reorder` / `remove` (the item to drop as `value`);
`<section>/<entry id>` with `action: "reorder"` and a list value of bullet ids. Actions:
`replace | append | remove | reorder | add_skill | add_entry | remove_entry`. `add_entry` on
`experience/<id>` or `projects/<id>` brings in a job or project from the entry library
(`src/tailor/entries.py`: every base's entries plus `materials/resumes/entries.yaml`); code copies its
header, `value` + `sources` is its first bullet, optional `after` places it. `remove_entry` drops a
project (never a job). `reorder` on `projects` orders the projects. **Never editable:** `title, company, location,
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
`requirements.json.company_facts`, counting from 1.

### `check.json`

```json
{"criticals": [{"code": "invented_number", "message": "...", "path": "...", "doc": "resume|letter"}],
 "warnings": [{"code": "...", "message": "...", "path": "...", "doc": "..."}],
 "flags": [{"code": "jev_unsupported", "message": "...", "path": "...", "doc": "...", "source": "jev"}],
 "reverted": ["paths reverted to the base text"],
 "metrics": {"alignment": 0.0, "preservation": 0.0, "baseline": 0.0, "lift": 0.0, "borrowed_rate": 0.0}}
```

Codes are short snake_case strings; the full list lives in `src/tailor/checks.py`. An issue may also
carry `data` (for example `{"term": "R"}`, or `{"first", "second", "added"}` for `jev_citation_gap`),
which `src/tailor/explain.py` uses to write the plain-language line in `check.md`; a new code needs an
entry in its `_ISSUES` table, or check.md falls back to the raw message.

When Jev says a changed line isn't supported by its cited passages, the check asks again with the
related passages the line doesn't cite (same vault entries, the passages sharing each clause's rarest
words). A "yes" then is `jev_citation_gap`: the line's wording was fine, its citations missed the
evidence, and those passages are added to its `sources` in `resume.yaml`, trimmed to the ones Jev needs. A second "no" stays
`jev_unsupported` and names the passages it also saw. The low-similarity revert does the same: a
bullet whose related passages close the gap gets those citations instead of being reverted.

### `grade.json`

```json
{"ats": {"total": 78.0, "components": {"keyword": 80, "skills": 75, "title": 100, "sections": 100, "dates": 100}},
 "checklist": [{"id": "must.r1", "question": "...", "passed": true, "confidence": 0.9, "p_pass": 0.9, "source": "jev|code|unchecked",
                "sections": ["summary", "experience/algaecal"]}],
 "score": 76.2, "stuffing": false, "gaps": [{"id": "must.r1", "sentence": "...", "sections": ["experience/algaecal"]}],
 "feedback": ["Must-have 'dbt' isn't shown; passage resess.pipeline supports it."]}
```

`score` = 0.6 × ATS total + 0.4 × checklist pass rate × 100, where each item counts by `p_pass`
(Jev's probability that it passes, so a 0.51 yes and a 0.49 no weigh about the same; unchecked items
count as passed for the score but are listed). Choosing the best round compares rounds only on the
checklist items every round was asked. In the keyword and skills components a must-have term weighs 1.5, a
boilerplate term 0.25 and a soft skill (taxonomy "Soft skills": communication, teamwork...) 0
(`tailor.ats_soft_weight`), since ATS searches and recruiter filters key on hard skills. `feedback` is built by code from failed items; it never quotes the checklist
question wording.

ATS floor (`tailor.ats_floor`, 70): grade.json also has `ats_floor`, `below_floor`, `ats_ceiling`
(the score if every vault-backed hard term were used in the posting's words, and the job title
when `plan.json` found it truthful as the headline), `ats_target`
(the floor, or the ceiling minus `ats_wording_tolerance` (5) when that is lower), `fit_gap` (the
ceiling is under the floor), `needs_ats_repair` (under the target with backed hard skills unused,
or with the summary not yet opening with the plan's true job title, which an `ats.title` note asks for),
`unused_terms` (backed hard skills not used word for word), `unused_soft_terms` (an `ats.soft`
note that rides along with a repair round, for a line whose story shows them or for the letter;
on its own it starts at most one letter-only round per best round, via `pending`),
`letter_soft_terms` (backed soft skills only the letter names; a letter-only round's feedback lists
them as `keep_soft`, and `next-round` names any the new letter dropped)
and `unbacked_terms` (the posting asks, the vault can't back). Unused hard skills become an
`ats.unused` gap and feedback line. While `needs_ats_repair` holds, `next-round` keeps repairing even
on a small gain (up to the round limit); a fit gap gets no extra rounds, since that would only stuff
keywords. While the best round's ATS is more than `loop.wide_gap` (8) under the ceiling and the last
round raised it, the limit is `loop.max_rounds_wide_gap` (5) drafts. `pending` asks for one more
repair round (feedback `revisit: true`, built on the best round) for an application up for review
whose best round, scored under today's rules, is that far off; and `packet` sets such an
application to needs_fixes with the `wide_gap` flag. Under the floor `check.md` opens with a Reviewed line that blocks `approve`: "Weaker fit"
when the evidence can't reach 70, otherwise "ATS score below 70" (a wording gap).

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
| `grade.py`, `loop.py`, `humanize.py` | steps 6-8 | `run_grade(app_dir, round, cfg, jev)`, `next_round(app_dir, cfg) -> {"action": "stop"|"repair", "best_round", "reason", "next_round"}`, `humanize_flags(app_dir, cfg)`, `humanize_apply(app_dir, cfg)` |
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
