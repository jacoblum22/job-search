# Step 3 (Claude part): plan the angle

**Who runs this:** the scheduled Claude session, one call, after the `base` command has written the
code part of `plan.json`.

## Purpose

Decide, before any editing, how this resume should lean for this posting: the headline, a
one-sentence summary angle, which vault passages to swap in, which base bullets to swap out, and the
order of the skills groups. Code overwrites every employer, title and date from the base, so the
plan cannot change them.

## Inputs to read

- `plan.json` (code part: `base_id`, `base_scores`, `bullet_relevance`, `candidate_passages`,
  `protected_paths`)
- `requirements.json`, `evidence.json`
- The chosen base: `materials/resumes/bases/<base_id>.yaml`
- `materials/profile/vault-index.json` (passage ids and texts)
- The rules file (`materials/docs/tailoring-rules.md`)

## Hard rules

1. **Headline.** Use the posting's job title as the headline only when it is truthful for the
   candidate: the work in the vault is genuinely that kind of work, and it does not imply a level,
   licence or credential the candidate lacks (no "Senior", no "Engineer" for analyst work, and so on).
   Otherwise use the base's own headline (output `null`). Never use the company name in the headline.
2. **`summary_angle`**: one sentence, plain wording, naming the strongest overlap between the
   candidate's real work and the posting's tier-1 requirements. No adjectives about the candidate
   ("passionate", "driven"); no claim that is not in the vault.
3. **`swap_in`**: vault passage ids (from `candidate_passages`) that cover an injectable or partial
   requirement the base does not show. Each must be a `claim` passage that exists in the index.
   Prefer passages for tier-1 and `must` requirements. At most 3.
4. **`swap_out`**: base bullet paths with the lowest `bullet_relevance` that you would replace or
   drop to make room. **Never** list a path in `protected_paths` (it is the only cover for a matched
   must-have). Same count or fewer than `swap_in`.
5. **`skills_order`**: the base's skills group ids, reordered so the groups holding tier-1 and `must`
   terms come first. Use only ids that exist in the base; include all of them exactly once.
6. Do not plan anything for terms in `absent`. They stay out of the resume.
7. Do not touch the code fields already in `plan.json`; read them only.

## Output

Merge these four keys into `plan.json` (keep every existing key unchanged):

```json
{"headline": "Data Analyst | null", "summary_angle": "...",
 "swap_in": ["passage.id"], "swap_out": ["section/entry/bullet-id"],
 "skills_order": ["skills.languages", "skills.tools"]}
```

## Worked example (invented)

Posting: Junior Data Analyst; tier-1 requirements: SQL (must), Power BI dashboards. Base:
`data-analyst`. `evidence.json`: SQL covered, Power BI absent, dbt injectable (passage
`northwind.pipeline`). Candidate has Tableau dashboards but not Power BI.

```json
{"headline": "Data Analyst",
 "summary_angle": "Daily SQL and dashboard work for operations and sales teams, which is the core of this role.",
 "swap_in": ["northwind.pipeline"],
 "swap_out": ["experience/northwind/northwind.slides"],
 "skills_order": ["skills.languages", "skills.bi", "skills.platforms"]}
```

Power BI is not mentioned anywhere: it is in `absent`. "Data Analyst" is truthful because the vault
shows analyst work.

## Self-check before saving

- [ ] Headline is the posting's title only if the vault supports that kind of work, else `null`.
- [ ] `summary_angle` is one sentence with no flattery and no claim outside the vault.
- [ ] Every `swap_in` id exists in the index; no `swap_out` path is in `protected_paths`.
- [ ] `skills_order` lists each base group id exactly once.
- [ ] Nothing from `absent` appears anywhere in the plan.
- [ ] All pre-existing `plan.json` keys are unchanged and the file is valid JSON.
