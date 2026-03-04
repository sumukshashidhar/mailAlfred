# DuckDB Email Cache Design

**Date:** 2026-03-04
**Status:** Approved

## Goal

Local DuckDB cache that mirrors Gmail inbox history. Avoids re-fetching emails, enables full-text search and filtering, and provides historical context for AI agent classification.

## Key Decisions

- **Dedup strategy:** High-water mark timestamp (narrows Gmail queries) + message ID primary key (prevents duplicates)
- **Deletion handling:** Append-only — remote deletions are ignored, cache is a historical log
- **Attachments:** Metadata only (filename, mime_type, size, attachment_id) — no binary content stored
- **Search:** Full-text search on subject + body_plain, plus field filtering

## Schema

```sql
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
);

CREATE TABLE IF NOT EXISTS sync_state (
    id              INTEGER PRIMARY KEY DEFAULT 1,
    last_sync_date  TIMESTAMPTZ,
    total_cached    INTEGER DEFAULT 0
);
```

## Architecture

```
EmailCache (src/cache/email_cache.py)
├── __init__(db_path="data/emails.duckdb")
├── _ensure_schema()
├── upsert_emails(emails: list[Email])
├── get_last_sync_date() -> datetime | None
├── update_sync_state()
├── get_email(id: str) -> Email | None
├── search(query: str, limit: int) -> list[Email]
├── filter_emails(sender, date_from, date_to, labels, limit) -> list[Email]
├── count() -> int
├── close()
└── __enter__ / __exit__ (context manager)
```

## Data Flow

1. `cache.get_last_sync_date()` → timestamp or None
2. `gmail.get_unread_emails()` with `after:YYYY/MM/DD` filter → new emails only
3. `cache.upsert_emails(emails)` → INSERT OR REPLACE by primary key
4. `cache.update_sync_state()` → set high-water mark to newest email date

## Dependencies

- `duckdb` (Python package)

## Testing Strategy

- Unit tests with in-memory DuckDB (`:memory:`)
- Test upsert dedup (same ID inserted twice → no duplicate)
- Test search and filter queries
- Test sync state persistence
- Test Email ↔ DuckDB round-trip (all fields preserved)
