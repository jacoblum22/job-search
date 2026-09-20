"""Shared Gmail search/cursor helpers for email-alert source adapters
(LinkedIn/Indeed/Glassdoor — see linkedin_email.py, indeed_email.py, glassdoor_email.py).

Each adapter searches Gmail for messages from one sender, decodes the
message bodies, and hands them back as plain EmailMessage records. Fetching
and cursor-advancing is shared here since all three adapters need the exact
same "only new mail since last run" logic.
"""

from __future__ import annotations

import base64
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from googleapiclient.discovery import Resource

from src.db import get_cursor, set_cursor

logger = logging.getLogger(__name__)

DEFAULT_LOOKBACK_DAYS = 30


@dataclass
class EmailMessage:
    id: str
    subject: str
    internal_date: datetime
    plain_text: str
    html: str


def fetch_new_messages(
    service: Resource,
    conn: sqlite3.Connection,
    *,
    source: str,
    query: str,
) -> list[EmailMessage]:
    """List + fetch messages matching `query` newer than this source's saved cursor.

    The cursor is a Unix timestamp (seconds) stored per source in the
    `source_cursors` table. On success it's advanced to one second past the
    newest message seen, so re-runs don't reprocess the same mail. With no
    cursor yet (first run), looks back DEFAULT_LOOKBACK_DAYS.
    """
    cursor = get_cursor(conn, source)
    after_epoch = (
        int(cursor)
        if cursor
        else int((datetime.now(timezone.utc) - timedelta(days=DEFAULT_LOOKBACK_DAYS)).timestamp())
    )

    full_query = f"{query} after:{after_epoch}"
    logger.info("%s: searching Gmail with %r", source, full_query)

    message_ids: list[str] = []
    page_token = None
    while True:
        resp = (
            service.users()
            .messages()
            .list(userId="me", q=full_query, pageToken=page_token, maxResults=100)
            .execute()
        )
        message_ids.extend(m["id"] for m in resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    messages: list[EmailMessage] = []
    newest_epoch = after_epoch
    for msg_id in message_ids:
        raw = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
        parsed = _parse_message(raw)
        if parsed:
            messages.append(parsed)
            newest_epoch = max(newest_epoch, int(parsed.internal_date.timestamp()))

    if messages:
        set_cursor(conn, source, str(newest_epoch + 1))

    logger.info("%s: fetched %d new message(s)", source, len(messages))
    return messages


def _parse_message(raw: dict) -> EmailMessage | None:
    payload = raw.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    subject = headers.get("subject", "")
    internal_date = datetime.fromtimestamp(int(raw["internalDate"]) / 1000, tz=timezone.utc)

    plain_text, html = _extract_bodies(payload)
    return EmailMessage(
        id=raw["id"], subject=subject, internal_date=internal_date, plain_text=plain_text, html=html
    )


def _extract_bodies(payload: dict) -> tuple[str, str]:
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict) -> None:
        mime_type = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if data:
            decoded = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)).decode(
                "utf-8", errors="replace"
            )
            if mime_type == "text/plain":
                plain_parts.append(decoded)
            elif mime_type == "text/html":
                html_parts.append(decoded)
        for sub in part.get("parts", []) or []:
            walk(sub)

    walk(payload)
    return "\n".join(plain_parts), "\n".join(html_parts)
