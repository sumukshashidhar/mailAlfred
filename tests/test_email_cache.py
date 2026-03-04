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
            "organized",
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


class TestGetEmailThread:
    """Thread retrieval by thread_id."""

    def test_returns_all_emails_in_thread(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", thread_id="t1", subject="First",
                            date=datetime(2026, 3, 1, tzinfo=timezone.utc)),
                _make_email(id="m2", thread_id="t1", subject="Reply",
                            date=datetime(2026, 3, 2, tzinfo=timezone.utc)),
                _make_email(id="m3", thread_id="t2", subject="Other thread"),
            ])
            thread = cache.get_email_thread("t1")
            assert len(thread) == 2
            assert {e.id for e in thread} == {"m1", "m2"}

    def test_ordered_chronologically_oldest_first(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="reply", thread_id="t1",
                            date=datetime(2026, 3, 3, tzinfo=timezone.utc)),
                _make_email(id="original", thread_id="t1",
                            date=datetime(2026, 3, 1, tzinfo=timezone.utc)),
            ])
            thread = cache.get_email_thread("t1")
            assert [e.id for e in thread] == ["original", "reply"]

    def test_nonexistent_thread_returns_empty(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([_make_email(id="m1", thread_id="t1")])
            assert cache.get_email_thread("nonexistent") == []

    def test_single_email_thread(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([_make_email(id="m1", thread_id="t1")])
            thread = cache.get_email_thread("t1")
            assert len(thread) == 1
            assert thread[0].id == "m1"


class TestGetEmailsFromSender:
    """Sender lookup with ILIKE partial matching."""

    def test_matches_by_email_address(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", sender="alice@example.com"),
                _make_email(id="m2", sender="bob@example.com"),
            ])
            results = cache.get_emails_from_sender("alice@example.com")
            assert len(results) == 1
            assert results[0].id == "m1"

    def test_matches_display_name_format(self):
        """Should match 'alice@example.com' even when stored as 'Alice <alice@example.com>'."""
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", sender="Alice Smith <alice@example.com>"),
                _make_email(id="m2", sender="bob@other.com"),
            ])
            results = cache.get_emails_from_sender("alice@example.com")
            assert len(results) == 1
            assert results[0].id == "m1"

    def test_case_insensitive(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", sender="Alice@Example.COM"),
            ])
            results = cache.get_emails_from_sender("alice@example.com")
            assert len(results) == 1

    def test_ordered_newest_first(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="old", sender="alice@co.com",
                            date=datetime(2026, 1, 1, tzinfo=timezone.utc)),
                _make_email(id="new", sender="alice@co.com",
                            date=datetime(2026, 3, 1, tzinfo=timezone.utc)),
            ])
            results = cache.get_emails_from_sender("alice@co.com")
            assert [r.id for r in results] == ["new", "old"]

    def test_respects_limit(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id=f"m{i}", sender="alice@co.com") for i in range(10)
            ])
            results = cache.get_emails_from_sender("alice@co.com", limit=3)
            assert len(results) == 3

    def test_no_match_returns_empty(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([_make_email(id="m1", sender="bob@co.com")])
            assert cache.get_emails_from_sender("alice@co.com") == []


class TestSearch:
    """Full-text search across subject and body."""

    def test_matches_subject(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", subject="Quarterly budget report"),
                _make_email(id="m2", subject="Lunch plans for Friday"),
                _make_email(id="m3", subject="Annual budget review"),
            ])
            results = cache.search_emails("budget")
            assert len(results) == 2
            assert {r.id for r in results} == {"m1", "m3"}

    def test_matches_body(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", body_plain="Please review the attached invoice"),
                _make_email(id="m2", body_plain="See you at the meeting"),
            ])
            results = cache.search_emails("invoice")
            assert len(results) == 1
            assert results[0].id == "m1"

    def test_case_insensitive(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", subject="URGENT: Server Down"),
            ])
            assert len(cache.search_emails("urgent")) == 1
            assert len(cache.search_emails("server down")) == 1

    def test_no_results_returns_empty(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([_make_email(id="m1", subject="Hello")])
            assert cache.search_emails("nonexistent") == []

    def test_respects_limit(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id=f"m{i}", subject=f"Report #{i}") for i in range(20)
            ])
            results = cache.search_emails("report", limit=5)
            assert len(results) == 5

    def test_ordered_by_date_desc(self):
        """Newest emails should appear first."""
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="old", subject="Report old", date=datetime(2026, 1, 1, tzinfo=timezone.utc)),
                _make_email(id="new", subject="Report new", date=datetime(2026, 3, 1, tzinfo=timezone.utc)),
                _make_email(id="mid", subject="Report mid", date=datetime(2026, 2, 1, tzinfo=timezone.utc)),
            ])
            results = cache.search_emails("report")
            assert [r.id for r in results] == ["new", "mid", "old"]

    def test_matches_across_subject_and_body(self):
        """A query should match if it appears in subject OR body, not requiring both."""
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", subject="Meeting notes", body_plain="Nothing about finance"),
                _make_email(id="m2", subject="No match here", body_plain="The meeting was productive"),
            ])
            results = cache.search_emails("meeting")
            assert len(results) == 2

    def test_empty_query_returns_empty(self):
        """An empty or whitespace-only query should not match everything."""
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([_make_email(id="m1", subject="Hello")])
            assert cache.search_emails("") == []
            assert cache.search_emails("   ") == []

    def test_percent_wildcard_treated_literally(self):
        """LIKE metacharacter % in the query should match the literal character."""
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", subject="100% complete"),
                _make_email(id="m2", subject="100 complete"),
            ])
            results = cache.search_emails("100%")
            assert len(results) == 1
            assert results[0].id == "m1"

    def test_underscore_wildcard_treated_literally(self):
        """LIKE metacharacter _ in the query should match the literal character."""
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", subject="in_reply_to header"),
                _make_email(id="m2", subject="inXreplyXto header"),
            ])
            results = cache.search_emails("in_reply_to")
            assert len(results) == 1
            assert results[0].id == "m1"


