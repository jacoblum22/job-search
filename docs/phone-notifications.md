# LinkedIn phone notifications → instant tailoring

Jake's Pixel forwards each LinkedIn notification ("you're a top applicant", "matches your
profile", "is hiring") to the desktop. The dashboard server (`scripts/serve.py`) finds the job,
reads its description, applies the normal gates and, if it passes, starts `run_tailoring.ps1 -JobId N`.
Code: `src/phone_notify.py`; endpoint: `POST /api/phone-notify` in `src/server.py`.

## What happens to a notification

1. **Match.** The notification has no link, so the job is found in jobs.db by company and title (both must
   appear in the text; jobs first seen in the last 21 days). Not found yet → retried every minute for 24 h,
   because the LinkedIn alert emails that bring the job in arrive every couple of hours; then dropped.
2. **Description.** If jobs.db only has a snippet, one plain request to LinkedIn's public posting page tries
   to read it (untested from the desktop as of Nov 16 2026; it gives up quietly on any block or login
   wall and never retries or works around it). If that fails the job goes to the front of the Chrome task's queue
   (`.browser-queue/priority.json`, read by `browser_queue.export_queue`). The Chrome task never solves a CAPTCHA.
3. **Gate.** Tier A or B (`tailor.phone_notify.tiers`), description ≥ `min_description_chars`, not closed,
   not dismissed/applied, no application folder yet (also not for another posting of the same job).
4. **Tailor.** Starts `run_tailoring.ps1 -JobId N -NoReview` through the dashboard's `TailoringRunner`, at most
   `daily_cap` (3) a day and never beside another run (it waits). Past the cap the daily run picks the job up.

State per notification: `.phone-inbox/state.json` (git-ignored); the server log (`logs/dashboard.log`) prints a
line each time a notification changes state.

## One-time setup on the desktop

1. Make a secret and put it in `.env` (git-ignored), then restart `serve.py`:

   ```powershell
   $t = -join ((48..57)+(97..122) | Get-Random -Count 32 | % {[char]$_})
   Add-Content .env "`nPHONE_NOTIFY_TOKEN=$t"; $t
   ```

   Keep the printed value for the phone. With no token set the endpoint answers 403 to everything.
2. The dashboard must already be reachable on the tailnet (`tailscale serve --bg 8765`, `serve.py --allow-host
   desktop-cah1a3p.tailc2f034.ts.net`); the same address serves this endpoint.

## One-time setup on the Pixel (MacroDroid, free tier allows 5 macros)

1. Install MacroDroid, give it **Notification access** when it asks. Keep Tailscale connected.
2. New macro:
   - **Trigger:** Notification → Notification Received → Application: LinkedIn → any text.
   - **Action:** Connectivity → HTTP Request:
     - Method `POST`, URL `https://desktop-cah1a3p.tailc2f034.ts.net/api/phone-notify`
     - Header `X-Notify-Token`: the secret from step 1 above
     - Header `Content-Type`: `application/json`
     - Body: `{"title": "<notification title>", "text": "<notification text>"}`; use the **{…} magic text** picker
       to insert the notification title and text where the placeholders are.
   - **Constraint (optional):** none needed; messages and invitations are ignored because they match no job.
3. Test: tap the macro's **Test actions**, or ask LinkedIn for a test notification. A line starting
   `phone-notify` should appear in `logs/dashboard.log`, and `.phone-inbox/inbox.jsonl` gets the text.

## Limits

- The phone sends only what the notification shows. A notification that names a company or title differently
  from the posting may not match; it is dropped after 24 h and the daily run still finds the job normally.
- The desktop and `serve.py` must be running. A notification that arrives while they are off is lost
  (the Gmail alert emails still bring the job in).
