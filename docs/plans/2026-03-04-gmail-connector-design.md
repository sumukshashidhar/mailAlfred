# Gmail Connector Design

**Date:** 2026-03-04
**Status:** Approved
**Scope:** Minimal fetch-only Gmail connector

## Goal

Build a Gmail connector that authenticates via OAuth2 and fetches unread emails from Gmail. No label management, no caching, no pagination iterator — just clean email fetching.

## Email Model

Expand the current `Email` dataclass to include fields the Gmail API provides:

```python
@dataclass
class Email:
    id: str
    thread_id: str
    subject: str
    sender: str
    body_plain: str = ""
    snippet: str = ""
    date: str | None = None
    labels: list[str] = field(default_factory=list)
```

## Gmail Connector API

```python
class Gmail:
    SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

    def __init__(self, credentials_path="credentials.json", token_path="token.json")
    async def get_unread_emails(self, max_results=10) -> list[Email]
    async def get_email(self, email_id: str) -> Email
```

### Auth Flow

1. Load `token.json` if it exists, build credentials
2. If expired, refresh automatically via `credentials.refresh()`
3. If no token, run `InstalledAppFlow` from `credentials.json` (opens browser)
4. Save refreshed/new token back to `token.json`

### Internal Parsing

Private `_parse_message(raw_message) -> Email`:
- Extract Subject, From, Date from headers
- Extract body from MIME parts (prefer text/plain, fall back to text/html stripped)
- Base64 URL-safe decoding

### Async Strategy

Use `google-api-python-client` (sync) wrapped with `asyncio.to_thread()`. This avoids blocking the event loop while leveraging the well-tested Google SDK.

## Dependencies

Add to `pyproject.toml`:
- `google-api-python-client`
- `google-auth-oauthlib`
- `google-auth-httplib2`

## Testing Strategy

TDD with unit tests using mocked Gmail API responses:
- `_parse_message` with plain text, multipart, HTML-only emails
- Auth flow: token exists, token expired, no token
- `get_unread_emails` returns correct Email objects
- `get_email` fetches a single email
- Empty inbox edge case
