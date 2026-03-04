# DuckDB Email Cache Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a DuckDB-based local cache that stores emails, avoids re-fetching, and supports full-text search and filtering.

**Architecture:** `EmailCache` class wraps a DuckDB file database. Emails are upserted by Gmail message ID (primary key). A `sync_state` table tracks a high-water mark timestamp to narrow Gmail queries. Attachment metadata is stored as JSON; binary content is not cached.

**Tech Stack:** Python 3.12, duckdb, pytest

---

### Task 1: Create the cache package structure

**Files:**
- Create: `src/cache/__init__.py`
- Create: `src/cache/email_cache.py` (stub)

**Step 1: Create the package**

`src/cache/__init__.py`:
```python
from src.cache.email_cache import EmailCache

__all__ = ["EmailCache"]
```

`src/cache/email_cache.py`:
```python
class EmailCache:
    """DuckDB-backed local email cache."""
    pass
```

**Step 2: Verify import**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -c "from src.cache import EmailCache; print(EmailCache)"`
Expected: `<class 'src.cache.email_cache.EmailCache'>`

**Step 3: Commit**

```bash
git add src/cache/
git commit -m "chore: scaffold cache package with EmailCache stub"
```

---

### Task 2: Test and implement schema creation

**Files:**
- Create: `tests/test_email_cache.py`
- Modify: `src/cache/email_cache.py`

**Step 1: Write the failing test**

Create `tests/test_email_cache.py`:

```python
import duckdb
import pytest

from src.cache.email_cache import EmailCache


class TestSchemaCreation:
    """EmailCache creates the expected tables on init."""

    def test_creates_emails_table(self):
        cache = EmailCache(db_path=":memory:")
        tables = cache._conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "emails" in table_names
        cache.close()

    def test_creates_sync_state_table(self):
        cache = EmailCache(db_path=":memory:")
        tables = cache._conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "sync_state" in table_names
        cache.close()

    def test_emails_table_has_expected_columns(self):
        cache = EmailCache(db_path=":memory:")
        cols = cache._conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'emails' ORDER BY ordinal_position"
        ).fetchall()
        col_names = [c[0] for c in cols]
        expected = [
            "id", "thread_id", "subject", "sender", "recipients", "cc", "bcc",
            "date", "message_id", "in_reply_to", "references", "snippet",
            "body_plain", "body_html", "labels", "attachment_meta", "cached_at",
        ]
        assert col_names == expected
        cache.close()

    def test_context_manager(self):
        with EmailCache(db_path=":memory:") as cache:
            assert cache._conn is not None
        # After exit, connection should be closed
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m pytest tests/test_email_cache.py -v`
Expected: FAIL — `EmailCache` has no `__init__`, `_conn`, `close`, etc.

**Step 3: Implement**

Replace `src/cache/email_cache.py`:

```python
"""DuckDB-backed local email cache for Gmail emails."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import duckdb

from src.models import Attachment, Email


class EmailCache:
    """DuckDB-backed local email cache."""

    def __init__(self, db_path: str = "data/emails.duckdb") -> None:
        self._conn = duckdb.connect(db_path)
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS emails (
                id              VARCHAR PRIMARY KEY,
                thread_id       VARCHAR NOT NULL,
                subject         VARCHAR DEFAULT '',
                sender          VARCHAR DEFAULT '',
                recipients      VARCHAR[] DEFAULT [],
                cc              VARCHAR[] DEFAULT [],
                bcc             VARCHAR[] DEFAULT [],
                date            TIMESTAMPTZ,
                message_id      VARCHAR DEFAULT '',
                in_reply_to     VARCHAR DEFAULT '',
                "references"    VARCHAR[] DEFAULT [],
                snippet         VARCHAR DEFAULT '',
                body_plain      VARCHAR DEFAULT '',
                body_html       VARCHAR DEFAULT '',
                labels          VARCHAR[] DEFAULT [],
                attachment_meta JSON DEFAULT '[]',
                cached_at       TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS sync_state (
                id              INTEGER PRIMARY KEY DEFAULT 1,
                last_sync_date  TIMESTAMPTZ,
                total_cached    INTEGER DEFAULT 0
            )
        """)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
```

**Step 4: Run tests**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m pytest tests/test_email_cache.py -v`
Expected: All 4 PASS.

**Step 5: Commit**

