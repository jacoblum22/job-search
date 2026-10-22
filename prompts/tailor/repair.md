# Step 7: repair round

**Who runs this:** the scheduled Claude session, after `next-round` wrote `drafts/r<N>/feedback.json`.
A repair is a **correction, not a rewrite**. Rule wording adapted from AI Job Hunter (Apache-2.0).

## Purpose

Fix only what failed in the last draft, inside the sections code allows, without breaking what
already passed.

## Inputs to read

- `drafts/r<N>/feedback.json`: `criticals`, `failed_items`, `warnings` (style problems such as a term
  repeated too often, text copied from the posting, or a letter outside 200-300 words), and
  `sections` (the only paths you may change)
- `drafts/r<B>/edits.json` and `drafts/r<B>/cover-letter.json` (the draft you build on), where `B` is
  feedback.json's `build_on`: normally N-1, but when round N-1 made things worse it names the best
  earlier round, and round N-1's changes are dropped
- `drafts/r<B>/check.json` and `grade.json` (for context)
- `evidence.json` (PRESENT / ABSENT), `requirements.json`, the base resume, the vault index, the
  rules file

## Hard rules

1. **Edit only inside `feedback.json.sections`.** Lines you don't edit carry over from the previous
   draft as they are. Do not improve other lines, even ones you dislike.
2. **Fix only the listed items.** Each failed item, critical and warning should be answered by a
   specific change; do not add other changes. For `term_stuffing`, keep the term where it matters
   most and reword the other mentions; for `letter_length`, add or cut a sentence, never a claim
   the vault can't back; a short letter's warning names the skills to use the room for. Don't add
   a skill to the list unless a bullet or the letter shows it; for `skill_only_in_list`, show it in
   a bullet the vault backs, or in the letter's proof paragraph through a real story from a cited
   passage when no bullet has room (woven into a sentence the story already needs, not a new
   sentence that only names it), or take it out of the list.
3. **An unsourced number is removed, or replaced with a number the cited passage actually states.**
   Never reword around it ("roughly a third", "dozens"), never swap it for another invented figure.
4. **"Use the posting's own words for these terms"** (the ATS item): work each listed term into a
   line in `sections`, word for word as the posting says it, only where a cited passage supports it.
   Prefer rewording an existing line over adding one. The list holds only hard skills; don't add soft
   skills (communication, collaboration) to chase the score, and each term needs only one mention.
   Add the word without trading away what makes the line specific: keep its tools, methods and scope
   ("CTEs, window functions, views") and cut filler instead. A line stripped to fit the term reads as
   one any candidate could write, and the grader marks it down for that.
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
10. **A `jev_unsupported` flag is not proof of an overclaim.** First check whether the line's
    `sources` cite a passage for every claim in it; if one is missing, add that passage and keep the
    wording. Change the wording only when no passage backs the claim.

## Output

Write `drafts/r<N>/edits.json` and `drafts/r<N>/cover-letter.json` in the same shapes as steps 4 and
4b. `edits.json` lists only this round's changes, made **against the draft you build on**
(`drafts/r<B>/resume.yaml`, `B` from `build_on`): each `original` is copied from that file, since `apply-edits` starts
from it, not from the base. `cover-letter.json`
is always complete. If the letter is not in `sections`, copy it unchanged.

## Worked example (invented)

`feedback.json`: critical `invented_number` at `experience/northwind/northwind.sql-daily` ("cut report
time by 40%"; no 40% in the cited passage); failed item "Must-have dbt isn't shown; passage
`northwind.pipeline` supports it" in `skills/skills.platforms`; `sections`:
`["experience/northwind/northwind.sql-daily", "skills/skills.platforms"]`.

Repair: a `replace` edit whose `original` is that bullet as `drafts/r1/resume.yaml` has it, changing "cut report time by 40%" to "cut report time" if the passage says
reports got faster without a number (or to the number the passage states); add an `add_skill` edit
for dbt citing `northwind.pipeline`. Nothing else goes in `edits.json`; the rest of the draft carries over.

## Self-check before saving

- [ ] Every change is inside `sections`; everything else is identical to the previous draft.
- [ ] Each critical and failed item is addressed, and nothing else was touched.
- [ ] No number remains that the cited passage does not state; none was reworded around.
- [ ] No ABSENT term was added; no must-have was claimed without a passage.
- [ ] Every `original` in `edits.json` is copied from `drafts/r<B>/resume.yaml` (`B` = `build_on`); `cover-letter.json`
  is complete; both are valid JSON.
