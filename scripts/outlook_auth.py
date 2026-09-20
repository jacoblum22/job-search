"""One-time Outlook connection setup.

Run this once per person/machine using this project:

    uv run python scripts/outlook_auth.py

It prints a short device code — open the URL it gives you in any browser,
sign into YOUR Microsoft account, and enter the code. A `token_outlook.json`
gets saved locally so the aggregator can read your LinkedIn/Indeed/Glassdoor
alert emails from then on. Nothing to copy or paste besides the short code.
See OUTLOOK_SETUP.md if OUTLOOK_CLIENT_ID isn't set up yet.
"""

from __future__ import annotations

from dotenv import load_dotenv

from src.outlook_client import TOKEN_CACHE_PATH, run_auth_flow


def main() -> None:
    load_dotenv()
    print("Starting Outlook device-code sign-in ...")
    run_auth_flow()
    print(f"Connected. Saved {TOKEN_CACHE_PATH.name} — this project can now read your Outlook alerts.")


if __name__ == "__main__":
    main()
