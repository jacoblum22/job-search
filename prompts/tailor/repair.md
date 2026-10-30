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
- `earlier_letters` in feedback.json, when present: letters from earlier rounds that passed a letter
  check the draft you build on now fails (`items` names the checks, `text` is that letter). The
  letter checks only warn, they don't decide which draft wins, so keep the newer draft and repair
  the letter on it. Take what made the earlier letter pass (a sentence that was specific to the
  company, a stronger opener or closer) and bring it back or reword it, as long as it is true and
  fits this draft; don't paste the earlier letter back over a letter that fixed other problems.
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
   Some warnings only ride along with a round that runs anyway; answer them while you are in those
   lines: `ai_phrase` (reword the named phrase plainly, as `humanize.md` describes; a phrase the
   posting uses stays), `keyword_coverage_dropped` (put the named term back in a line in `sections`
   that already says it in the cited passage's words) and `jev_unsupported` (rule 10).
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
   **If nothing in the feedback can be fixed honestly, change nothing.** Write `{"edits": []}`
   and copy the letter unchanged; `next-round` then stops. A word swapped only so the round has
   something to show is worse than no change (October's third drafts mostly changed about five
   words, and rounds that changed nothing won or lost on Jev's coin flips). Say why in a line of
   your notes for the digest.
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

When `feedback.json` has `"review": true`, the round acts on an outside reviewer's notes (the file
named in `feedback.json`'s `notes`: `review/notes.md` for the first pass, `review/pass<N>/notes.md`
for a later pass), written by a reader who never saw the vault or the rules; every pass is a
brand-new reviewer who has not seen earlier drafts or notes. It builds on round `B`, and `sections`
allow the whole resume and the letter. A later reviewer can contradict an earlier one: pick the
advice that makes most sense, use it, and ignore later advice on that topic.

Read every numbered fix and decide, one by one:

- **Act on it** when it is about wording, emphasis, order, what to cut, or evidence the vault
  already shows: a clearer summary for this role, the posting's word for work a cited passage
  describes, a dropped grade or internal name, a filler word cut, the letter's strongest story
  moved up, a closing ask added, resume and letter made to agree. Use the advice sections of
  `resume-edits.md` and `cover-letter.md`.
- **Skip it** (action `"left"`: you decided not to apply that note) when you judge it isn't valid for
  this job. You have the vault, the rules and the posting; the reviewer has none of them, so you
  decide, the way Jake does with his own reviews ("use what's valid, ignore the rest"). Skip a note
  when it is wrong or already true and backed (check the vault: a claim a passage backs is not
  "unverified"), when it asks for something the vault can't back (an outcome number, a tool, a
  result: cut or soften the claim instead, never invent), when it would break the rules file
  (AlgaeCal metrics, dates, titles), or when it conflicts with Jake's habits below. Put the reason in
  `why` in a few words. A reviewer's "[number]" stays out unless a cited passage has that number.
- If you skip every note, write an empty `edits.json` and copy the letter unchanged. The passes then
  stop (nothing left is worth applying); the reasons show in check.md.
- **Check a new skill or tool word before you write it.** The reviewer never saw the vault, so a
  word it suggests may be one the vault doesn't use ("AI agent" for an LLM tool-call loop drew two
  `invented_skill` criticals on Infoblox, Oct 28 2026). Run `uv run python -m src.tailor vault <word>`
  first; if no claim passage words it that way, make the reviewer's point in the vault's words.
- "Questions only you can answer" and "Interview questions" never hold up the passes. When the
  vault, the posting or the rules answer a question (is the Downloader claim true, did he use
  Docker), answer it in `response.json` as `{"question": "...", "answer": "..."}` (the answer is a
  fact from the vault, never a guess); the next reviewer is brand new and never sees it, so also fix
  the resume or letter wherever the answer should show.
  Apply any fix the question was asking for. A question only Jake can answer stays for him on the
  review page; don't guess it.
- **Look it up before you ask him.** When a reviewer wants a fact the vault doesn't hold (does the
  project have CI or logging, how many rows or postings it handles, which tests exist), look in
  the code first: the job-search repo in this folder (workflows, logging calls, tests, the
  database) and Jake's other project repos on GitHub. A fact found there, with the file or query
  that shows it, can be written into the resume or letter and answered in `response.json`. If the
  code can't tell you, answer "I don't know" and leave that detail out; never estimate. Only
  something that lives in his memory (what he did at AlgaeCal, how many of something he traced) is
  Jake's to answer, and it goes on the review page, not into the pass.

**How Jake usually decides on reviewer advice** (his own reviews, Oct 25-28 2026; advice, not
rules, so use judgment):

- Don't name a missing minimum in the letter (years asked vs. his four months). The resume dates
  already show it, and pointing at it hands the screener a reason to stop. Name only a gap the
  letter can bridge in the same sentence (a tool he hasn't used, with the closest one he has).
- Fill a "[number]" or "[N]" from the vault or cut the phrase; never estimate. Use the vault's
  wording ("9+", "about 20", "10+ tables", "several business units"). Keep a "+" when the vault
  says there were more he can't name.
- Keep the posting's title words in the summary's first sentence even when the reviewer suggests
  another opener: the ATS title match depends on it.
- Every sentence in the summary has a verb, and parentheses there name only tools he used, never
  a topic tag like "(data engineering)".
- No test counts ("a pytest suite"): they go stale and read as padding.
- Ownership verbs only for what he did: "fixed both" when he made the fix, "traced the cause" when
  someone else changed it. "Across teams", not "every team".
- A tool he never touched (Spark, dbt, Airflow) never goes in skills or a claim; the letter may
  name it as a gap with a bridge. Docker is coursework only. C is coursework only.
- Unfamiliar product or internal names get a short gloss ("the company's online community on
  Circle") rather than being cut, when the story needs them.
- A letter opener names what the job needs and how his work lines up with it as a whole; a single
  narrow example goes in paragraph 2, not the opener.
- A company figure the reviewer questions: use the wording in `facts.json` or the posting exactly,
  or drop it.

All step-4 grounding rules still apply, and the resume must still fit one page (prefer replacing to
adding). Write `edits.json` (an empty list is fine if nothing for the resume is worth doing) and a
`cover-letter.json` if the letter changes. Then write the file named in `feedback.json`'s
`response` (`review/response.json` for the first pass, `review/pass<N>/response.json` after), one
entry per numbered fix:

```json
[{"note": "Summary names the Loyalty team", "action": "changed", "why": "now says marketing and other business teams"},
 {"note": "Quantify the Apps Script time saved", "action": "left", "why": "no number in the vault"}]
```

`note` is a short plain summary of the reviewer's point; `why` says what changed or why not, in a
few words. Jake reads these in check.md.

## Review fix rounds

When `feedback.json` has `"review_fix": true`, the review round before it added a critical. The
round builds on that review round (`build_on`) and keeps everything it changed; fix only the lines
in `criticals`, the way rule 2 and rule 3 say (use the vault's wording for a skill, cut an unbacked
number), and copy the letter unless a critical is in it. `next-round` then compares this round
with the round the review read (`compare_to`) and keeps it unless a critical is still there.

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
