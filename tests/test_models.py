from dataclasses import fields

from src.models import Email


def test_email_required_fields():
    email = Email(id="abc123", thread_id="thread1", subject="Hello", sender="alice@example.com")
    assert email.id == "abc123"
    assert email.thread_id == "thread1"
    assert email.subject == "Hello"
    assert email.sender == "alice@example.com"


def test_email_default_fields():
    email = Email(id="abc123", thread_id="thread1", subject="Hello", sender="alice@example.com")
    assert email.body_plain == ""
    assert email.snippet == ""
    assert email.date is None
    assert email.labels == []


def test_email_custom_fields():
    email = Email(
        id="abc123",
        thread_id="thread1",
        subject="Meeting",
        sender="bob@example.com",
        body_plain="Let's meet at 3pm",
        snippet="Let's meet...",
        date="2026-03-04T10:00:00Z",
        labels=["INBOX", "UNREAD"],
    )
    assert email.body_plain == "Let's meet at 3pm"
    assert email.snippet == "Let's meet..."
    assert email.date == "2026-03-04T10:00:00Z"
    assert email.labels == ["INBOX", "UNREAD"]


def test_email_labels_no_shared_default():
    """Ensure each Email gets its own labels list (no mutable default sharing)."""
    a = Email(id="1", thread_id="t1", subject="A", sender="a@a.com")
    b = Email(id="2", thread_id="t2", subject="B", sender="b@b.com")
    a.labels.append("INBOX")
    assert b.labels == []
