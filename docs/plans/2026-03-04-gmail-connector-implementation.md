# Gmail Connector Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a minimal Gmail connector that authenticates via OAuth2 and fetches unread emails.

**Architecture:** Sync `google-api-python-client` wrapped in `asyncio.to_thread()` for async. OAuth2 with `credentials.json`/`token.json` file-based auth. Private `_parse_message` extracts headers and body from Gmail API responses.

**Tech Stack:** Python 3.12, google-api-python-client, google-auth-oauthlib, pytest, unittest.mock

---

### Task 1: Add Google API dependencies

**Files:**
- Modify: `pyproject.toml:7-13`

**Step 1: Add dependencies**

Add the three Google libraries to `pyproject.toml` dependencies:

```toml
dependencies = [
    "asyncio>=4.0.0",
    "google-api-python-client>=2.150.0",
    "google-auth-httplib2>=0.2.0",
    "google-auth-oauthlib>=1.2.0",
    "jinja2>=3.1.6",
    "loguru>=0.7.3",
    "openai-agents>=0.10.4",
    "python-dotenv>=1.2.2",
]
```

**Step 2: Install dependencies**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv sync`
Expected: Dependencies resolve and install successfully.

**Step 3: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add google api dependencies for gmail connector"
```

---

### Task 2: Expand the Email model

**Files:**
- Modify: `src/models.py:1-12`
- Test: `tests/test_models.py` (create)

**Step 1: Write the failing test**

Create `tests/test_models.py`:

```python
from dataclasses import fields

from src.models import Email


def test_email_required_fields():
    email = Email(id="abc123", thread_id="thread1", subject="Hello", sender="alice@example.com")
    assert email.id == "abc123"
    assert email.thread_id == "thread1"
    assert email.subject == "Hello"
    assert email.sender == "alice@example.com"


def test_email_default_fields():
    email = Email(id="abc123", thread_id="thread1", subject="Hello", sender="alice@example.com")
    assert email.body_plain == ""
    assert email.snippet == ""
    assert email.date is None
    assert email.labels == []


def test_email_custom_fields():
    email = Email(
        id="abc123",
        thread_id="thread1",
        subject="Meeting",
        sender="bob@example.com",
        body_plain="Let's meet at 3pm",
        snippet="Let's meet...",
        date="2026-03-04T10:00:00Z",
        labels=["INBOX", "UNREAD"],
    )
    assert email.body_plain == "Let's meet at 3pm"
    assert email.snippet == "Let's meet..."
    assert email.date == "2026-03-04T10:00:00Z"
    assert email.labels == ["INBOX", "UNREAD"]


def test_email_labels_no_shared_default():
    """Ensure each Email gets its own labels list (no mutable default sharing)."""
    a = Email(id="1", thread_id="t1", subject="A", sender="a@a.com")
    b = Email(id="2", thread_id="t2", subject="B", sender="b@b.com")
    a.labels.append("INBOX")
    assert b.labels == []
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && python -m pytest tests/test_models.py -v`
Expected: FAIL — `Email` currently has no `thread_id` field.

**Step 3: Write the implementation**

Replace `src/models.py` entirely:

```python
from dataclasses import dataclass, field


@dataclass
class Email:
    """Email fetched from Gmail."""

    id: str
    thread_id: str
    subject: str
    sender: str
    body_plain: str = ""
    snippet: str = ""
    date: str | None = None
    labels: list[str] = field(default_factory=list)
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && python -m pytest tests/test_models.py -v`
Expected: All 4 tests PASS.

**Step 5: Commit**

```bash
git add src/models.py tests/test_models.py
git commit -m "feat: expand Email model with thread_id, body, date, labels"
```

---

### Task 3: Create connectors __init__.py

**Files:**
- Create: `src/connectors/__init__.py`

**Step 1: Create the file**

```python
from src.connectors.gmail import Gmail

__all__ = ["Gmail"]
```

**Step 2: Verify import works**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && python -c "from src.connectors import Gmail; print(Gmail)"`
Expected: `<class 'src.connectors.gmail.Gmail'>`

**Step 3: Commit**

```bash
git add src/connectors/__init__.py
git commit -m "chore: add connectors __init__ with Gmail re-export"
```

---

### Task 4: Test the message parser

**Files:**
- Test: `tests/test_gmail_connector.py` (create)

**Step 1: Write failing tests for _parse_message**

Create `tests/test_gmail_connector.py`:

```python
import base64

