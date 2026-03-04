"""DuckDB-based local email cache."""

from __future__ import annotations

import json
from datetime import datetime

import duckdb

from src.models import Attachment, Email


class EmailCache:
    """Cache for storing Gmail emails locally in DuckDB."""

    def __init__(self, db_path: str = "email_cache.duckdb") -> None:
        self._conn = duckdb.connect(db_path)
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        """Create tables if they do not already exist."""
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

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def upsert_emails(self, emails: list[Email]) -> None:
        """Insert or replace emails in the cache.

        Deduplicates by Gmail message ID (the primary key).
        Attachment binary data is excluded; only metadata is stored as JSON.
        """
        if not emails:
            return

        self._conn.executemany(
            """
            INSERT OR REPLACE INTO emails (
                id, thread_id, subject, sender,
                recipients, cc, bcc, date,
                message_id, in_reply_to, "references",
                snippet, body_plain, body_html,
                labels, attachment_meta, cached_at
            ) VALUES (
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, CURRENT_TIMESTAMP
            )
            """,
            [self._email_to_row(e) for e in emails],
        )

    @staticmethod
    def _email_to_row(email: Email) -> tuple:
        """Convert an Email dataclass to a tuple matching the INSERT columns."""
        attachment_meta = json.dumps(
            [
                {
                    "filename": a.filename,
                    "mime_type": a.mime_type,
                    "size": a.size,
                    "attachment_id": a.attachment_id,
                }
                for a in email.attachments
            ]
        )
        return (
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
        )

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get_last_sync_date(self) -> datetime | None:
        """Return the last sync date, or None if no sync has been recorded."""
        row = self._conn.execute(
            "SELECT last_sync_date FROM sync_state WHERE id = 1"
        ).fetchone()
        if row is None or row[0] is None:
            return None
        return row[0]

    def count(self) -> int:
        """Return the total number of cached emails."""
        row = self._conn.execute("SELECT COUNT(*) FROM emails").fetchone()
        return row[0]

    def get_email(self, email_id: str) -> Email | None:
        """Return a single Email by its ID, or None if not found."""
        result = self._conn.execute(
            """
            SELECT id, thread_id, subject, sender,
                   recipients, cc, bcc, date,
                   message_id, in_reply_to, "references",
                   snippet, body_plain, body_html,
                   labels, attachment_meta
            FROM emails WHERE id = ?
            """,
            [email_id],
        )
        columns = [desc[0] for desc in result.description]
        row = result.fetchone()
        if row is None:
            return None
        return self._row_to_email(row, columns)

    def _rows_to_emails(self, result) -> list[Email]:
        """Convert a DuckDB result set to Email objects."""
        columns = [desc[0] for desc in result.description]
        return [self._row_to_email(row, columns) for row in result.fetchall()]

    @staticmethod
    def _row_to_email(row: tuple, columns: list[str]) -> Email:
        """Convert a DuckDB result row to an Email dataclass.

        Parses attachment_meta JSON back into Attachment objects.
        """
        data = dict(zip(columns, row))

        # Parse attachment JSON back into Attachment objects
        raw_meta = data.pop("attachment_meta", "[]")
        if isinstance(raw_meta, str):
            meta_list = json.loads(raw_meta)
        else:
            # DuckDB may return it already parsed
            meta_list = raw_meta if raw_meta else []
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
            recipients=list(data.get("recipients") or []),
            cc=list(data.get("cc") or []),
            bcc=list(data.get("bcc") or []),
            date=data.get("date"),
            message_id=data.get("message_id", ""),
            in_reply_to=data.get("in_reply_to", ""),
            references=list(data.get("references") or []),
            snippet=data.get("snippet", ""),
            body_plain=data.get("body_plain", ""),
            body_html=data.get("body_html", ""),
            labels=list(data.get("labels") or []),
            attachments=attachments,
        )

    # ------------------------------------------------------------------
    # Search & filter
    # ------------------------------------------------------------------

    def search(self, query: str, limit: int = 50) -> list[Email]:
        """Search emails by subject and body (case-insensitive)."""
        pattern = f"%{query}%"
        result = self._conn.execute(
            """
            SELECT id, thread_id, subject, sender,
                   recipients, cc, bcc, date,
                   message_id, in_reply_to, "references",
                   snippet, body_plain, body_html,
                   labels, attachment_meta
            FROM emails
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
        """Filter emails by sender, date range, label. All params optional and ANDed."""
        conditions: list[str] = []
        params: list = []

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
            f"""
            SELECT id, thread_id, subject, sender,
                   recipients, cc, bcc, date,
                   message_id, in_reply_to, "references",
                   snippet, body_plain, body_html,
                   labels, attachment_meta
            FROM emails
            WHERE {where}
            ORDER BY date DESC NULLS LAST
            LIMIT ?
            """,
            params,
        )
        return self._rows_to_emails(result)

    # ------------------------------------------------------------------
    # Sync state
    # ------------------------------------------------------------------

    def update_sync_state(self) -> None:
        """Update sync_state with the newest email date and total count."""
        self._conn.execute("""
            INSERT OR REPLACE INTO sync_state (id, last_sync_date, total_cached)
            SELECT 1, MAX(date), COUNT(*)
            FROM emails
        """)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._conn.close()

    def __enter__(self) -> EmailCache:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
