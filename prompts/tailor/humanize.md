# Step 8: humanize flagged lines

**Who runs this:** the scheduled Claude session, at most one call per application, after
`humanize-flags` wrote `humanize/flags.json`. Approach adapted from AI Job Hunter (Apache-2.0).

## Purpose

Patch only the lines that sound AI-written. Everything else in the resume and letter stays exactly as
it is.

## Inputs to read

- `humanize/flags.json`: `[{"path", "text", "reasons": ["banned:leverage", "dash", ...]}]`
- `posting.md` (for exact terms) and the final draft the flags came from
- `evidence.json` (PRESENT / ABSENT)
- The rules file

If `flags.json` is empty, write `[]` to `humanize/patches.json` and stop.

## Hard rules

1. **Patch only flagged paths.** One patch per flagged `path`; a patch for any other path is
   rejected by code.
2. **Never change, add or remove a number.** Every digit sequence in the line must survive exactly.
   Code rejects the patch otherwise.
3. **Keep exact posting terms.** A term that is in the posting (and backed by the vault) stays, even
   if it is on the banned list. The protection rule: a phrase is allowed when it is an exact posting
   term or already in the candidate's own writing. Only change what the flag's `reasons` name.
4. Fix by plain substitution first: a short everyday word for the flagged word ("use" for
   "utilize", "led" for "spearheaded"), remove dashes (use a comma, colon or full stop), cut "-ing"
   tails and "not just X but Y". Keep the meaning, the tools and the scope.
5. **Do not add** any claim, tool, outcome or adjective. A patch may be shorter than the original.
   Do not mention an ABSENT term.
6. Keep the line's rough length and its role in the page; do not make several lines start the same way.
7. Letter paragraphs: keep the `sources`/`company_facts` meaning intact; do not introduce a company
   fact that was not there.
8. The whole pass is reverted if the warning count goes up, so prefer the smallest change that clears
   the flag.

## Output

Write `humanize/patches.json`:

```json
[{"path": "experience/northwind/northwind.sql-daily", "replacement": "new text for the whole line"}]
```

`replacement` is the full new text of the line (not a diff). For a letter paragraph the path is the
one given in `flags.json`.

## Worked example (invented)

Flag: `{"path": "experience/northwind/northwind.dashboards", "text": "Leveraged Tableau dashboards to
streamline reporting for 4 teams", "reasons": ["banned:leveraged", "banned:streamline"]}`.
The posting does not contain either word.

```json
[{"path": "experience/northwind/northwind.dashboards",
  "replacement": "Built Tableau dashboards that simplified reporting for 4 teams"}]
```

"4" is unchanged; no new claim.

## Self-check before saving

- [ ] Only flagged paths are patched, once each.
- [ ] Every number in each replacement is identical to the original line's.
- [ ] Exact posting terms and the candidate's own phrases are untouched.
- [ ] No banned phrase, dash or "-ing" tail left in any replacement.
- [ ] No new claim, tool or ABSENT term.
- [ ] Valid JSON list.