from src.connectors.gmail import Gmail
from src.models import Email


def _b64(text: str) -> str:
    """Base64url-encode a string, matching Gmail API format."""
    return base64.urlsafe_b64encode(text.encode()).decode()


class TestParseMessage:
    """Tests for Gmail._parse_message (static, no API needed)."""

    def test_plain_text_email(self):
        raw = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Hey there",
            "labelIds": ["INBOX", "UNREAD"],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Hello"},
                    {"name": "From", "value": "alice@example.com"},
                    {"name": "Date", "value": "Mon, 4 Mar 2026 10:00:00 +0000"},
                ],
                "mimeType": "text/plain",
                "body": {"data": _b64("Hello world!")},
            },
        }
        email = Gmail._parse_message(raw)
        assert email.id == "msg1"
        assert email.thread_id == "thread1"
        assert email.subject == "Hello"
        assert email.sender == "alice@example.com"
        assert email.body_plain == "Hello world!"
        assert email.snippet == "Hey there"
        assert email.date == "Mon, 4 Mar 2026 10:00:00 +0000"
        assert email.labels == ["INBOX", "UNREAD"]

    def test_multipart_email(self):
        raw = {
            "id": "msg2",
            "threadId": "thread2",
            "snippet": "Multipart",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Multipart Test"},
                    {"name": "From", "value": "bob@example.com"},
                    {"name": "Date", "value": "Tue, 5 Mar 2026 12:00:00 +0000"},
                ],
                "mimeType": "multipart/alternative",
                "body": {"size": 0},
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": _b64("Plain text part")},
                    },
                    {
                        "mimeType": "text/html",
                        "body": {"data": _b64("<p>HTML part</p>")},
                    },
                ],
            },
        }
        email = Gmail._parse_message(raw)
        assert email.body_plain == "Plain text part"

    def test_html_only_email(self):
        raw = {
            "id": "msg3",
            "threadId": "thread3",
            "snippet": "HTML only",
            "labelIds": [],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "HTML Only"},
                    {"name": "From", "value": "carol@example.com"},
                ],
                "mimeType": "text/html",
                "body": {"data": _b64("<h1>Title</h1><p>Content here</p>")},
            },
        }
        email = Gmail._parse_message(raw)
        # Should strip HTML tags as fallback
        assert "Title" in email.body_plain
        assert "Content here" in email.body_plain
        assert "<h1>" not in email.body_plain

    def test_missing_headers(self):
        raw = {
            "id": "msg4",
            "threadId": "thread4",
            "snippet": "",
            "labelIds": [],
            "payload": {
                "headers": [],
                "mimeType": "text/plain",
                "body": {"data": _b64("No headers")},
            },
        }
        email = Gmail._parse_message(raw)
        assert email.subject == ""
        assert email.sender == ""
        assert email.date is None

    def test_nested_multipart(self):
        """multipart/mixed containing multipart/alternative."""
        raw = {
            "id": "msg5",
            "threadId": "thread5",
            "snippet": "Nested",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Nested"},
                    {"name": "From", "value": "dave@example.com"},
                ],
                "mimeType": "multipart/mixed",
                "body": {"size": 0},
                "parts": [
                    {
                        "mimeType": "multipart/alternative",
                        "body": {"size": 0},
                        "parts": [
                            {
                                "mimeType": "text/plain",
                                "body": {"data": _b64("Deep plain text")},
                            },
                            {
                                "mimeType": "text/html",
                                "body": {"data": _b64("<p>Deep HTML</p>")},
                            },
                        ],
                    },
                ],
            },
        }
        email = Gmail._parse_message(raw)
        assert email.body_plain == "Deep plain text"
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && python -m pytest tests/test_gmail_connector.py -v`
Expected: FAIL — `Gmail._parse_message` does not exist yet.

**Step 3: Commit the tests**

```bash
git add tests/test_gmail_connector.py
git commit -m "test: add tests for Gmail message parser"
```

---

### Task 5: Implement _parse_message

**Files:**
- Modify: `src/connectors/gmail.py`

**Step 1: Implement the parser**

Replace `src/connectors/gmail.py` entirely:

```python
import base64
import re
from typing import Any

