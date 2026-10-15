from datetime import timezone

from src.sources.email_common import _parse_outlook_message


def test_parse_outlook_html_body():
    msg = _parse_outlook_message(
        {
            "id": "abc",
            "subject": "Your jobs",
            "receivedDateTime": "2026-09-30T12:00:00Z",
            "body": {"contentType": "html", "content": "<p>Hello</p>"},
            "bodyPreview": "Hello",
        }
    )
    assert msg is not None
    assert msg.id == "abc"
    assert msg.html == "<p>Hello</p>"
    assert msg.internal_date.tzinfo is not None
    assert msg.internal_date.tzinfo == timezone.utc or msg.internal_date.utcoffset() is not None