```bash
git add src/cache/email_cache.py tests/test_email_cache.py
git commit -m "feat: EmailCache schema creation with DuckDB"
```

---

### Task 3: Test and implement upsert_emails

**Files:**
- Modify: `tests/test_email_cache.py`
- Modify: `src/cache/email_cache.py`

**Step 1: Write the failing tests**

Append to `tests/test_email_cache.py`:

```python
from datetime import datetime, timezone
from src.models import Attachment, Email


def _make_email(
    id: str = "msg1",
    thread_id: str = "t1",
    subject: str = "Test",
    sender: str = "alice@example.com",
    **kwargs,
) -> Email:
    return Email(id=id, thread_id=thread_id, subject=subject, sender=sender, **kwargs)


class TestUpsertEmails:
    """Insert and deduplicate emails."""

    def test_insert_single_email(self):
        with EmailCache(db_path=":memory:") as cache:
            email = _make_email(
                date=datetime(2026, 3, 4, 10, 0, tzinfo=timezone.utc),
                recipients=["bob@example.com"],
                labels=["INBOX", "UNREAD"],
            )
            cache.upsert_emails([email])

            row = cache._conn.execute(
                "SELECT id, subject, sender FROM emails WHERE id = ?", ["msg1"]
            ).fetchone()
            assert row == ("msg1", "Test", "alice@example.com")

    def test_upsert_dedup_by_id(self):
        with EmailCache(db_path=":memory:") as cache:
            email1 = _make_email(subject="Version 1")
            cache.upsert_emails([email1])

            email2 = _make_email(subject="Version 2")
            cache.upsert_emails([email2])

            count = cache._conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
            assert count == 1
            # Should have the updated version
            row = cache._conn.execute("SELECT subject FROM emails WHERE id = 'msg1'").fetchone()
            assert row[0] == "Version 2"

    def test_insert_multiple_emails(self):
        with EmailCache(db_path=":memory:") as cache:
            emails = [_make_email(id=f"msg{i}", thread_id=f"t{i}") for i in range(5)]
            cache.upsert_emails(emails)

            count = cache._conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
            assert count == 5

    def test_attachment_metadata_stored_as_json(self):
        with EmailCache(db_path=":memory:") as cache:
            email = _make_email(
                attachments=[
                    Attachment(filename="doc.pdf", mime_type="application/pdf", size=1024, attachment_id="att1"),
                    Attachment(filename="img.png", mime_type="image/png", size=2048, attachment_id="att2"),
                ]
            )
            cache.upsert_emails([email])

            row = cache._conn.execute(
                "SELECT attachment_meta FROM emails WHERE id = 'msg1'"
            ).fetchone()
            meta = json.loads(row[0]) if isinstance(row[0], str) else row[0]
            assert len(meta) == 2
            assert meta[0]["filename"] == "doc.pdf"
            assert meta[1]["mime_type"] == "image/png"

    def test_empty_list_is_noop(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([])
            count = cache._conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
            assert count == 0
```

