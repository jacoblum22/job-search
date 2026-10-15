"""Shared Gmail/Outlook search/cursor helpers for email-alert source adapters
(LinkedIn/Indeed/Glassdoor — see linkedin_email.py, indeed_email.py, glassdoor_email.py).

Each adapter searches mail for messages from one sender, decodes the
message bodies, and hands them back as plain EmailMessage records. Fetching
and cursor-advancing is shared here since all three adapters need the exact
same "only new mail since last run" logic.
"""

from __future__ import annotations

import base64
import logging
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

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


def collect_alert_messages(
    conn: sqlite3.Connection,
    *,
    source: str,
    query: str,
) -> list[EmailMessage]:
    """Load new alert mail from Gmail and/or Outlook, whichever is configured.

    Previously the aggregator bailed on all three adapters if Gmail OAuth was
    missing, even when Outlook was set up (or vice versa). Each mailbox has
    its own cursor (`{source}:gmail` / `{source}:outlook`).
    """
    messages: list[EmailMessage] = []
    try:
        from src.gmail_client import get_gmail_service

        service = get_gmail_service()
        messages.extend(
            fetch_new_messages(service, conn, source=f"{source}:gmail", query=query)
        )
    except (RuntimeError, FileNotFoundError) as exc:
        logger.warning("%s: Gmail skipped (%s)", source, exc)

    try:
        messages.extend(
            fetch_new_outlook_messages(conn, source=f"{source}:outlook", query=query)
        )
    except RuntimeError as exc:
        logger.warning("%s: Outlook skipped (%s)", source, exc)

    if not messages:
        logger.info("%s: no new messages from Gmail or Outlook", source)
    return messages


def fetch_new_messages(
    service: Resource,
    conn: sqlite3.Connection,
    *,
    source: str,
    query: str,
) -> list[EmailMessage]:
    """List + fetch Gmail messages matching `query` newer than this source's cursor.

    The cursor is a Unix timestamp (seconds) stored per source in the
    `source_cursors` table. On success it's advanced to one second past the
    newest message seen, so re-runs don't reprocess the same mail. With no
    cursor yet (first run), looks back DEFAULT_LOOKBACK_DAYS.
    """
    cursor = get_cursor(conn, source)
    after_epoch = (
        int(cursor)
        if cursor
        else int((datetime.now(UTC) - timedelta(days=DEFAULT_LOOKBACK_DAYS)).timestamp())
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
        parsed = _parse_gmail_message(raw)
        if parsed:
            messages.append(parsed)
            newest_epoch = max(newest_epoch, int(parsed.internal_date.timestamp()))

    if messages:
        set_cursor(conn, source, str(newest_epoch + 1))

    logger.info("%s: fetched %d new message(s)", source, len(messages))
    return messages


def fetch_new_outlook_messages(
    conn: sqlite3.Connection,
    *,
    source: str,
    query: str,
) -> list[EmailMessage]:
    """Same cursor semantics as Gmail, against Microsoft Graph `$search`."""
    import httpx

    from src.outlook_client import GRAPH_BASE, get_access_token

    cursor = get_cursor(conn, source)
    after_epoch = (
        int(cursor)
        if cursor
        else int((datetime.now(UTC) - timedelta(days=DEFAULT_LOOKBACK_DAYS)).timestamp())
    )
    after_dt = datetime.fromtimestamp(after_epoch, tz=UTC)

    token = get_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "ConsistencyLevel": "eventual",
    }
    params: dict[str, str] | None = {
        "$search": f'"{query}"',
        "$top": "50",
        "$select": "id,subject,receivedDateTime,body,bodyPreview",
    }
    url: str | None = f"{GRAPH_BASE}/me/messages"
    logger.info("%s: searching Outlook with %r", source, query)

    messages: list[EmailMessage] = []
    newest_epoch = after_epoch
    while url:
        resp = httpx.get(url, headers=headers, params=params, timeout=60.0)
        resp.raise_for_status()
        data = resp.json()
        params = None
        for raw in data.get("value") or []:
            parsed = _parse_outlook_message(raw)
            if not parsed or parsed.internal_date <= after_dt:
                continue
            messages.append(parsed)
            newest_epoch = max(newest_epoch, int(parsed.internal_date.timestamp()))
        url = data.get("@odata.nextLink")

    if messages:
        set_cursor(conn, source, str(newest_epoch + 1))

    logger.info("%s: fetched %d new Outlook message(s)", source, len(messages))
    return messages


def _parse_gmail_message(raw: dict) -> EmailMessage | None:
    payload = raw.get("payload", {})
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    subject = headers.get("subject", "")
    internal_date = datetime.fromtimestamp(int(raw["internalDate"]) / 1000, tz=UTC)

    plain_text, html = _extract_bodies(payload)
    return EmailMessage(
        id=raw["id"], subject=subject, internal_date=internal_date, plain_text=plain_text, html=html
    )


def _parse_outlook_message(raw: dict) -> EmailMessage | None:
    received = raw.get("receivedDateTime") or ""
    try:
        internal_date = datetime.fromisoformat(received.replace("Z", "+00:00"))
    except ValueError:
        return None
    if internal_date.tzinfo is None:
        internal_date = internal_date.replace(tzinfo=UTC)

    body = raw.get("body") or {}
    content = body.get("content") or ""
    content_type = (body.get("contentType") or "").lower()
    html = content if content_type == "html" else ""
    plain = content if content_type != "html" else (raw.get("bodyPreview") or "")
    return EmailMessage(
        id=str(raw.get("id") or ""),
        subject=raw.get("subject") or "",
        internal_date=internal_date,
        plain_text=plain,
        html=html,
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
