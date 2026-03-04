"""Tests for the DuckDB email cache."""

import json
from datetime import datetime, timezone

import duckdb
import pytest

from src.cache import EmailCache
from src.models import Attachment, Email


def _make_email(
    id: str = "msg1",
    thread_id: str = "t1",
    subject: str = "Test",
    sender: str = "alice@example.com",
    **kwargs,
) -> Email:
    return Email(id=id, thread_id=thread_id, subject=subject, sender=sender, **kwargs)


class TestSchemaCreation:
    """Task 2: Schema creation tests."""

    def test_creates_emails_table(self):
        cache = EmailCache(":memory:")
        result = cache._conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = 'emails'"
        ).fetchone()
        assert result is not None
        assert result[0] == "emails"
        cache.close()

    def test_creates_sync_state_table(self):
        cache = EmailCache(":memory:")
        result = cache._conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_name = 'sync_state'"
        ).fetchone()
        assert result is not None
        assert result[0] == "sync_state"
        cache.close()

    def test_emails_table_has_expected_columns(self):
        cache = EmailCache(":memory:")
        rows = cache._conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'emails' ORDER BY ordinal_position"
        ).fetchall()
        columns = [row[0] for row in rows]
        expected = [
            "id",
            "thread_id",
            "subject",
            "sender",
            "recipients",
            "cc",
            "bcc",
            "date",
            "message_id",
            "in_reply_to",
            "references",
            "snippet",
            "body_plain",
            "body_html",
            "labels",
            "attachment_meta",
            "cached_at",
        ]
        assert columns == expected
        cache.close()

    def test_context_manager(self):
        with EmailCache(":memory:") as cache:
            result = cache._conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_name = 'emails'"
            ).fetchone()
            assert result is not None


class TestUpsertEmails:
    """Task 3: upsert_emails tests."""

    def test_insert_single_email(self):
        with EmailCache(":memory:") as cache:
            email = _make_email()
            cache.upsert_emails([email])
            row = cache._conn.execute(
                "SELECT id, thread_id, subject, sender FROM emails"
            ).fetchone()
            assert row is not None
            assert row[0] == "msg1"
            assert row[1] == "t1"
            assert row[2] == "Test"
            assert row[3] == "alice@example.com"

    def test_upsert_dedup_by_id(self):
        with EmailCache(":memory:") as cache:
            email1 = _make_email(id="msg1", subject="Original")
            cache.upsert_emails([email1])

            email2 = _make_email(id="msg1", subject="Updated")
            cache.upsert_emails([email2])

            count = cache._conn.execute(
                "SELECT COUNT(*) FROM emails"
            ).fetchone()[0]
            assert count == 1

            subject = cache._conn.execute(
                "SELECT subject FROM emails WHERE id = 'msg1'"
            ).fetchone()[0]
            assert subject == "Updated"

    def test_insert_multiple_emails(self):
        with EmailCache(":memory:") as cache:
            emails = [_make_email(id=f"msg{i}") for i in range(5)]
            cache.upsert_emails(emails)

            count = cache._conn.execute(
                "SELECT COUNT(*) FROM emails"
            ).fetchone()[0]
            assert count == 5

    def test_attachment_metadata_stored_as_json(self):
        with EmailCache(":memory:") as cache:
            att = Attachment(
                filename="report.pdf",
                mime_type="application/pdf",
                size=1024,
                attachment_id="att123",
                data=b"binary-content",  # should NOT be stored
            )
            email = _make_email(attachments=[att])
            cache.upsert_emails([email])

            raw = cache._conn.execute(
                "SELECT attachment_meta FROM emails WHERE id = 'msg1'"
            ).fetchone()[0]
            meta = json.loads(raw)
            assert len(meta) == 1
            assert meta[0]["filename"] == "report.pdf"
            assert meta[0]["mime_type"] == "application/pdf"
            assert meta[0]["size"] == 1024
            assert meta[0]["attachment_id"] == "att123"
            # Binary data must not appear in the JSON
            assert "data" not in meta[0]

    def test_empty_list_is_noop(self):
        with EmailCache(":memory:") as cache:
            cache.upsert_emails([])
            count = cache._conn.execute(
                "SELECT COUNT(*) FROM emails"
            ).fetchone()[0]
            assert count == 0


