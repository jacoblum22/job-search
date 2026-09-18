# Connecting your Gmail (one-time, ~5 minutes)

This project reads LinkedIn/Indeed/Glassdoor job-alert emails from **your own** Gmail inbox.
Everyone who runs this project connects their own Google account — nothing is shared between
users, and your email contents never leave your machine.

There's no way around a small amount of one-time clicking in Google's own console (Google
requires every app to have its own OAuth client — there's no "just works" option for reading
someone's private Gmail). But there's **no copy-pasting of tokens, codes, or secrets** — the
only manual step is downloading one file. Signing in later is just clicking "Allow" in your
browser.

## 1. Create a Google Cloud project (free, ~2 minutes)

1. Go to [console.cloud.google.com](https://console.cloud.google.com) and sign in with the
   same Google account whose Gmail you want to connect.
2. Click the project dropdown (top left) → **New Project**. Name it anything, e.g.
   "job-aggregator". Create it.
3. Make sure that new project is selected in the dropdown before continuing.

## 2. Enable the Gmail API

1. In the search bar at the top, search **"Gmail API"** and open it.
2. Click **Enable**.

## 3. Configure the OAuth consent screen

1. In the left sidebar: **APIs & Services → OAuth consent screen**.
2. User type: **External** → Create.
3. Fill in the required fields (app name, your email for support/developer contact) — anything
   reasonable works, this is never seen by anyone but you.
4. On the "Test users" step, **add your own Google account's email address**. This keeps the
   app in "Testing" mode, which is all we need — no Google review/verification required, and
   you get up to 100 test users if you ever want more people using this app under your project
   (each person can also just make their own project instead — either works).
5. Save through to the end.

## 4. Create the OAuth client credentials

1. **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
2. Application type: **Desktop app**. Name it anything.
3. Click **Create**, then **Download JSON** on the client you just created.
4. Rename the downloaded file to `credentials.json` and place it in the project root (same
   folder as `pyproject.toml`). This file is already gitignored — it never gets committed.

## 5. Connect your account

From the project root:

```bash
uv run python scripts/gmail_auth.py
```

This opens your browser. Sign in, click **Allow**, and you're done — it saves a `token.json`
locally (also gitignored) and closes. The aggregator will use it automatically from then on,
refreshing itself as needed. You won't need to repeat any of this unless you delete
`token.json` or revoke access.

## If something goes wrong

- **"credentials.json not found"** — you skipped step 4, or it's not named/placed correctly.
- **"access blocked: this app hasn't been verified"** during sign-in — this happens if your own
  email wasn't added as a test user in step 3.4. Go back and add it.
- Revoke access any time at
  [myaccount.google.com/permissions](https://myaccount.google.com/permissions).
