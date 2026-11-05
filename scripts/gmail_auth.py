"""One-time Gmail connection setup.

Run this once per person/machine using this project:

    uv run python scripts/gmail_auth.py

It opens your browser, you sign into YOUR Google account and click Allow,
and a `token.json` gets saved locally so the aggregator can read your
LinkedIn/Indeed/Glassdoor alert emails from then on. Nothing to copy or
paste. See GMAIL_SETUP.md if `credentials.json` isn't set up yet.
"""

from __future__ import annotations

from src.gmail_client import CREDENTIALS_PATH, TOKEN_PATH, run_auth_flow


def main() -> None:
    print(f"Looking for {CREDENTIALS_PATH.name} ...")
    run_auth_flow()
    print(f"Connected. Saved {TOKEN_PATH.name} — this project can now read your Gmail alerts.")


if __name__ == "__main__":
    main()