from src.models import Email


class Gmail:
    """Minimal Gmail connector — fetch-only, OAuth2 auth."""

    SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

    def __init__(
        self,
        credentials_path: str = "credentials.json",
        token_path: str = "token.json",
    ):
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._service = None  # lazy init

    @staticmethod
    def _parse_message(raw: dict[str, Any]) -> Email:
        """Parse a Gmail API message resource into an Email."""
        headers = {
            h["name"].lower(): h["value"]
            for h in raw.get("payload", {}).get("headers", [])
        }

        body_plain = Gmail._extract_body(raw.get("payload", {}))

        return Email(
            id=raw["id"],
            thread_id=raw["threadId"],
            subject=headers.get("subject", ""),
            sender=headers.get("from", ""),
            body_plain=body_plain,
            snippet=raw.get("snippet", ""),
            date=headers.get("date"),
            labels=raw.get("labelIds", []),
        )

    @staticmethod
    def _extract_body(payload: dict[str, Any]) -> str:
        """Recursively extract plain-text body from MIME payload."""
        mime_type = payload.get("mimeType", "")

        # Direct text/plain body
        if mime_type == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        # Multipart — recurse into parts
        if mime_type.startswith("multipart/"):
            for part in payload.get("parts", []):
                text = Gmail._extract_body(part)
                if text:
                    return text

        # Fallback: text/html stripped of tags
        if mime_type == "text/html":
            data = payload.get("body", {}).get("data", "")
            if data:
                html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                return re.sub(r"<[^>]+>", "", html)

        return ""

    async def get_unread_emails(self, max_results: int = 10) -> list[Email]:
        """Fetch unread emails. Non-blocking I/O."""
        # TODO: implement in Task 6
        return []

    async def get_email(self, email_id: str) -> Email:
        """Fetch a single email by ID."""
        # TODO: implement in Task 6
        raise NotImplementedError
```

**Step 2: Run tests to verify they pass**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && python -m pytest tests/test_gmail_connector.py -v`
Expected: All 5 tests PASS.

**Step 3: Commit**

```bash
git add src/connectors/gmail.py
git commit -m "feat: implement Gmail message parser with MIME body extraction"
```

---

### Task 6: Test the auth and fetch methods

**Files:**
- Modify: `tests/test_gmail_connector.py`

**Step 1: Add auth and fetch tests**

Append to `tests/test_gmail_connector.py`:

