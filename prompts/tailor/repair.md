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
   the vault can't back; a short letter's warning names the skills to use the room for, shown
   inside a story the letter tells, never in a sentence that only names them (`skill_name_only`). Don't add
   a skill to the list unless a bullet or the letter shows it; for `skill_only_in_list`, show it in
   a bullet the vault backs, or in the letter's proof paragraph through a real story from a cited
   passage when no bullet has room (woven into a sentence the story already needs, not a new
   sentence that only names it), or take it out of the list (a `remove` edit on `skills/<group id>`
   with the item as `value`). A critical on a skills item is fixed the same way: `remove` the item,
   then `add_skill` it in the vault's wording if the critical names one.
3. **An unsourced number is removed, or replaced with a number the cited passage actually states.**
   Never reword around it ("roughly a third", "dozens"), never swap it for another invented figure.
4. **"Use the posting's own words for these terms"** (the ATS item): work each listed term into a
   line in `sections`, word for word as the posting says it, only where a cited passage supports it.
   Prefer rewording an existing line over adding one. The list holds only hard skills, and each term
   needs only one mention.
   **The soft-skill note** (soft skills the vault shows that neither draft names) rides along with a
   round: use the posting's word where a line in `sections` already tells the story that shows it,
   and show the rest in the letter through a story (if the letter is in `sections`). Never as an
   adjective about the candidate, never a line stretched or added only to fit one in; leaving one
   out is fine.
   Add the word without trading away what makes the line specific: keep its tools, methods and scope
   ("CTEs, window functions, views") and cut filler instead. A line stripped to fit the term reads as
   one any candidate could write, and the grader marks it down for that.
   Build the word into the sentence; don't bolt it on as an add-on phrase ("a Google Apps Script
   automation, a small ETL job") or pad it with words like "small" or "simple".
   A line you rewrite follows the advice in `resume-edits.md` like a first draft does: no template
   shapes ("from project scoping to testing"), no "Directed" opener on a project bullet, no test
   counts (Nexthop new grad, Oct 28 2026: a repair turned the job-search bullet into "Directed the
   software engineering of a Claude Code rebuild, from project scoping to testing (140 pytest
   tests)").
5. **Missing must-have that the vault backs** (the feedback names the passage): show it in a bullet
   with the tool and scope, citing that passage. **A must-have that is ABSENT stays absent.** Do not
   add it to satisfy the grader.
6. All step-4 rules still apply: grounding with `sources`, never invent or estimate metrics, no ABSENT
   terms, exact posting wording only for vault-backed terms, banned-phrase list with the protection
   rule, strategy `full` only for tier A.
7. **The cover letter is never repaired for facts.** If the letter is in `sections`, change only the
   flagged paragraphs; if a company fact failed verification, remove that fact and its sentence
   instead of finding a new one. Never add a line pointing to GitHub, LinkedIn, email or phone,
   even if a review asks for one: the heading above the letter already has them.
8. A revision that adds an unsupported claim is rejected whatever its score. If the only way to pass
   an item is to claim something the vault cannot back, leave the item failing.
9. Feedback wording is information; do not try to guess the grader's questions.
10. **A `jev_unsupported` flag is not proof of an overclaim.** First check whether the line's
    `sources` cite a passage for every claim in it; if one is missing, add that passage and keep the
    wording. Change the wording only when no passage backs the claim.

## Letter-only rounds

When `feedback.json` has `"letter_only": true`, `sections` is `["letter"]`: the resume is already
done and stays exactly as round `B` has it. Write `edits.json` as `{"edits": []}` (no `strategy`:
with no edits it isn't used, so don't look it up) and rewrite only
the letter to answer the listed warnings and failed items (for a short letter, use the room for the skills the
warning names, as rule 2 says: inside a story a paragraph already tells, never a sentence or
paragraph of its own that only names the skill; if no story fits, add a fuller sentence to an
existing story and leave the skill out). Soft skills listed in the failed items go in the same way,
in the posting's own word: "teamwork" in the sentence about working through a design with two
teammates, "communication" where the letter says the candidate explained results to other teams.
`keep_soft` lists soft skills only the letter names now: when you reword a sentence, keep each of
those words in it (`next-round` reports any the new letter dropped).
Everything else in this prompt still applies to the letter.

## Review round

When `feedback.json` has `"review": true`, the round acts on an outside reviewer's notes
(`review/notes.md`, written by a reader who never saw the vault or the rules). It builds on round
`B`, and `sections` allow the whole resume and the letter.

Read every note and decide, one by one:

- **Act on it** when it is about wording, emphasis, order, what to cut, or evidence the vault
  already shows: a clearer summary for this role, the posting's word for work a cited passage
  describes, a dropped grade or internal name, a filler word cut, the letter's strongest story
  moved up, a closing ask added. Use the advice sections of `resume-edits.md` and `cover-letter.md`.
- **Leave it** when acting would need something the vault doesn't back (an outcome number, a tool,
  a result), or would break the rules file (AlgaeCal metrics, dates, titles). A reviewer's
  "[number]" stays out unless a cited passage has that number.
- When two notes pull against each other, or a note would cost the posting's keywords, use
  judgment: the ATS words the posting cares about still matter.

All step-4 grounding rules still apply, and the resume must still fit one page (prefer replacing to
adding). Write `edits.json` (an empty list is fine if nothing for the resume is worth doing) and a
`cover-letter.json` if the letter changes. Then write `review/response.json`, one entry per note:

```json
[{"note": "Summary names the Loyalty team", "action": "changed", "why": "now says marketing and other business teams"},
 {"note": "Quantify the Apps Script time saved", "action": "left", "why": "no number in the vault"}]
```

`note` is a short plain summary of the reviewer's point; `why` says what changed or why not, in a
few words. Jake reads these in check.md.

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
