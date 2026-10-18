# Scheduled task: fill in missing job descriptions with Claude in Chrome

LinkedIn (and Indeed/Glassdoor) alert emails give a title and a link but no
description, and the scrape can't fetch those pages over plain HTTP. This task
reads them in Jake's own signed-in Chrome. CareerJet links can't be fetched
over plain HTTP either but open in Chrome. Every other snippet source (Adzuna,
BC Public Service, Job Bank, ...) is filled automatically on every scrape
(src/enrich.py); any page that fetch fails on shows up here as well.

Run it as a scheduled task in the Claude desktop app (it needs Claude in
Chrome and this folder), daily at 6:45 PM, with this folder as the task's
working folder.

## Running unattended

The task must never stop at a permission prompt, since nobody is there to
answer it. `.claude/settings.json` (committed) pre-approves exactly what the
prompt below uses:

- `.venv\Scripts\python.exe scripts\browser_queue.py ...` (PowerShell), the
  only shell command the task runs. Rules match the command text literally,
  so the prompt spells it out and says not to add `cd`; a `cd ...;` prefix
  turns it into a compound command that only gets "Allow once".
- Writing description files under `.browser-queue/` (git-ignored).
- The Claude in Chrome tools for opening, reading, scrolling and closing tabs
  (not form filling, JavaScript or uploads).

Chrome also asks per site. In the Claude in Chrome extension, allow
linkedin.com, ca.indeed.com, glassdoor.ca, jobright.ai, wellfound.com,
jobviewtrack.com and careerjet.ca so it doesn't stop there either.

There's no dashboard step: the dashboard at http://127.0.0.1:8765
(`scripts/serve.py`) reads jobs.db on every page load. New descriptions are
re-scored on the next scrape.

## Prompt

---

In my job-search folder (C:\Users\jacob\job-search), fill in job descriptions
that the scraper couldn't get. Nobody is watching this run, so use only the
commands and tools below, written exactly as shown.

1. Run `.venv\Scripts\python.exe scripts\browser_queue.py list` exactly as
   written, from the job-search folder (it's already the working folder; don't
   add `cd`). It prints up to 15 listings per site (LinkedIn, Indeed,
   Glassdoor, Jobright, Wellfound, CareerJet, plus any other site whose page
   the scraper couldn't load) as JSON. If it prints `[]`, stop and reply "Nothing to fill in
   today."
2. For each listing, open its `url` in a new Chrome tab. Expand the
   description if it's collapsed ("See more" / "Show more") and read the full
   job description: the role, responsibilities, qualifications, pay and
   benefits. Leave out the sidebar, "similar jobs", and the generic company
   blurb.
   - Write the description as Markdown to `.browser-queue\<id>.md` in the
     job-search folder, then run
     `.venv\Scripts\python.exe scripts\browser_queue.py save <id> .browser-queue\<id>.md`.
   - If the posting is closed or removed, has no description, asks for a
     login, or shows a CAPTCHA, "verify you are human", or Cloudflare check,
     run `.venv\Scripts\python.exe scripts\browser_queue.py fail <id>` and
     move on. Never try to solve or get around a CAPTCHA or bot check.
   - CareerJet links (jobviewtrack.com) redirect to a careerjet.ca job page;
     the description is the main article from the title down to "Apply Now"
     (leave out "Similar Jobs"). If a "Verification in progress" screen
     shows, wait about 10 seconds for it to clear on its own, without
     clicking anything; if it doesn't clear, `fail` the listing. A 404 on
     jobviewtrack.com means the link is dead: `fail` it.
   - Read only. Don't click Apply, Save, Follow, Easy Apply, or anything else
     that changes my accounts.
   - Close the tab when you're done with it, and pause a few seconds between
     postings.
3. Reply with how many you filled in, which failed and why (one line each),
   and any that look like a strong fit for an entry-level data science,
   analyst, ML or junior software role in Vancouver or remote Canada. If a
   step was blocked by a permission prompt, name the exact command or tool so
   it can be added to `.claude/settings.json`.