```python
import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open


class TestGmailAuth:
    """Tests for Gmail authentication flow."""

    @patch("src.connectors.gmail.build")
    @patch("src.connectors.gmail.Credentials")
    def test_auth_with_valid_token(self, mock_creds_cls, mock_build, tmp_path):
        token_path = tmp_path / "token.json"
        token_path.write_text('{"token": "fake"}')

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        gmail = Gmail(credentials_path="creds.json", token_path=str(token_path))
        gmail._get_service()

        mock_creds_cls.from_authorized_user_file.assert_called_once_with(
            str(token_path), Gmail.SCOPES
        )
        mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds)

    @patch("src.connectors.gmail.build")
    @patch("src.connectors.gmail.Request")
    @patch("src.connectors.gmail.Credentials")
    def test_auth_refreshes_expired_token(self, mock_creds_cls, mock_request_cls, mock_build, tmp_path):
        token_path = tmp_path / "token.json"
        token_path.write_text('{"token": "fake"}')

        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_me"
        mock_creds.to_json.return_value = '{"refreshed": true}'
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        gmail = Gmail(credentials_path="creds.json", token_path=str(token_path))
        gmail._get_service()

        mock_creds.refresh.assert_called_once()
        # Verify token was saved back
        assert token_path.read_text() == '{"refreshed": true}'

    @patch("src.connectors.gmail.InstalledAppFlow")
    @patch("src.connectors.gmail.build")
    def test_auth_runs_flow_when_no_token(self, mock_build, mock_flow_cls, tmp_path):
        token_path = tmp_path / "token.json"
        creds_path = tmp_path / "credentials.json"
        creds_path.write_text("{}")

        mock_creds = MagicMock()
        mock_creds.to_json.return_value = '{"new": true}'
        mock_flow = MagicMock()
        mock_flow.run_local_server.return_value = mock_creds
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        gmail = Gmail(credentials_path=str(creds_path), token_path=str(token_path))
        gmail._get_service()

        mock_flow_cls.from_client_secrets_file.assert_called_once_with(
            str(creds_path), Gmail.SCOPES
        )
        assert token_path.read_text() == '{"new": true}'


class TestGetUnreadEmails:
    """Tests for Gmail.get_unread_emails."""

    def _make_gmail_with_mock_service(self):
        gmail = Gmail.__new__(Gmail)
        gmail._service = MagicMock()
        gmail._credentials_path = "creds.json"
        gmail._token_path = "token.json"
        return gmail

    def test_empty_inbox(self):
        gmail = self._make_gmail_with_mock_service()
        gmail._service.users().messages().list().execute.return_value = {
            "resultSizeEstimate": 0
        }
        result = asyncio.run(gmail.get_unread_emails())
        assert result == []

    def test_fetches_and_parses_emails(self):
        gmail = self._make_gmail_with_mock_service()

        # list returns message IDs
        gmail._service.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg1"}, {"id": "msg2"}],
            "resultSizeEstimate": 2,
        }

        # get returns full message for each ID
        plain_body = base64.urlsafe_b64encode(b"Body text").decode()
        full_msg = {
            "id": "msg1",
            "threadId": "thread1",
            "snippet": "Body...",
            "labelIds": ["INBOX", "UNREAD"],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Test Subject"},
                    {"name": "From", "value": "test@example.com"},
                    {"name": "Date", "value": "Mon, 4 Mar 2026 10:00:00 +0000"},
                ],
                "mimeType": "text/plain",
                "body": {"data": plain_body},
            },
        }
        gmail._service.users().messages().get().execute.return_value = full_msg

        result = asyncio.run(gmail.get_unread_emails(max_results=5))
        assert len(result) == 2
        assert result[0].id == "msg1"
        assert result[0].subject == "Test Subject"
        assert result[0].body_plain == "Body text"


class TestGetEmail:
    """Tests for Gmail.get_email."""

    def _make_gmail_with_mock_service(self):
        gmail = Gmail.__new__(Gmail)
        gmail._service = MagicMock()
        gmail._credentials_path = "creds.json"
        gmail._token_path = "token.json"
        return gmail

    def test_get_single_email(self):
        gmail = self._make_gmail_with_mock_service()
        plain_body = base64.urlsafe_b64encode(b"Single email body").decode()
        gmail._service.users().messages().get().execute.return_value = {
            "id": "msg99",
            "threadId": "thread99",
            "snippet": "Single...",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "Subject", "value": "Specific Email"},
                    {"name": "From", "value": "specific@example.com"},
                ],
                "mimeType": "text/plain",
                "body": {"data": plain_body},
            },
        }
        email = asyncio.run(gmail.get_email("msg99"))
        assert email.id == "msg99"
        assert email.subject == "Specific Email"
        assert email.body_plain == "Single email body"
```

**Step 2: Run to verify they fail**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && python -m pytest tests/test_gmail_connector.py -v`
Expected: FAIL — `_get_service`, `build`, `Credentials`, `InstalledAppFlow` not imported/defined yet.

**Step 3: Commit the tests**

```bash
git add tests/test_gmail_connector.py
git commit -m "test: add auth and fetch tests for Gmail connector"
```

---

### Task 7: Implement auth and fetch methods

**Files:**
- Modify: `src/connectors/gmail.py`

**Step 1: Add imports and implement _get_service, get_unread_emails, get_email**

Update `src/connectors/gmail.py` to its final form:

```python
import asyncio
import base64
import re
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.models import Email


