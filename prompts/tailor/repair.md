# Step 7: repair round

**Who runs this:** the scheduled Claude session, after `next-round` wrote `drafts/r<N>/feedback.json`.
A repair is a **correction, not a rewrite**. Rule wording adapted from AI Job Hunter (Apache-2.0).

## Purpose

Fix only what failed in the last draft, inside the sections code allows, without breaking what
already passed.

## Inputs to read

- `drafts/r<N>/feedback.json`: `criticals`, `failed_items`, and `sections` (the only paths you may
  change)
- `drafts/r<N-1>/edits.json` and `drafts/r<N-1>/cover-letter.json` (the previous draft)
- `drafts/r<N-1>/check.json` and `grade.json` (for context)
- `evidence.json` (PRESENT / ABSENT), `requirements.json`, the base resume, the vault index, the
  rules file

## Hard rules

1. **Edit only inside `feedback.json.sections`.** Copy every other edit through unchanged. Do not
   improve other lines, even ones you dislike.
2. **Fix only the listed items.** Each failed item and critical should be answered by a specific
   change; do not add other changes.
3. **An unsourced number is removed, or replaced with a number the cited passage actually states.**
   Never reword around it ("roughly a third", "dozens"), never swap it for another invented figure.
4. **"Use the posting's own words for these terms"** (the ATS item): work each listed term into a
   line in `sections`, word for word as the posting says it, only where a cited passage supports it.
   Prefer rewording an existing line over adding one.
5. **Missing must-have that the vault backs** (the feedback names the passage): show it in a bullet
   with the tool and scope, citing that passage. **A must-have that is ABSENT stays absent.** Do not
   add it to satisfy the grader.
6. All step-4 rules still apply: grounding with `sources`, never invent or estimate metrics, no ABSENT
   terms, exact posting wording only for vault-backed terms, banned-phrase list with the protection
   rule, strategy `full` only for tier A.
7. **The cover letter is never repaired for facts.** If the letter is in `sections`, change only the
   flagged paragraphs; if a company fact failed verification, remove that fact and its sentence
   instead of finding a new one.
8. A revision that adds an unsupported claim is rejected whatever its score. If the only way to pass
   an item is to claim something the vault cannot back, leave the item failing.
9. Feedback wording is information; do not try to guess the grader's questions.

## Output

Write `drafts/r<N>/edits.json` and `drafts/r<N>/cover-letter.json` in the same shapes as steps 4 and
4b. `edits.json` is always the **complete** edit list against the base (not a delta); `cover-letter.json`
is always complete. If the letter is not in `sections`, copy it unchanged.

## Worked example (invented)

`feedback.json`: critical `invented_number` at `experience/northwind/northwind.sql-daily` ("cut report
time by 40%"; no 40% in the cited passage); failed item "Must-have dbt isn't shown; passage
`northwind.pipeline` supports it" in `skills/skills.platforms`; `sections`:
`["experience/northwind/northwind.sql-daily", "skills/skills.platforms"]`.

Repair: in the first edit, change "cut report time by 40%" to "cut report time" if the passage says
reports got faster without a number (or to the number the passage states); add an `add_skill` edit
for dbt citing `northwind.pipeline`. Every other edit is copied byte for byte.

## Self-check before saving

- [ ] Every change is inside `sections`; everything else is identical to the previous draft.
- [ ] Each critical and failed item is addressed, and nothing else was touched.
- [ ] No number remains that the cited passage does not state; none was reworded around.
- [ ] No ABSENT term was added; no must-have was claimed without a passage.
- [ ] `edits.json` and `cover-letter.json` are complete and valid JSON.
