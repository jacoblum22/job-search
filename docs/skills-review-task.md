# Scheduled task: daily skills-list review

The skills list (`src/tailor/taxonomy.py`) only knows the skills someone has
added to it. This task looks for skills that new postings ask for and the list
doesn't know yet. It adds them with tests and opens a pull request into `jake`
for Jake to review and merge. It never merges anything itself.

It runs as Claude Code on Jake's PC, outside the Claude desktop app's sandbox:
the sandbox can't reach GitHub and has no pytest. That means the CLI must be
signed in (`claude` once, interactively). `gh` must also be signed in
(`gh auth status`) for the PR step. Without `gh`, the branch is still pushed
and the log gives the compare link.

## What the wrapper does

`scripts/run_skills_review.ps1`:

1. Fetches `origin/jake` and creates a fresh git worktree at
   `..\job-search-skills-review` on a new branch `skills-review/<date>`. Jake's
   own checkout and uncommitted work are never touched.
2. Copies `jobs.db` to a temp file. SQLite on the live file can lock a
   running scrape.
3. Runs `claude -p` with the prompt below in the worktree. It can read the
   main folder (`--add-dir`), edit files, and run only
   `uv run python ...` / `uv run pytest ...`. It has no git, network or other
   shell access.
4. If the code changed: runs the full test suite. If the tests pass, it
   commits, pushes and opens the PR with the body Claude wrote. If they fail,
   it leaves the worktree in place for a look and pushes nothing.
5. Removes the worktree and logs to `logs\skills_review.log`.

Register it once, daily at 7:30 AM (PowerShell, from the repo root):

```powershell
schtasks /Create /TN "JobSearch-SkillsReview" /SC DAILY /ST 07:30 /F `
  /TR "powershell -NoProfile -ExecutionPolicy Bypass -File `"$PWD\scripts\run_skills_review.ps1`""
```

Run it by hand any time with `.\scripts\run_skills_review.ps1`.

## Prompt

---

You are reviewing my job-search skills list. Today is {DATE}. Your working
folder is a fresh worktree of my repo on branch {BRANCH}. My personal files are
in the main checkout at {MAIN} (read them there). A read-only copy of my job
database is at {DB}.

You may only edit files in this worktree, plus the two files in step 6. Run
Python as `uv run python ...` and tests as `uv run pytest -q ...`. Don't try
git, network or other commands. The wrapper commits and opens the PR.

1. Read `{MAIN}\materials\tailor\skill-review-state.json` if it exists. It
   has `last_run` (a date) and `last_csv_row` (an integer). If it's missing,
   treat every row and every job as new.

2. Gather new terms from two places:
   a. `{MAIN}\materials\tailor\unknown-terms.csv` (term, job_id, date):
      rows after `last_csv_row`.
   b. `{DB}`: jobs with tier A or B, `first_seen` after `last_run`,
      `length(description) >= 1000`, and one per `dedup_group_id`. Read each
      description in full. Note every hard skill (tool, language, platform,
      method, practice, domain knowledge, certification) and soft skill it asks
      for or clearly values.

3. Check each term with the posting's exact wording:
   `uv run python -c "import sys; from src.tailor import taxonomy as t; print(sorted(t.find(sys.argv[1])))" "<wording>"`.
   An empty result means the list doesn't know it. Also note matches that
   are wrong (the term hit an unrelated skill).

4. Keep only real gaps. Skip:
   - company names and the employer's own description
   - benefits and generic duties
   - EEO, hiring-process and privacy boilerplate
   - diversity/inclusion and Indigenous cultural safety wording (my rule:
     employer boilerplate, not skills)
   Group synonyms into one skill.

5. Count postings in `{DB}` (all tiers except skip, full descriptions, one per
   dedup group) that mention each candidate. Add a candidate only if it
   appears in 2+ postings, or in any A-tier posting.

6. For each skill you add, follow the conventions in `src/tailor/taxonomy.py`
   and its comments:
   - one `(category, name, regex)` entry in `T`, in the right category
     section, with a short comment when the regex needs explaining
   - products are their own entries: add them to `RELATED` (their platform)
     and `_TYPES` (their tool type)
   - a non-tool hard skill (a practice, method or concept) also goes in
     `_CONCEPTS` in `src/skill_groups.py`
   - guard false matches: lowercase verbs ("excel at"), short words ("Go",
     "R"), and words that also appear in boilerplate
   - in `tests/test_taxonomy.py`, add at least one real phrase from a posting
     that must match, plus each false-match phrase you guarded against
   You may also fix a wrong match in an existing entry, with a test for the
   fix. Don't rename or remove existing entries.

   Then run `uv run pytest -q tests/test_taxonomy.py tests/test_skill_groups.py tests/test_vault_gaps.py`
   and fix anything you broke.

7. If you added or fixed anything, write `.skills-review-pr.md` in the
   worktree root. It's the PR body, and the wrapper deletes it before
   committing. It should have:
   - a table of added skills with posting counts, example job ids and the
     wording seen
   - fixes to existing entries
   - candidates you skipped, one line each
   - a "Vault evidence" section: for each added skill, the ids of passages in
     `{MAIN}\materials\profile\vault-index.json` whose text `taxonomy.find`
     matches to it. List the skills with no matching passage separately, so I
     can say which ones I have (they need a vault line or a confirmed match,
     or tailoring flags them as missing). Also flag any match where the
     passage only mentions the skill without showing I used it (for example,
     "the Dev team used X")

   Always write two more files:
   - `{MAIN}\materials\tailor\skill-proposals\{DATE}.md`: the same content,
     or a single line saying nothing qualified
   - `{MAIN}\materials\tailor\skill-review-state.json`: today's date and the
     last CSV row number you read

8. End with one line: how many terms and postings you checked and how many
   skills you added or fixed.
