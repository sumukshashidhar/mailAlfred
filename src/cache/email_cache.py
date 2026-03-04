"""DuckDB-based local email cache."""

from __future__ import annotations

import duckdb


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
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying DuckDB connection."""
        self._conn.close()

    def __enter__(self) -> EmailCache:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
