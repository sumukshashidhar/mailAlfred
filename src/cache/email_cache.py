"""DuckDB-based local email cache."""

from __future__ import annotations

import json

import duckdb

from src.models import Email


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
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._conn.close()

    def __enter__(self) -> EmailCache:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
