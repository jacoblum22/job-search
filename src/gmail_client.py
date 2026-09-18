"""Gmail API client — one OAuth setup per person running this project.

Each user (Jacob, or anyone who clones this repo) authenticates their OWN
Google account, not a shared one. This module never embeds credentials —
it just loads whatever `credentials.json` / `token.json` the local person
set up for themselves via `scripts/gmail_auth.py`. See GMAIL_SETUP.md for
the one-time setup steps.
"""

from __future__ import annotations

import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

# Read-only is the least-privilege scope that covers searching + reading
# alert emails — this project never sends, deletes, or modifies mail.
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_PATH = Path(os.environ.get("GMAIL_CREDENTIALS_FILE", PROJECT_ROOT / "credentials.json"))
TOKEN_PATH = Path(os.environ.get("GMAIL_TOKEN_FILE", PROJECT_ROOT / "token.json"))


def run_auth_flow() -> Credentials:
    """One-time interactive setup: opens the user's browser for them to sign in.

    No copy/pasting — `run_local_server()` spins up a temporary local
    redirect endpoint so the OAuth consent screen sends the result straight
    back to this process.
    """
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"{CREDENTIALS_PATH} not found. See GMAIL_SETUP.md for how to get your own "
            "(each person running this project needs their own — it can't be shared)."
        )

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)
    TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
    return creds


def get_gmail_service() -> Resource:
    """Return an authorized Gmail API client, refreshing the saved token if needed.

    Raises RuntimeError with setup instructions if no token exists yet —
    run `scripts/gmail_auth.py` once first.
    """
    if not TOKEN_PATH.exists():
        raise RuntimeError(
            f"No {TOKEN_PATH.name} found. Run `uv run python scripts/gmail_auth.py` once "
            "to connect your Gmail account (see GMAIL_SETUP.md)."
        )

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                f"{TOKEN_PATH.name} is invalid and has no refresh token. Delete it and run "
                "`uv run python scripts/gmail_auth.py` again."
            )

    return build("gmail", "v1", credentials=creds)
