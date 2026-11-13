You are doing the open check for the daily tailoring run. Today is {DATE}. Job postings can close
before we get to them, and drafting a resume for a closed job wastes the run. You only look at
pages. You never apply, never fill in or submit a form, never log in, and never click anything
that isn't needed to read the posting.

{BROWSER}Read `materials/tailor/open-check/plan.json`. `entries` lists the next jobs in order, each with a
`job_id`, `company`, `title` and `url`. Go through them in that order. For each one:

1. Open its `url` in a new browser tab, read the page text, then close the tab.
2. Decide whether the posting is still taking applications:
   - `closed`: the page itself says so ("no longer accepting applications", "this job has expired",
     "position has been filled", "posting closed", "this job is no longer available", a 404 or
     "page not found" for the posting, or a closing date that has passed), or the posting is gone
     and the site shows a list of other jobs instead.
   - `open`: the page shows the posting with a way to apply and no closed wording.
   - `unknown`: anything else: a login wall, a CAPTCHA or "verification" screen, a blank page, a
     page that didn't load, a site the browser wouldn't open, or a different job than the one
     named. Never click through a login or CAPTCHA, and never solve one.
3. Write `materials/tailor/open-check/<job_id>.json` with the Write tool:
   `{"job_id": <id>, "state": "open" | "closed" | "unknown", "evidence": "<text>"}`.
   For `closed`, `evidence` must quote the exact words from the page that show it is closed;
   without a quote the file is ignored, so when you can't quote it, say `unknown`. For `open` and
   `unknown`, `evidence` is a few words ("Apply button shown", "login wall").

Stop as soon as {LIMIT} jobs are confirmed `open` or `unknown` (the run drafts those first), so you
rarely need every entry. Do not check jobs past that point. Only a certain `closed` removes a job:
if you're not sure, it is `unknown`.

When you finish, reply with one line: how many you checked and which were closed (company and title).