**Step 2: Run to verify failure**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m pytest tests/test_email_cache.py::TestUpsertEmails -v`
Expected: FAIL — `upsert_emails` not defined.

**Step 3: Implement upsert_emails**

Add to `EmailCache` class in `src/cache/email_cache.py`:

```python
    def upsert_emails(self, emails: list[Email]) -> None:
        """Insert or update emails in the cache."""
        if not emails:
            return

        for email in emails:
            attachment_meta = json.dumps([
                {
                    "filename": a.filename,
                    "mime_type": a.mime_type,
                    "size": a.size,
                    "attachment_id": a.attachment_id,
                }
                for a in email.attachments
            ])

            self._conn.execute(
                """
                INSERT OR REPLACE INTO emails (
                    id, thread_id, subject, sender, recipients, cc, bcc,
                    date, message_id, in_reply_to, "references", snippet,
                    body_plain, body_html, labels, attachment_meta
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    email.id,
                    email.thread_id,
                    email.subject,
                    email.sender,
                    email.recipients,
                    email.cc,
                    email.bcc,
                    email.date,
                    email.message_id,
                    email.in_reply_to,
                    email.references,
                    email.snippet,
                    email.body_plain,
                    email.body_html,
                    email.labels,
                    attachment_meta,
                ],
            )
```

**Step 4: Run tests**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m pytest tests/test_email_cache.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add src/cache/email_cache.py tests/test_email_cache.py
git commit -m "feat: implement email upsert with dedup by message ID"
```

---

### Task 4: Test and implement sync state

**Files:**
- Modify: `tests/test_email_cache.py`
- Modify: `src/cache/email_cache.py`

**Step 1: Write the failing tests**

Append to `tests/test_email_cache.py`:

```python
class TestSyncState:
    """Track high-water mark for incremental sync."""

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
```

**Step 2: Run to verify failure**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m pytest tests/test_email_cache.py::TestSyncState -v`
Expected: FAIL — methods not defined.

**Step 3: Implement**

Add to `EmailCache` class:

```python
    def get_last_sync_date(self) -> datetime | None:
        """Return the high-water mark timestamp, or None if never synced."""
        row = self._conn.execute(
            "SELECT last_sync_date FROM sync_state WHERE id = 1"
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return row[0]

    def update_sync_state(self) -> None:
        """Set high-water mark to the newest email date in cache."""
        row = self._conn.execute(
            "SELECT MAX(date) FROM emails"
        ).fetchone()
        newest = row[0] if row else None
        total = self._conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]

        self._conn.execute(
            """
            INSERT OR REPLACE INTO sync_state (id, last_sync_date, total_cached)
            VALUES (1, ?, ?)
            """,
            [newest, total],
        )

    def count(self) -> int:
        """Return total number of cached emails."""
        return self._conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
```

**Step 4: Run tests**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m pytest tests/test_email_cache.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add src/cache/email_cache.py tests/test_email_cache.py
git commit -m "feat: implement sync state tracking with high-water mark"
```

---

### Task 5: Test and implement get_email (read-back)

**Files:**
- Modify: `tests/test_email_cache.py`
- Modify: `src/cache/email_cache.py`

**Step 1: Write the failing tests**

Append to `tests/test_email_cache.py`:

```python
class TestGetEmail:
    """Retrieve a single cached email as an Email dataclass."""

    def test_get_existing_email(self):
        with EmailCache(db_path=":memory:") as cache:
            original = _make_email(
                date=datetime(2026, 3, 4, 10, 0, tzinfo=timezone.utc),
                recipients=["bob@example.com"],
                cc=["carol@example.com"],
                labels=["INBOX"],
                body_plain="Hello world",
                body_html="<p>Hello world</p>",
                message_id="<msg@example.com>",
                in_reply_to="<prev@example.com>",
                references=["<prev@example.com>"],
                attachments=[
                    Attachment(filename="doc.pdf", mime_type="application/pdf", size=1024, attachment_id="att1"),
                ],
            )
            cache.upsert_emails([original])

            result = cache.get_email("msg1")
            assert result is not None
            assert result.id == "msg1"
            assert result.subject == "Test"
            assert result.sender == "alice@example.com"
            assert result.recipients == ["bob@example.com"]
            assert result.cc == ["carol@example.com"]
            assert result.labels == ["INBOX"]
            assert result.body_plain == "Hello world"
            assert result.body_html == "<p>Hello world</p>"
            assert result.message_id == "<msg@example.com>"
            assert result.references == ["<prev@example.com>"]
            assert len(result.attachments) == 1
            assert result.attachments[0].filename == "doc.pdf"

    def test_get_nonexistent_email_returns_none(self):
        with EmailCache(db_path=":memory:") as cache:
            assert cache.get_email("nonexistent") is None
```

**Step 2: Run to verify failure**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m pytest tests/test_email_cache.py::TestGetEmail -v`
Expected: FAIL — `get_email` not defined.

**Step 3: Implement**

Add to `EmailCache` class:

```python
    def _row_to_email(self, row: tuple, columns: list[str]) -> Email:
        """Convert a DuckDB row to an Email dataclass."""
        data = dict(zip(columns, row))

        # Parse attachment metadata from JSON
        meta_raw = data.get("attachment_meta", "[]")
        if isinstance(meta_raw, str):
            meta_list = json.loads(meta_raw)
        else:
            meta_list = meta_raw if meta_raw else []

        attachments = [
            Attachment(
                filename=m.get("filename", ""),
                mime_type=m.get("mime_type", ""),
                size=m.get("size", 0),
                attachment_id=m.get("attachment_id", ""),
            )
            for m in meta_list
        ]

        return Email(
            id=data["id"],
            thread_id=data["thread_id"],
            subject=data.get("subject", ""),
            sender=data.get("sender", ""),
            recipients=data.get("recipients") or [],
            cc=data.get("cc") or [],
            bcc=data.get("bcc") or [],
            date=data.get("date"),
            message_id=data.get("message_id", ""),
            in_reply_to=data.get("in_reply_to", ""),
            references=data.get("references") or [],
            snippet=data.get("snippet", ""),
            body_plain=data.get("body_plain", ""),
            body_html=data.get("body_html", ""),
            labels=data.get("labels") or [],
            attachments=attachments,
        )

    def get_email(self, email_id: str) -> Email | None:
        """Fetch a single cached email by Gmail message ID."""
        result = self._conn.execute(
            "SELECT * FROM emails WHERE id = ?", [email_id]
        )
        columns = [desc[0] for desc in result.description]
        row = result.fetchone()
        if row is None:
            return None
        return self._row_to_email(row, columns)
```

**Step 4: Run tests**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m pytest tests/test_email_cache.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add src/cache/email_cache.py tests/test_email_cache.py
git commit -m "feat: implement get_email with full round-trip from DuckDB"
```

---

### Task 6: Test and implement search and filter

**Files:**
- Modify: `tests/test_email_cache.py`
- Modify: `src/cache/email_cache.py`

**Step 1: Write the failing tests**

Append to `tests/test_email_cache.py`:

```python
class TestSearch:
    """Full-text search across subject and body."""

    def test_search_finds_by_subject(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", subject="Quarterly report ready"),
                _make_email(id="m2", subject="Lunch plans"),
            ])
            results = cache.search("quarterly")
            assert len(results) == 1
            assert results[0].id == "m1"

    def test_search_finds_by_body(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", body_plain="Please review the budget proposal"),
                _make_email(id="m2", body_plain="See you tomorrow"),
            ])
            results = cache.search("budget")
            assert len(results) == 1
            assert results[0].id == "m1"

    def test_search_case_insensitive(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([_make_email(id="m1", subject="IMPORTANT Meeting")])
            results = cache.search("important")
            assert len(results) == 1

    def test_search_no_results(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([_make_email(id="m1", subject="Hello")])
            results = cache.search("nonexistent")
            assert results == []

    def test_search_respects_limit(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id=f"m{i}", subject=f"Report {i}") for i in range(10)
            ])
            results = cache.search("report", limit=3)
            assert len(results) == 3


class TestFilterEmails:
    """Filter by sender, date range, labels."""

    def test_filter_by_sender(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", sender="alice@example.com"),
                _make_email(id="m2", sender="bob@example.com"),
                _make_email(id="m3", sender="alice@example.com"),
            ])
            results = cache.filter_emails(sender="alice@example.com")
            assert len(results) == 2

    def test_filter_by_date_range(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", date=datetime(2026, 1, 1, tzinfo=timezone.utc)),
                _make_email(id="m2", date=datetime(2026, 2, 15, tzinfo=timezone.utc)),
                _make_email(id="m3", date=datetime(2026, 3, 1, tzinfo=timezone.utc)),
            ])
            results = cache.filter_emails(
                date_from=datetime(2026, 2, 1, tzinfo=timezone.utc),
                date_to=datetime(2026, 2, 28, tzinfo=timezone.utc),
            )
            assert len(results) == 1
            assert results[0].id == "m2"

    def test_filter_by_label(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", labels=["INBOX", "UNREAD"]),
                _make_email(id="m2", labels=["INBOX"]),
                _make_email(id="m3", labels=["SENT"]),
            ])
            results = cache.filter_emails(label="UNREAD")
            assert len(results) == 1
            assert results[0].id == "m1"

    def test_filter_combined(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id="m1", sender="alice@example.com", labels=["INBOX"]),
                _make_email(id="m2", sender="alice@example.com", labels=["SENT"]),
                _make_email(id="m3", sender="bob@example.com", labels=["INBOX"]),
            ])
            results = cache.filter_emails(sender="alice@example.com", label="INBOX")
            assert len(results) == 1
            assert results[0].id == "m1"

    def test_filter_with_limit(self):
        with EmailCache(db_path=":memory:") as cache:
            cache.upsert_emails([
                _make_email(id=f"m{i}", sender="alice@example.com") for i in range(10)
            ])
            results = cache.filter_emails(sender="alice@example.com", limit=3)
            assert len(results) == 3
```

**Step 2: Run to verify failure**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m pytest tests/test_email_cache.py::TestSearch tests/test_email_cache.py::TestFilterEmails -v`
Expected: FAIL — methods not defined.

**Step 3: Implement search and filter_emails**

Add to `EmailCache` class:

```python
    def _rows_to_emails(self, result) -> list[Email]:
        """Convert a DuckDB result set to a list of Email objects."""
        columns = [desc[0] for desc in result.description]
        return [self._row_to_email(row, columns) for row in result.fetchall()]

    def search(self, query: str, limit: int = 50) -> list[Email]:
        """Search emails by subject and body (case-insensitive LIKE)."""
        pattern = f"%{query}%"
        result = self._conn.execute(
            """
            SELECT * FROM emails
            WHERE subject ILIKE ? OR body_plain ILIKE ?
            ORDER BY date DESC NULLS LAST
            LIMIT ?
            """,
            [pattern, pattern, limit],
        )
        return self._rows_to_emails(result)

    def filter_emails(
        self,
        sender: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        label: str | None = None,
        limit: int = 50,
    ) -> list[Email]:
        """Filter emails by sender, date range, and/or label."""
        conditions = []
        params = []

        if sender is not None:
            conditions.append("sender = ?")
            params.append(sender)
        if date_from is not None:
            conditions.append("date >= ?")
            params.append(date_from)
        if date_to is not None:
            conditions.append("date <= ?")
            params.append(date_to)
        if label is not None:
            conditions.append("list_contains(labels, ?)")
            params.append(label)

        where = " AND ".join(conditions) if conditions else "TRUE"
        params.append(limit)

        result = self._conn.execute(
            f"SELECT * FROM emails WHERE {where} ORDER BY date DESC NULLS LAST LIMIT ?",
            params,
        )
        return self._rows_to_emails(result)
```

**Step 4: Run tests**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m pytest tests/test_email_cache.py -v`
Expected: All PASS.

**Step 5: Commit**

```bash
git add src/cache/email_cache.py tests/test_email_cache.py
git commit -m "feat: implement search and filter for cached emails"
```

---

### Task 7: Test file-based persistence

**Files:**
- Modify: `tests/test_email_cache.py`

**Step 1: Write test**

Append to `tests/test_email_cache.py`:

```python
import os
import tempfile


class TestFilePersistence:
    """Verify data persists across cache instances via file-based DuckDB."""

    def test_data_persists_after_close_and_reopen(self):
        with tempfile.NamedTemporaryFile(suffix=".duckdb", delete=False) as f:
            db_path = f.name

        try:
            # Write
            with EmailCache(db_path=db_path) as cache:
                cache.upsert_emails([_make_email(id="persist1", subject="Persistent")])
                cache.update_sync_state()

            # Read back in new instance
            with EmailCache(db_path=db_path) as cache:
                email = cache.get_email("persist1")
                assert email is not None
                assert email.subject == "Persistent"
                assert cache.count() == 1
                assert cache.get_last_sync_date() is not None
        finally:
            os.unlink(db_path)
            # DuckDB may create .wal file
            wal = db_path + ".wal"
            if os.path.exists(wal):
                os.unlink(wal)
```

**Step 2: Run test**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m pytest tests/test_email_cache.py::TestFilePersistence -v`
Expected: PASS (no new implementation needed — existing code should handle this).

**Step 3: Commit**

```bash
git add tests/test_email_cache.py
git commit -m "test: verify file-based DuckDB persistence across sessions"
```

---

### Task 8: Add Gmail query filter for incremental sync

**Files:**
- Modify: `src/connectors/gmail.py:211-218`

**Step 1: Write the failing test**

Append to `tests/test_gmail_connector.py`:

```python
class TestIncrementalFetch:
    """get_unread_emails supports after_date for incremental sync."""

    def test_after_date_adds_query_filter(self):
        gmail = Gmail.__new__(Gmail)
        gmail._service = MagicMock()
        gmail._credentials_path = "creds.json"
        gmail._token_path = "token.json"

        gmail._service.users().messages().list().execute.return_value = {
            "resultSizeEstimate": 0,
        }

        from datetime import datetime, timezone
        after = datetime(2026, 3, 1, tzinfo=timezone.utc)
        gmail._fetch_messages_sync(max_results=10, after_date=after)

        gmail._service.users().messages().list.assert_called_with(
            userId="me", q="is:unread after:2026/03/01", maxResults=10
        )
```

**Step 2: Run to verify failure**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m pytest tests/test_gmail_connector.py::TestIncrementalFetch -v`
Expected: FAIL — `_fetch_messages_sync` doesn't accept `after_date`.

**Step 3: Implement**

Modify `_fetch_messages_sync` and `get_unread_emails` in `src/connectors/gmail.py`:

```python
    def _fetch_messages_sync(
        self, max_results: int = 10, after_date: datetime | None = None
    ) -> list[Email]:
        """Fetch unread messages synchronously."""
        service = self._get_service()

        query = "is:unread"
        if after_date:
            query += f" after:{after_date.strftime('%Y/%m/%d')}"

        response = (
            service.users()
            .messages()
            .list(userId="me", q=query, maxResults=max_results)
            .execute()
        )

        messages = response.get("messages", [])
        if not messages:
            return []

        emails: list[Email] = []
        for stub in messages:
            raw = (
                service.users()
                .messages()
                .get(userId="me", id=stub["id"], format="full")
                .execute()
            )
            emails.append(self._parse_message(raw))
        return emails

    async def get_unread_emails(
        self, max_results: int = 10, after_date: datetime | None = None
    ) -> list[Email]:
        """Fetch unread emails asynchronously."""
        return await asyncio.to_thread(
            self._fetch_messages_sync, max_results, after_date
        )
```

**Step 4: Run all tests**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m pytest tests/ -v`
Expected: All PASS (existing tests still work since `after_date` defaults to `None`).

**Step 5: Commit**

```bash
git add src/connectors/gmail.py tests/test_gmail_connector.py
git commit -m "feat: add after_date filter to Gmail fetch for incremental sync"
```

---

### Task 9: Final integration test

**Files:**
- Modify: `tests/test_email_cache.py`

**Step 1: Write an integration-style test**

Append to `tests/test_email_cache.py`:

```python
class TestIntegrationFlow:
    """End-to-end: upsert → sync state → search → filter → get."""

    def test_full_workflow(self):
        with EmailCache(db_path=":memory:") as cache:
            # Simulate first sync
            batch1 = [
                _make_email(
                    id="m1", subject="Budget Report Q1",
                    sender="finance@company.com",
                    body_plain="Q1 budget numbers attached",
                    date=datetime(2026, 1, 15, tzinfo=timezone.utc),
                    labels=["INBOX", "UNREAD"],
                ),
                _make_email(
                    id="m2", subject="Lunch tomorrow?",
                    sender="friend@gmail.com",
                    body_plain="Want to grab lunch?",
                    date=datetime(2026, 1, 20, tzinfo=timezone.utc),
                    labels=["INBOX"],
                ),
            ]
            cache.upsert_emails(batch1)
            cache.update_sync_state()
            assert cache.count() == 2
            assert cache.get_last_sync_date() == datetime(2026, 1, 20, tzinfo=timezone.utc)

            # Simulate second sync with newer emails
            batch2 = [
                _make_email(
                    id="m3", subject="Budget Report Q2",
                    sender="finance@company.com",
                    body_plain="Q2 numbers ready",
                    date=datetime(2026, 3, 1, tzinfo=timezone.utc),
                    labels=["INBOX", "UNREAD"],
                ),
            ]
            cache.upsert_emails(batch2)
            cache.update_sync_state()
            assert cache.count() == 3
            assert cache.get_last_sync_date() == datetime(2026, 3, 1, tzinfo=timezone.utc)

            # Search
            results = cache.search("budget")
            assert len(results) == 2
            assert {r.id for r in results} == {"m1", "m3"}

            # Filter
            results = cache.filter_emails(sender="finance@company.com")
            assert len(results) == 2

            results = cache.filter_emails(label="UNREAD")
            assert len(results) == 2  # m1 and m3

            # Get single
            email = cache.get_email("m2")
            assert email is not None
            assert email.subject == "Lunch tomorrow?"
```

**Step 2: Run all tests**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m pytest tests/ -v`
Expected: All PASS.

**Step 3: Commit**

```bash
git add tests/test_email_cache.py
git commit -m "test: add integration test for full email cache workflow"
```
