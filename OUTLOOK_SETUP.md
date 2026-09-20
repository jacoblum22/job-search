# Connecting your Microsoft Outlook (one-time, ~5 minutes)

This project reads LinkedIn/Indeed/Glassdoor job-alert emails from **your own** Outlook
inbox (personal @outlook.com/@hotmail.com/@live.com, or a work/school Microsoft 365
account). Everyone who runs this project connects their own Microsoft account — nothing
is shared between users, and your email contents never leave your machine.

There's no way around a small amount of one-time clicking in Microsoft's own portal
(Microsoft requires every app to have its own registration — there's no "just works"
option for reading someone's private mail). But there's **no copy-pasting of tokens or
secrets** — you'll just enter a short one-time code in your browser.

## 1. Register an app in Azure (free, ~2 minutes)

1. Go to [portal.azure.com](https://portal.azure.com) and sign in with the same
   Microsoft account whose Outlook you want to connect (a free Microsoft account works
   fine — this doesn't require a paid Azure subscription).
2. Search **"App registrations"** in the top search bar → open it → **New registration**.
3. Name it anything, e.g. "job-aggregator".
4. **Supported account types**: choose **"Accounts in any organizational directory and
   personal Microsoft accounts"** (covers both personal @outlook.com/@hotmail.com
   accounts and work/school accounts).
5. Leave "Redirect URI" blank. Click **Register**.

## 2. Enable public client (device code) sign-in

1. In your new app, open **Authentication** in the left sidebar.
2. Scroll to **Advanced settings** → set **"Allow public client flows"** to **Yes** →
   **Save**.

## 3. Add the Mail.Read permission

1. Open **API permissions** in the left sidebar → **Add a permission**.
2. **Microsoft Graph** → **Delegated permissions** → search **Mail.Read** → check it →
   **Add permissions**.
   (Admin consent isn't needed for a personal account reading its own mail. A work/school
   account may need an admin to approve it, depending on org policy.)

## 4. Copy your Application (client) ID

1. Open **Overview** in the left sidebar.
2. Copy the **Application (client) ID** value (a GUID).
3. Add it to your `.env` file in the project root (copy `.env.example` to `.env` first if
   you haven't already):

   ```
   OUTLOOK_CLIENT_ID=<paste the GUID here>
   ```

## 5. Connect your account

From the project root:

```bash
uv run python scripts/outlook_auth.py
```

This prints a short code and a URL (`https://microsoft.com/devicelogin`). Open that URL
in any browser, enter the code, sign in, and approve access — no copy-pasting of tokens.
It saves a `token_outlook.json` locally (gitignored) and the aggregator will use it
automatically from then on, refreshing itself as needed. You won't need to repeat any of
this unless you delete `token_outlook.json` or revoke access.

## If something goes wrong

- **"OUTLOOK_CLIENT_ID is not set"** — you skipped step 4, or `.env` isn't being loaded
  (make sure you're running from the project root).
- **"need admin approval"** during sign-in — some work/school accounts have an admin
  policy blocking third-party apps. Use a personal Microsoft account instead, or ask your
  admin to approve the `Mail.Read` permission for this app.
- Revoke access any time at
  [account.live.com/consent/Manage](https://account.live.com/consent/Manage) (personal
  accounts) or through your organization's admin portal (work/school accounts).
