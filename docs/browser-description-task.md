# Scheduled task: fill in missing job descriptions with Claude in Chrome

LinkedIn (and Indeed/Glassdoor) alert emails give a title and a link but no
description, and the scrape can't fetch those pages over plain HTTP. This task
reads them in Jake's own signed-in Chrome. CareerJet links can't be fetched
over plain HTTP either but open in Chrome. Every other snippet source (Adzuna,
BC Public Service, Job Bank, ...) is filled automatically on every scrape
(src/enrich.py); any page that fetch fails on shows up here as well.

Run it as a scheduled task in the Claude desktop app (it needs Claude in
Chrome and this folder), daily at 6:45 PM, with this folder as the task's
folder.

## Files, not commands

The task only reads and writes files in `.browser-queue/` (git-ignored); it
never runs a command and never touches the database:

- `.browser-queue/queue.json`: what to open. The 9:00 AM run_tailoring.ps1
  run writes it with `.venv\Scripts\python.exe scripts\browser_queue.py sync`
  (after the 7:00 AM Azure scrape, or its own fallback scrape).
- `.browser-queue/<id>.md`: a description the task read.
- `.browser-queue/<id>.fail`: one line on why it couldn't (closed, login,
  CAPTCHA...).

The next `sync` stores those files in the database and moves them to
`.browser-queue/done/<date>/`; the tailoring queue right after it rescores
them. `sync` runs on the desktop, not in the scrape, because the scrape runs
in Azure (docs/azure-scrape-job.md), where this folder doesn't exist.

Why: the desktop app may run the task in a Linux shell with this folder
mounted (that's what happened on Oct 28 2026, when it couldn't run
`.venv\Scripts\python.exe` and filled nothing). That shell has no Windows
Python, and since the move to Azure the database is Postgres, which only
answers from the desktop's own IP. A task that only touches files works the
same in the Linux shell and in a native Windows session, so it can't break
that way again.

Optional, for descriptions on the dashboard the same evening instead of after
the next morning's tailoring run, register a Task Scheduler entry that runs `sync`
at 9:30 PM (PowerShell, from this folder):

```powershell
schtasks /Create /TN "JobSearch-BrowserQueueImport" /SC DAILY /ST 21:30 /F /TR "cmd /c cd /d C:\Users\Nelly\job-search && .venv\Scripts\python.exe scripts\browser_queue.py sync >> logs\browser_queue.log 2>&1"
```

## Running unattended

The task must never stop at a permission prompt, since nobody is there to
answer it. `.claude/settings.json` (committed) pre-approves writing under
`.browser-queue/` and the Claude in Chrome tools for opening, reading,
scrolling and closing tabs (not form filling, JavaScript or uploads).

Chrome also asks per site. In the Claude in Chrome extension, allow
linkedin.com, ca.indeed.com, glassdoor.ca, jobright.ai, wellfound.com,
jobviewtrack.com and careerjet.ca so it doesn't stop there either.

## Prompt

---

In my job-search folder (C:\Users\Nelly\job-search; if you're in a Linux
shell it's the mounted job-search folder), fill in job descriptions that the
scraper couldn't get. Nobody is watching this run. Don't run any shell
commands or scripts: this task only reads and writes files in the
`.browser-queue` folder and uses Chrome.

1. Read `.browser-queue/queue.json`. Its `listings` are up to 15 postings
   per site (LinkedIn, Indeed, Glassdoor, Jobright, Wellfound, CareerJet,
   plus any other site whose page the scraper couldn't load), each with an
   `id` and a `url`. Open only the listings in the file, never more than 15
   from one site in a run. Write each file as soon as you finish that
   posting, so whatever's left waits for the next run. Skip any listing whose `.browser-queue/<id>.md` or
   `.browser-queue/<id>.fail` already exists. If the file is missing, stop and
   say so. If every listing already has a file, the day's list is done:
   reply with when `queue.json` was written (`generated_at`), how many of its
   listings have a `.md` and how many a `.fail`, and the
   `backlog_after_this_list` counts per site (postings still waiting beyond
   today's list), and say tomorrow's list is written at 9 AM. Each day's list
   is at most 15 per site, so a second run the same day does no more. Only
   say there is nothing left to fill when the list is empty and
   `backlog_after_this_list` is empty too.
2. For each listing, open its `url` in a new Chrome tab. Expand the
   description if it's collapsed ("See more" / "Show more") and read the full
   job description: the role, responsibilities, qualifications, pay and
   benefits. Leave out the sidebar, "similar jobs", and the generic company
   blurb.
   - Copy the description into `.browser-queue/<id>.md` word for word, as
     Markdown (keep its headings and bullet lists). Don't summarize, shorten,
     reword or add notes of your own: the tailoring matches the posting's
     exact wording, so a summary loses the keywords it needs.
   - If the posting is closed or removed, has no description, asks for a
     login, or shows a CAPTCHA, "verify you are human", or Cloudflare check,
     write one line saying which to `.browser-queue/<id>.fail` and move on.
     Never try to solve or get around a CAPTCHA or bot check.
   - CareerJet links (jobviewtrack.com) redirect to a careerjet.ca job page;
     the description is the main article from the title down to "Apply Now"
     (leave out "Similar Jobs"). If a "Verification in progress" screen
     shows, wait about 10 seconds for it to clear on its own, without
     clicking anything; if it doesn't clear, write a `.fail` file. A 404 on
     jobviewtrack.com means the link is dead: write a `.fail` file.
   - Read only. Don't click Apply, Save, Follow, Easy Apply, or anything else
     that changes my accounts.
   - Close the tab when you're done with it, and pause a few seconds between
     postings.
3. Reply with how many you filled in, which failed and why (one line each),
   and any that look like a strong fit for an entry-level data science,
   analyst, ML or junior software role in Vancouver or remote Canada. If a
   step was blocked by a permission prompt, name the exact tool so it can be
   added to `.claude/settings.json`.