class TestFilterEmails:
    """Filter by sender, date range, label — all combinable."""

    def test_filter_by_sender(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", sender="alice@co.com"),
                _make_email(id="m2", sender="bob@co.com"),
                _make_email(id="m3", sender="alice@co.com"),
            ])
            results = cache.filter_emails(sender="alice@co.com")
            assert len(results) == 2
            assert all(r.sender == "alice@co.com" for r in results)

    def test_filter_by_date_range(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="jan", date=datetime(2026, 1, 15, tzinfo=timezone.utc)),
                _make_email(id="feb", date=datetime(2026, 2, 15, tzinfo=timezone.utc)),
                _make_email(id="mar", date=datetime(2026, 3, 15, tzinfo=timezone.utc)),
            ])
            results = cache.filter_emails(
                date_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
                date_to=datetime(2026, 2, 28, tzinfo=timezone.utc),
            )
            assert len(results) == 1
            assert results[0].id == "feb"

    def test_filter_by_label(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", labels=["INBOX", "IMPORTANT"]),
                _make_email(id="m2", labels=["INBOX"]),
                _make_email(id="m3", labels=["SENT"]),
            ])
            results = cache.filter_emails(label="IMPORTANT")
            assert len(results) == 1
            assert results[0].id == "m1"

    def test_filter_combined_sender_and_label(self):
        """Multiple filters are ANDed together."""
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", sender="alice@co.com", labels=["INBOX"]),
                _make_email(id="m2", sender="alice@co.com", labels=["SENT"]),
                _make_email(id="m3", sender="bob@co.com", labels=["INBOX"]),
            ])
            results = cache.filter_emails(sender="alice@co.com", label="INBOX")
            assert len(results) == 1
            assert results[0].id == "m1"

    def test_filter_combined_sender_and_date(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", sender="alice@co.com", date=datetime(2026, 1, 1, tzinfo=timezone.utc)),
                _make_email(id="m2", sender="alice@co.com", date=datetime(2026, 3, 1, tzinfo=timezone.utc)),
                _make_email(id="m3", sender="bob@co.com", date=datetime(2026, 3, 1, tzinfo=timezone.utc)),
            ])
            results = cache.filter_emails(
                sender="alice@co.com",
                date_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
            )
            assert len(results) == 1
            assert results[0].id == "m2"

    def test_filter_no_params_returns_all(self):
        """No filters = return everything (up to limit)."""
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([_make_email(id=f"m{i}") for i in range(5)])
            results = cache.filter_emails()
            assert len(results) == 5

    def test_filter_respects_limit(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id=f"m{i}", sender="same@co.com") for i in range(20)
            ])
            results = cache.filter_emails(sender="same@co.com", limit=3)
            assert len(results) == 3

    def test_filter_ordered_by_date_desc(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="old", sender="a@co.com", date=datetime(2026, 1, 1, tzinfo=timezone.utc)),
                _make_email(id="new", sender="a@co.com", date=datetime(2026, 3, 1, tzinfo=timezone.utc)),
            ])
            results = cache.filter_emails(sender="a@co.com")
            assert results[0].id == "new"
            assert results[1].id == "old"

    def test_filter_sender_case_insensitive(self):
        """Sender filtering should be case-insensitive."""
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", sender="Alice@Example.COM"),
                _make_email(id="m2", sender="bob@other.com"),
            ])
            results = cache.filter_emails(sender="alice@example.com")
            assert len(results) == 1
            assert results[0].id == "m1"


