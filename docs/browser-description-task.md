# Scheduled task: fill in missing job descriptions with Claude in Chrome

LinkedIn (and Indeed/Glassdoor) alert emails give a title and a link but no
description, and the scrape can't fetch those pages over plain HTTP. This task
reads them in Jake's own signed-in Chrome. Adzuna is filled automatically on
every scrape (src/enrich.py); Adzuna links that failed there also show up here.
CareerJet is excluded on purpose: its links sit behind a Cloudflare bot check.

Run it as a scheduled task in the Claude desktop app (it needs Claude in
Chrome and this folder), daily at 6:45 PM. Prompt:

---

In my job-search folder (C:\Users\jacob\job-search), fill in job descriptions
that the scraper couldn't get.

1. Run `python3 scripts/browser_queue.py list` (on Windows: `python`). It
   prints up to 15 listings as JSON. If it prints `[]`, stop and reply
   "Nothing to fill in today."
2. For each listing, open its `url` in a new Chrome tab. Expand the
   description if it's collapsed ("See more" / "Show more") and read the full
   job description: the role, responsibilities, qualifications, pay and
   benefits. Leave out the sidebar, "similar jobs", and the generic company
   blurb.
   - Write the description as Markdown to a temporary file and run
     `python3 scripts/browser_queue.py save <id> <file>`.
   - If the posting is closed or removed, has no description, asks for a
     login, or shows a CAPTCHA, "verify you are human", or Cloudflare check,
     run `python3 scripts/browser_queue.py fail <id>` and move on. Never try
     to solve or get around a CAPTCHA or bot check.
   - Read only. Don't click Apply, Save, Follow, Easy Apply, or anything else
     that changes my accounts.
   - Close the tab when you're done with it, and pause a few seconds between
     postings.
3. Run `python3 scripts/browser_queue.py dashboard` to refresh dashboard.html.
4. Reply with how many you filled in, which failed and why (one line each),
   and any that look like a strong fit for an entry-level data science,
   analyst, ML or junior software role in Vancouver or remote Canada.
