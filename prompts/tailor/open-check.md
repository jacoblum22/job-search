You are doing the open check for the daily tailoring run. Today is {DATE}. Job postings can close
before we get to them, and drafting a resume for a closed job wastes the run. You only look at
pages. You never apply, never fill in or submit a form, never log in, and never click anything
that isn't needed to read the posting.

{BROWSER}Read `materials/tailor/open-check/plan.json`. `entries` lists the next jobs in order, each with a
`job_id`, `company`, `title` and `url`. Go through them in that order. For each one:

1. Open its `url` in a new browser tab, read the page text, then close the tab.
2. Decide two things about the posting. First, whether it is still taking applications:
   - `closed`: the page itself says so ("no longer accepting applications", "this job has expired",
     "position has been filled", "posting closed", "this job is no longer available", a 404 or
     "page not found" for the posting, or a closing date that has passed), or the posting is gone
     and the site shows a list of other jobs instead.
   - `open`: the page shows the posting with a way to apply and no closed wording.
   - `unknown`: anything else: a login wall, a CAPTCHA or "verification" screen, a blank page, a
     page that didn't load, a site the browser wouldn't open, or a different job than the one
     named. Never click through a login or CAPTCHA, and never solve one.
   Second, while you have the text open, whether it is an **obvious miss**: you are completely
   certain Jake cannot get this job. That means a must-have he does not have and cannot honestly
   bridge: an employer pedigree ("experience at a leading technology, research, or quantitative
   firm", FAANG, a top-tier lab), a credential (PhD, licence) or a clearance, or a must-have asking
   for {MIN_YEARS} or more years of experience. (Jake has about one year of industry experience, a BSc
   in Computer Science with a data science minor, and is a US citizen living in Canada.) 3 to 5
   years is something he has bridged before, so it never counts. If you would only say "unlikely",
   or a bridge is possible, it is not a miss: doubt means not a miss. A closed posting is `closed`,
   not a miss.
3. Write `materials/tailor/open-check/<job_id>.json` with the Write tool:
   `{"job_id": <id>, "state": "open" | "closed" | "miss" | "unknown", "evidence": "<text>", "why": "<text>"}`.
   For `closed`, `evidence` must quote the exact words from the page that show it is closed;
   without a quote the file is ignored, so when you can't quote it, say `unknown`. For `open` and
   `unknown`, `evidence` is a few words ("Apply button shown", "login wall"). For `miss`,
   `evidence` is the verbatim must-have quoted from the page and `why` is one plain sentence for
   Jake; without both the file is ignored (the job stays). A job that is open and not a miss is
   `open`.

`entries` is every eligible job in rank order, not just the ones the run needs. Keep going down the
list, closed ones and misses included, until {LIMIT} jobs are `open` or `unknown`; then stop and
check no more. Only a certain `closed` or `miss` removes a job: if you're not sure, it is `open` or
`unknown`.

When you finish, reply with one line: how many you checked and which were closed or misses (company and title).
