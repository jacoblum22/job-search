# Scheduled task: fill in missing job descriptions with Claude in Chrome

LinkedIn (and Indeed/Glassdoor) alert emails give a title and a link but no
description, and the scrape can't fetch those pages over plain HTTP. This task
reads them in Jake's own signed-in Chrome. CareerJet links can't be fetched
over plain HTTP either but open in Chrome. Every other snippet source (Adzuna,
BC Public Service, Job Bank, ...) is filled automatically on every scrape
(src/enrich.py); any page that fetch fails on shows up here as well.

Run it as a scheduled task in the Claude desktop app (it needs Claude in
Chrome and this folder), daily at 6:45 PM. Prompt:

---

In my job-search folder (C:\Users\jacob\job-search), fill in job descriptions
that the scraper couldn't get.

1. Run `python3 scripts/browser_queue.py list` (on Windows: `python`). It
   prints up to 15 listings per site (LinkedIn, Indeed, Glassdoor, CareerJet, plus any other site whose page the scraper couldn't load) as JSON. If it prints `[]`, stop and reply
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
3. Run `python3 scripts/browser_queue.py dashboard` to refresh dashboard.html.
4. Reply with how many you filled in, which failed and why (one line each),
   and any that look like a strong fit for an entry-level data science,
   analyst, ML or junior software role in Vancouver or remote Canada.