class TestOrganizedFlag:
    """Organized boolean flag on emails."""

    def test_emails_default_to_unorganized(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([_make_email(id="m1")])
            email = cache.get_email("m1")
            assert email.organized is False

    def test_mark_organized(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1"),
                _make_email(id="m2"),
            ])
            cache.mark_organized(["m1"])
            assert cache.get_email("m1").organized is True
            assert cache.get_email("m2").organized is False

    def test_mark_organized_batch(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([_make_email(id=f"m{i}") for i in range(5)])
            cache.mark_organized(["m0", "m2", "m4"])
            for i in range(5):
                email = cache.get_email(f"m{i}")
                assert email.organized == (i % 2 == 0)

    def test_mark_organized_empty_list_is_noop(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([_make_email(id="m1")])
            cache.mark_organized([])
            assert cache.get_email("m1").organized is False

    def test_get_unorganized(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", date=datetime(2026, 3, 1, tzinfo=timezone.utc)),
                _make_email(id="m2", date=datetime(2026, 3, 2, tzinfo=timezone.utc)),
                _make_email(id="m3", date=datetime(2026, 3, 3, tzinfo=timezone.utc)),
            ])
            cache.mark_organized(["m2"])
            unorg = cache.get_unorganized()
            assert len(unorg) == 2
            assert [e.id for e in unorg] == ["m3", "m1"]

    def test_get_unorganized_respects_limit(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([_make_email(id=f"m{i}") for i in range(10)])
            assert len(cache.get_unorganized(limit=3)) == 3

    def test_upsert_preserves_organized_flag(self):
        """Re-syncing an email should NOT reset organized back to False."""
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([_make_email(id="m1", subject="Original")])
            cache.mark_organized(["m1"])
            assert cache.get_email("m1").organized is True

            # Re-sync same email with updated subject
            cache.upsert_emails([_make_email(id="m1", subject="Updated")])
            email = cache.get_email("m1")
            assert email.subject == "Updated"
            assert email.organized is True  # preserved!


class TestFilePersistence:
    """Data survives closing and reopening a file-backed DuckDB."""

    def test_data_persists_across_sessions(self, tmp_path):
        db_path = str(tmp_path / "test.duckdb")

        # Session 1: write
        with EmailCache(db_path=db_path) as cache:
            cache.upsert_emails([
                _make_email(id="persist1", subject="Persistent Email",
                            date=datetime(2026, 3, 4, tzinfo=timezone.utc)),
            ])
            cache.update_sync_state()

        # Session 2: read back
        with EmailCache(db_path=db_path) as cache:
            assert cache.count() == 1
            email = cache.get_email("persist1")
            assert email is not None
            assert email.subject == "Persistent Email"
            assert cache.get_last_sync_date() == datetime(2026, 3, 4, tzinfo=timezone.utc)

    def test_upsert_persists_across_sessions(self, tmp_path):
        db_path = str(tmp_path / "test.duckdb")

        # Session 1: insert
        with EmailCache(db_path=db_path) as cache:
            cache.upsert_emails([_make_email(id="m1", subject="First")])

        # Session 2: upsert same ID + add new
        with EmailCache(db_path=db_path) as cache:
            cache.upsert_emails([
                _make_email(id="m1", subject="Updated"),
                _make_email(id="m2", subject="Second"),
            ])

        # Session 3: verify
        with EmailCache(db_path=db_path) as cache:
            assert cache.count() == 2
            assert cache.get_email("m1").subject == "Updated"
            assert cache.get_email("m2").subject == "Second"

    def test_search_works_after_reopen(self, tmp_path):
        db_path = str(tmp_path / "test.duckdb")

        with EmailCache(db_path=db_path) as cache:
            cache.upsert_emails([_make_email(id="m1", subject="Budget report Q1")])

        with EmailCache(db_path=db_path) as cache:
            results = cache.search_emails("budget")
            assert len(results) == 1
            assert results[0].id == "m1"
