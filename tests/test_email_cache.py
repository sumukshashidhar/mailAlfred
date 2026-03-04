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
