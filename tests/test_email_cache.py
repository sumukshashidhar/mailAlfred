"""Tests for the DuckDB email cache."""

import duckdb
import pytest

from src.cache import EmailCache


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
