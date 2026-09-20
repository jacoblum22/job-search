"""Microsoft Outlook (Graph API) client — one OAuth setup per person running this project.

Mirrors gmail_client.py's role: this project never embeds credentials — it
loads whatever local app registration + token cache the local person set up
for themselves via `scripts/outlook_auth.py`. See OUTLOOK_SETUP.md for the
one-time setup steps.

Uses MSAL's device-code flow rather than a local-redirect browser flow: it
needs no redirect URI configuration in Azure, works the same on any machine,
and still involves no copy-pasting of tokens — just a short one-time code
entered at https://microsoft.com/devicelogin.
"""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import msal

# Read-only, least-privilege delegated scope — this project never sends,
# deletes, or modifies mail. Mail.Read covers searching + reading alert emails.
SCOPES = ["Mail.Read"]

GRAPH_BASE = "https://graph.microsoft.com/v1.0"

# "common" accepts both personal Microsoft accounts (outlook.com/hotmail/live)
# and work/school accounts, matching whatever account type the app was
# registered for in OUTLOOK_SETUP.md.
AUTHORITY = "https://login.microsoftonline.com/common"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLIENT_ID = os.environ.get("OUTLOOK_CLIENT_ID", "")
TOKEN_CACHE_PATH = Path(os.environ.get("OUTLOOK_TOKEN_FILE", PROJECT_ROOT / "token_outlook.json"))


def _require_client_id() -> str:
    if not CLIENT_ID:
        raise RuntimeError(
            "OUTLOOK_CLIENT_ID is not set. See OUTLOOK_SETUP.md for how to register your own "
            "free Azure app (each person running this project needs their own client ID)."
        )
    return CLIENT_ID


def _load_cache() -> msal.SerializableTokenCache:
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE_PATH.exists():
        cache.deserialize(TOKEN_CACHE_PATH.read_text(encoding="utf-8"))
    return cache


def _save_cache(cache: msal.SerializableTokenCache) -> None:
    if cache.has_state_changed:
        TOKEN_CACHE_PATH.write_text(cache.serialize(), encoding="utf-8")


def run_auth_flow() -> dict:
    """One-time interactive setup via device code — no local redirect server needed.

    Prints a short code + URL. Visit the URL in any browser, enter the code,
    sign in with YOUR Microsoft account, and this process picks up the result.
    """
    client_id = _require_client_id()
    cache = _load_cache()
    app = msal.PublicClientApplication(client_id, authority=AUTHORITY, token_cache=cache)

    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise RuntimeError(f"Failed to start device flow: {flow}")

    print(flow["message"])
    result = app.acquire_token_by_device_flow(flow)

    if "access_token" not in result:
        raise RuntimeError(f"Sign-in failed: {result.get('error_description', result)}")

    _save_cache(cache)
    return result


def get_access_token() -> str:
    """Return a valid access token, refreshing silently from the token cache if possible.

    Raises RuntimeError with setup instructions if no signed-in account exists yet —
    run `scripts/outlook_auth.py` once first.
    """
    client_id = _require_client_id()
    if not TOKEN_CACHE_PATH.exists():
        raise RuntimeError(
            f"No {TOKEN_CACHE_PATH.name} found. Run `uv run python scripts/outlook_auth.py` "
            "once to connect your Outlook account (see OUTLOOK_SETUP.md)."
        )

    cache = _load_cache()
    app = msal.PublicClientApplication(client_id, authority=AUTHORITY, token_cache=cache)

    accounts = app.get_accounts()
    if not accounts:
        raise RuntimeError(
            f"{TOKEN_CACHE_PATH.name} has no signed-in account. Delete it and run "
            "`uv run python scripts/outlook_auth.py` again."
        )

    result = app.acquire_token_silent(SCOPES, account=accounts[0])
    if not result or "access_token" not in result:
        raise RuntimeError(
            "Stored Outlook session expired and could not silently refresh. Delete "
            f"{TOKEN_CACHE_PATH.name} and run `uv run python scripts/outlook_auth.py` again."
        )

    _save_cache(cache)
    return result["access_token"]


def search_messages(query: str, *, top: int = 25) -> list[dict]:
    """Search the signed-in user's mail via Microsoft Graph's $search.

    `query` follows Graph's search syntax, e.g. 'from:jobalerts-noreply@linkedin.com'.
    Returns raw Graph message resources (id, subject, from, receivedDateTime, body, etc.)
    for adapters (e.g. src/sources/linkedin_email.py, once built) to parse.
    """
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    params = {
        "$search": f'"{query}"',
        "$top": str(top),
        "$select": "id,subject,from,receivedDateTime,bodyPreview,body,webLink",
    }
    response = httpx.get(f"{GRAPH_BASE}/me/messages", headers=headers, params=params, timeout=30)
    response.raise_for_status()
    return response.json().get("value", [])
