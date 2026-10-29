# Post-run review: fix what the tailoring run tripped over

After the daily tailoring run (`docs/tailoring-runbook.md`) finishes, a second
Claude Code session reads that run's log and looks for problems in the pipeline
itself: commands that failed or were denied, checks that disagreed or flagged a
true claim, steps the run had to work around, rules a draft broke. It fixes the
clear bugs in a fresh worktree, with tests, and the wrapper opens a pull request
into `jake`. It never merges, never touches personal materials, and never
changes the drafted applications. Anything that needs Jake's judgment goes in a
notes file instead of code.

It runs as Claude Code on Jake's PC (same sign-in as the tailoring run). `gh`
must be signed in (`gh auth status`) for the PR step; without it the branch is
still pushed and the log gives the compare link.

## What the wrapper does

`scripts/run_tailoring_review.ps1 -Transcript <run.jsonl>` (called by
`scripts/run_tailoring.ps1` at the end of every run that tailored something):

1. Turns the transcript into a readable log with
   `scripts/transcript_summary.py` (one line per command, results cut short).
2. Fetches `origin/jake` and creates a fresh git worktree at
   `..\job-search-run-review` on a new branch `run-review/<date>_<time>`.
   Jake's checkout is never touched.
3. Runs `claude -p` with the prompt below in the worktree. It can read the
   main folder (`--add-dir`), edit code, prompts, docs, config and tests in
   the worktree, and run `uv run pytest` and `uv run python -c`. No git,
   network, connectors or other shell commands.
4. If code changed: runs the full test suite. If it passes, commits, pushes
   and opens the PR with the body Claude wrote. If it fails, pushes nothing
   and leaves the worktree for a look.
5. Appends the review's problems, by area, to `materials\tailor\run-reviews\tally.csv`
   (`scripts/review_tally.py`; `show` prints the trend), and gives the next review
   the trend so it can tell a recurring area from a new one.
6. Saves the session's transcript to `logs\tailoring\review_<date>_<time>.jsonl`,
   copies Claude's notes to `materials\tailor\run-reviews\<date>_<time>.md`,
   removes the worktree and logs to `logs\tailoring_review.log`.

Run it by hand on any past run:

```powershell
.\scripts\run_tailoring_review.ps1 -Transcript logs\tailoring\2026-10-20_0139.jsonl
```

## Prompt

<!-- prompt start -->

You are reviewing today's unattended tailoring run for my job-search repo and
fixing the pipeline where it went wrong. Today is {DATE}. Your working folder is
a fresh worktree of my repo on branch {BRANCH}; edit code there. My main
checkout, with my personal files and the run's output, is at {MAIN} (read only).

**What to read**

1. `{SUMMARY}`: the run's log, one entry per command with its result
   (cut short), errors and denied commands marked, and the final digest. A parallel run has one
   section per Claude session ("# Session 1 of 3: ..."), each with its own digest; sessions ran at
   the same time, so look across all of them.
2. `docs/tailoring-runbook.md` (the prompt the run followed) and
   `{MAIN}\materials\docs\tailoring-rules.md` (my binding writing rules).
3. `{TALLY}`: what earlier reviews found, counted by area. An area that keeps coming back
   means the earlier fixes were patches.
4. For each application folder the digest names, under
   `{MAIN}\materials\applications\`: `check.md`, the best round's
   `drafts\r<N>\check.json`, `grade.json` and `applied.json`, `fit-notes.md`,
   and the final resume and letter text.
5. The code, prompts and tests behind anything that looks wrong.

**What counts as a problem**

- A command that failed, was denied, or was retried; a step the run had to
  work around by hand or skipped.
- Two parts of the pipeline disagreeing (for example the check calling a term
  invented while the grade lists it as backed).
- A check flagging something true, or missing something false, in the drafts.
- A draft breaking a rule in the rules file that a check should have caught.
- Wasted work: steps repeated for no reason, needless rounds, oversized output.
- The runbook or a prompt telling the run something wrong or unclear.

**How to fix**

- Fix the root cause, not the instance: ask why it happened and whether it
  would happen on other jobs, then fix the code, check or prompt so it can't.
  Don't special-case one job, company or wording.
- Fix it once, where every step shares it. Wording comparisons go through
  `src/tailor/wording.py` (evidence, the check and the grade all use it); a
  new variant (plural, spelling, hyphen) is fixed there, never with another
  matcher in one step. If the tally shows the area before, say in the notes
  why the earlier fix didn't hold and fix the shared cause.
- Prefer code over prompt wording for rules the run must follow: a prompt can
  be ignored, a check can't.
- Fix only clear bugs, each with a test that fails without the fix. Keep each
  diff small and match the surrounding code's style. At most 5 fixes per run;
  list the rest in the notes.
- Never make a truth check (invented skills, numbers, employers, sources)
  more lenient just to clear a flag, unless the flag was plainly wrong about
  what the vault says, and say which passage proves it.
- Policy or judgment calls (scoring weights, what counts as a skill I have,
  how strict a rule is, anything in the rules file or the vault) are mine:
  put them in the notes as a question, don't change them.
- Don't edit anything under `{MAIN}`. Don't redo or change the applications.
- Run `uv run pytest -q` before you finish and fix anything you broke.
- Don't run git in any form, including from Python: leave your changes uncommitted.
  The wrapper runs the tests, commits, pushes and opens the PR.

**The repo is public.** Commit content, tests, code comments and the PR body
must not contain my resume or letter text, vault passages, contact details or
anything else from `materials/`. Company and job titles are fine. Tests use
invented examples like the existing fixtures do.

**Output** (in the worktree root; the wrapper moves them):

- `.run-review-pr.md`, only if you changed code: the PR body. Start with a
  "Before:" paragraph and an "After:" paragraph in plain language, then one
  short section per fix: what went wrong in the run (the command or check),
  the root cause, the fix and its test. End with problems found but not
  fixed, one line each.
- `.run-review-tally.json`, always: a JSON list with one entry per problem,
  `{"area": ..., "status": "fixed" | "left" | "question", "problem": "<one line>"}`.
  Areas: wording-match, job-selection, company-research, resume-check, letter,
  ats-grade, repair-loop, review-file, runbook-prompt, tooling, other.
- `.run-review-notes.md`, always: what you checked, each problem found
  (fixed, left for later, or a question for me), and anything in the drafts I
  should look at before sending. Personal details are fine here; this file
  stays on my PC.

End with one line: how many problems you found and how many you fixed.

<!-- prompt end -->