class TestSyncState:
    """Task 4: Sync state tests."""

    def test_get_last_sync_date_returns_none_initially(self):
        with EmailCache(db_path=":memory:") as cache:
            assert cache.get_last_sync_date() is None

    def test_update_sync_state_after_upsert(self):
        with EmailCache(db_path=":memory:") as cache:
            dt = datetime(2026, 3, 4, 12, 0, tzinfo=timezone.utc)
            emails = [_make_email(date=dt)]
            cache.upsert_emails(emails)
            cache.update_sync_state()
            last = cache.get_last_sync_date()
            assert last == dt

    def test_sync_state_uses_newest_email_date(self):
        with EmailCache(db_path=":memory:") as cache:
            old = datetime(2026, 1, 1, tzinfo=timezone.utc)
            new = datetime(2026, 3, 4, tzinfo=timezone.utc)
            cache.upsert_emails([
                _make_email(id="old", date=old),
                _make_email(id="new", date=new),
            ])
            cache.update_sync_state()
            assert cache.get_last_sync_date() == new

    def test_count(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([_make_email(id=f"m{i}") for i in range(3)])
            assert cache.count() == 3


class TestGetEmail:
    """Task 5: get_email read-back tests."""

    def test_get_existing_email(self):
        """Verify that ALL 17 fields survive the round-trip through DuckDB."""
        with EmailCache(db_path=":memory:") as cache:
            dt = datetime(2026, 3, 4, 14, 30, 0, tzinfo=timezone.utc)
            att1 = Attachment(
                filename="report.pdf",
                mime_type="application/pdf",
                size=2048,
                attachment_id="att_001",
                data=b"binary-should-not-persist",
            )
            att2 = Attachment(
                filename="photo.jpg",
                mime_type="image/jpeg",
                size=51200,
                attachment_id="att_002",
            )
            original = Email(
                id="msg_full",
                thread_id="thread_42",
                subject="Quarterly Report Q1 2026",
                sender="bob@example.com",
                recipients=["alice@example.com", "charlie@example.com"],
                cc=["manager@example.com"],
                bcc=["audit@example.com"],
                date=dt,
                message_id="<unique-msg-id@example.com>",
                in_reply_to="<prev-msg-id@example.com>",
                references=["<first@example.com>", "<second@example.com>"],
                snippet="Please find attached the quarterly...",
                body_plain="Dear team,\n\nPlease find attached the quarterly report.",
                body_html="<html><body><p>Dear team,</p></body></html>",
                labels=["INBOX", "IMPORTANT", "CATEGORY_UPDATES"],
                attachments=[att1, att2],
            )

            cache.upsert_emails([original])
            retrieved = cache.get_email("msg_full")

            assert retrieved is not None
            assert isinstance(retrieved, Email)

            # Identifiers
            assert retrieved.id == "msg_full"
            assert retrieved.thread_id == "thread_42"

            # Core headers
            assert retrieved.subject == "Quarterly Report Q1 2026"
            assert retrieved.sender == "bob@example.com"
            assert retrieved.recipients == ["alice@example.com", "charlie@example.com"]
            assert retrieved.cc == ["manager@example.com"]
            assert retrieved.bcc == ["audit@example.com"]
            assert retrieved.date == dt

            # Threading headers
            assert retrieved.message_id == "<unique-msg-id@example.com>"
            assert retrieved.in_reply_to == "<prev-msg-id@example.com>"
            assert retrieved.references == ["<first@example.com>", "<second@example.com>"]

            # Body content
            assert retrieved.snippet == "Please find attached the quarterly..."
            assert retrieved.body_plain == "Dear team,\n\nPlease find attached the quarterly report."
            assert retrieved.body_html == "<html><body><p>Dear team,</p></body></html>"

            # Metadata
            assert retrieved.labels == ["INBOX", "IMPORTANT", "CATEGORY_UPDATES"]

            # Attachments — reconstructed from JSON as Attachment objects
            assert len(retrieved.attachments) == 2
            assert isinstance(retrieved.attachments[0], Attachment)

            a1 = retrieved.attachments[0]
            assert a1.filename == "report.pdf"
            assert a1.mime_type == "application/pdf"
            assert a1.size == 2048
            assert a1.attachment_id == "att_001"
            assert a1.data == b""  # binary data not stored

            a2 = retrieved.attachments[1]
            assert a2.filename == "photo.jpg"
            assert a2.mime_type == "image/jpeg"
            assert a2.size == 51200
            assert a2.attachment_id == "att_002"

    def test_get_nonexistent_email_returns_none(self):
        with EmailCache(db_path=":memory:") as cache:
            assert cache.get_email("nonexistent") is None

    def test_get_email_with_defaults(self):
        """Verify an email with all default/empty fields round-trips correctly."""
        with EmailCache(db_path=":memory:") as cache:
            minimal = Email(id="minimal", thread_id="t_min")
            cache.upsert_emails([minimal])
            retrieved = cache.get_email("minimal")

            assert retrieved is not None
            assert retrieved.id == "minimal"
            assert retrieved.thread_id == "t_min"
            assert retrieved.subject == ""
            assert retrieved.sender == ""
            assert retrieved.recipients == []
            assert retrieved.cc == []
            assert retrieved.bcc == []
            assert retrieved.date is None
            assert retrieved.message_id == ""
            assert retrieved.in_reply_to == ""
            assert retrieved.references == []
            assert retrieved.snippet == ""
            assert retrieved.body_plain == ""
            assert retrieved.body_html == ""
            assert retrieved.labels == []
            assert retrieved.attachments == []