class Gmail:
    """Minimal Gmail connector — fetch-only, OAuth2 auth."""

    SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

    def __init__(
        self,
        credentials_path: str = "credentials.json",
        token_path: str = "token.json",
    ):
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._service = None

    def _get_service(self):
        """Authenticate and build the Gmail API service (lazy)."""
        if self._service is not None:
            return self._service

        creds = None
        token_path = Path(self._token_path)

        if token_path.exists():
            creds = Credentials.from_authorized_user_file(str(token_path), self.SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self._credentials_path, self.SCOPES
                )
                creds = flow.run_local_server(port=0)
            token_path.write_text(creds.to_json())

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    @staticmethod
    def _parse_message(raw: dict[str, Any]) -> Email:
        """Parse a Gmail API message resource into an Email."""
        headers = {
            h["name"].lower(): h["value"]
            for h in raw.get("payload", {}).get("headers", [])
        }

        body_plain = Gmail._extract_body(raw.get("payload", {}))

        return Email(
            id=raw["id"],
            thread_id=raw["threadId"],
            subject=headers.get("subject", ""),
            sender=headers.get("from", ""),
            body_plain=body_plain,
            snippet=raw.get("snippet", ""),
            date=headers.get("date"),
            labels=raw.get("labelIds", []),
        )

    @staticmethod
    def _extract_body(payload: dict[str, Any]) -> str:
        """Recursively extract plain-text body from MIME payload."""
        mime_type = payload.get("mimeType", "")

        if mime_type == "text/plain":
            data = payload.get("body", {}).get("data", "")
            if data:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        if mime_type.startswith("multipart/"):
            for part in payload.get("parts", []):
                text = Gmail._extract_body(part)
                if text:
                    return text

        if mime_type == "text/html":
            data = payload.get("body", {}).get("data", "")
            if data:
                html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                return re.sub(r"<[^>]+>", "", html)

        return ""

    def _fetch_messages_sync(self, max_results: int) -> list[Email]:
        """Synchronous fetch — called via to_thread."""
        service = self._get_service()
        response = (
            service.users()
            .messages()
            .list(userId="me", q="is:unread", maxResults=max_results)
            .execute()
        )

        messages = response.get("messages", [])
        if not messages:
            return []

        emails = []
        for msg_ref in messages:
            raw = (
                service.users()
                .messages()
                .get(userId="me", id=msg_ref["id"], format="full")
                .execute()
            )
            emails.append(self._parse_message(raw))
        return emails

    def _fetch_message_sync(self, email_id: str) -> Email:
        """Synchronous single-message fetch."""
        service = self._get_service()
        raw = (
            service.users()
            .messages()
            .get(userId="me", id=email_id, format="full")
            .execute()
        )
        return self._parse_message(raw)

    async def get_unread_emails(self, max_results: int = 10) -> list[Email]:
        """Fetch unread emails. Non-blocking I/O."""
        return await asyncio.to_thread(self._fetch_messages_sync, max_results)

    async def get_email(self, email_id: str) -> Email:
        """Fetch a single email by ID."""
        return await asyncio.to_thread(self._fetch_message_sync, email_id)
```

**Step 2: Run all tests**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && python -m pytest tests/ -v`
Expected: All tests PASS (model tests + parser tests + auth tests + fetch tests).

**Step 3: Commit**

```bash
git add src/connectors/gmail.py
git commit -m "feat: implement Gmail auth and async email fetching"
```

---

### Task 8: Update main.py to use new Email model

**Files:**
- Modify: `src/main.py:60-61`

**Step 1: Update Gmail instantiation in main.py**

The `main()` function currently calls `Gmail()` with no args. The new constructor still defaults to `credentials.json`/`token.json`, so no change is needed there. However, verify the import and model changes are compatible:

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && python -c "from src.main import main; print('imports OK')"`
Expected: `imports OK`

**Step 2: Commit if any changes were needed**

```bash
git add src/main.py
git commit -m "chore: verify main.py compatibility with updated connector"
```

---

### Task 9: Final integration verification

**Step 1: Run full test suite**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && python -m pytest tests/ -v --tb=short`
Expected: All tests PASS.

**Step 2: Quick smoke test with real credentials (manual)**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && python -c "
import asyncio
from src.connectors.gmail import Gmail

async def smoke():
    g = Gmail()
    emails = await g.get_unread_emails(max_results=3)
    for e in emails:
        print(f'{e.sender}: {e.subject}')

asyncio.run(smoke())
"`
Expected: Prints up to 3 unread email subjects from the real inbox.

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete minimal gmail connector with tests"
```
