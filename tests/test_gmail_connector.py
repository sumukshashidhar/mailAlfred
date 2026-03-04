"""Tests for the Gmail connector with mocked Gmail API responses."""

import asyncio
import base64
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, mock_open

import pytest

from src.connectors.gmail import Gmail
from src.models import Attachment, Email


# ---------------------------------------------------------------------------
# Helpers to build Gmail API message dicts
# ---------------------------------------------------------------------------


def _header(name: str, value: str) -> dict:
    return {"name": name, "value": value}


def _make_message(
    msg_id: str = "msg1",
    thread_id: str = "thread1",
    snippet: str = "A snippet",
    label_ids: list[str] | None = None,
    headers: list[dict] | None = None,
    payload_body: dict | None = None,
    payload_mime: str = "text/plain",
    payload_parts: list[dict] | None = None,
    payload_filename: str = "",
) -> dict:
    """Build a minimal Gmail API message resource."""
    if label_ids is None:
        label_ids = ["INBOX", "UNREAD"]
    if headers is None:
        headers = [
            _header("Subject", "Test Subject"),
            _header("From", "alice@example.com"),
            _header("To", "bob@example.com"),
            _header("Date", "Mon, 02 Mar 2026 10:00:00 +0000"),
        ]
    payload: dict = {
        "mimeType": payload_mime,
        "headers": headers,
        "filename": payload_filename,
    }
    if payload_parts is not None:
        payload["parts"] = payload_parts
    if payload_body is not None:
        payload["body"] = payload_body
    else:
        payload["body"] = {"size": 0}
    return {
        "id": msg_id,
        "threadId": thread_id,
        "snippet": snippet,
        "labelIds": label_ids,
        "payload": payload,
    }


def _plain_part(text: str, filename: str = "") -> dict:
    encoded = base64.urlsafe_b64encode(text.encode()).decode()
    return {
        "mimeType": "text/plain",
        "headers": [_header("Content-Type", "text/plain; charset=utf-8")],
        "body": {"size": len(text), "data": encoded},
        "filename": filename,
    }


def _html_part(html: str, filename: str = "") -> dict:
    encoded = base64.urlsafe_b64encode(html.encode()).decode()
    return {
        "mimeType": "text/html",
        "headers": [_header("Content-Type", "text/html; charset=utf-8")],
        "body": {"size": len(html), "data": encoded},
        "filename": filename,
    }


def _attachment_part(
    filename: str, mime_type: str, size: int, attachment_id: str
) -> dict:
    return {
        "mimeType": mime_type,
        "filename": filename,
        "headers": [
            _header("Content-Disposition", f'attachment; filename="{filename}"'),
        ],
        "body": {"size": size, "attachmentId": attachment_id},
    }


# ===========================================================================
# _parse_message tests
# ===========================================================================


class TestParseMessagePlainText:
    """Plain-text email extracts all headers, body, snippet, labels."""

    def test_extracts_all_headers(self):
        body_text = "Hello, plain text"
        raw = _make_message(
            headers=[
                _header("Subject", "Hello"),
                _header("From", "alice@example.com"),
                _header("To", "bob@example.com"),
                _header("Cc", "carol@example.com"),
                _header("Bcc", "dave@example.com"),
                _header("Date", "Mon, 02 Mar 2026 10:00:00 +0000"),
                _header("Message-ID", "<msg001@example.com>"),
                _header("In-Reply-To", "<msg000@example.com>"),
                _header("References", "<msg000@example.com> <msg-01@example.com>"),
            ],
            payload_body={
                "size": len(body_text),
                "data": base64.urlsafe_b64encode(body_text.encode()).decode(),
            },
        )

        email = Gmail._parse_message(raw)

        assert email.id == "msg1"
        assert email.thread_id == "thread1"
        assert email.subject == "Hello"
        assert email.sender == "alice@example.com"
        assert email.recipients == ["bob@example.com"]
        assert email.cc == ["carol@example.com"]
        assert email.bcc == ["dave@example.com"]
        assert email.message_id == "<msg001@example.com>"
        assert email.in_reply_to == "<msg000@example.com>"
        assert email.references == ["<msg000@example.com>", "<msg-01@example.com>"]
        assert email.snippet == "A snippet"
        assert email.labels == ["INBOX", "UNREAD"]
        assert email.body_plain == body_text
        assert email.body_html == ""

    def test_date_parsed_to_datetime(self):
        raw = _make_message(
            headers=[
                _header("Date", "Mon, 02 Mar 2026 10:00:00 +0000"),
            ],
            payload_body={"size": 0, "data": ""},
        )
        email = Gmail._parse_message(raw)
        assert isinstance(email.date, datetime)
        assert email.date == datetime(2026, 3, 2, 10, 0, 0, tzinfo=timezone.utc)


class TestParseMessageMultipart:
    """Multipart email: prefers text/plain, stores BOTH plain and html."""

    def test_prefers_plain_and_stores_html(self):
        raw = _make_message(
            payload_mime="multipart/alternative",
            payload_parts=[
                _plain_part("Plain body"),
                _html_part("<p>HTML body</p>"),
            ],
            payload_body={"size": 0},
        )

        email = Gmail._parse_message(raw)

        assert email.body_plain == "Plain body"
        assert email.body_html == "<p>HTML body</p>"


class TestParseMessageHtmlOnly:
    """HTML-only email: strips tags via BeautifulSoup for body_plain."""

    def test_html_only_creates_plain_from_html(self):
        html = "<html><body><h1>Title</h1><p>Hello world</p></body></html>"
        raw = _make_message(
            payload_mime="text/html",
            payload_body={
                "size": len(html),
                "data": base64.urlsafe_b64encode(html.encode()).decode(),
            },
        )

        email = Gmail._parse_message(raw)

        assert email.body_html == html
        # BeautifulSoup should strip tags
        assert "Title" in email.body_plain
        assert "Hello world" in email.body_plain
        assert "<p>" not in email.body_plain
        assert "<h1>" not in email.body_plain


class TestParseMessageMissingHeaders:
    """Graceful defaults when headers are missing."""

    def test_missing_headers_produce_defaults(self):
        raw = _make_message(
            headers=[],
            payload_body={"size": 0, "data": ""},
            label_ids=[],
        )

        email = Gmail._parse_message(raw)

        assert email.subject == ""
        assert email.sender == ""
        assert email.recipients == []
        assert email.cc == []
        assert email.bcc == []
        assert email.date is None
        assert email.message_id == ""
        assert email.in_reply_to == ""
        assert email.references == []
        assert email.labels == []


class TestParseMessageNestedMultipart:
    """Nested multipart/mixed containing multipart/alternative."""

    def test_nested_multipart_extracts_body(self):
        alternative_part = {
            "mimeType": "multipart/alternative",
            "headers": [],
            "body": {"size": 0},
            "filename": "",
            "parts": [
                _plain_part("Nested plain"),
                _html_part("<p>Nested html</p>"),
            ],
        }
        attachment = _attachment_part("doc.pdf", "application/pdf", 5000, "att1")

        raw = _make_message(
            payload_mime="multipart/mixed",
            payload_parts=[alternative_part, attachment],
            payload_body={"size": 0},
        )

        email = Gmail._parse_message(raw)

        assert email.body_plain == "Nested plain"
        assert email.body_html == "<p>Nested html</p>"
        assert len(email.attachments) == 1
        assert email.attachments[0].filename == "doc.pdf"


class TestParseMessageAttachments:
    """Extracts attachment metadata (no data download during parse)."""

    def test_attachment_metadata(self):
        raw = _make_message(
            payload_mime="multipart/mixed",
            payload_parts=[
                _plain_part("Body text"),
                _attachment_part("report.pdf", "application/pdf", 10240, "att123"),
                _attachment_part("image.png", "image/png", 2048, "att456"),
            ],
            payload_body={"size": 0},
        )

        email = Gmail._parse_message(raw)

        assert len(email.attachments) == 2
        att1 = email.attachments[0]
        assert att1.filename == "report.pdf"
        assert att1.mime_type == "application/pdf"
        assert att1.size == 10240
        assert att1.attachment_id == "att123"
        assert att1.data == b""  # no data downloaded during parse

        att2 = email.attachments[1]
        assert att2.filename == "image.png"
        assert att2.mime_type == "image/png"


class TestParseMessageDateParsing:
    """RFC 2822 date string converted to datetime."""

    def test_rfc2822_date(self):
        raw = _make_message(
            headers=[_header("Date", "Tue, 03 Mar 2026 15:30:00 -0500")],
            payload_body={"size": 0, "data": ""},
        )
        email = Gmail._parse_message(raw)
        assert email.date is not None
        assert email.date.year == 2026
        assert email.date.month == 3
        assert email.date.day == 3

    def test_invalid_date_returns_none(self):
        raw = _make_message(
            headers=[_header("Date", "not-a-date")],
            payload_body={"size": 0, "data": ""},
        )
        email = Gmail._parse_message(raw)
        assert email.date is None


class TestParseMessageMultipleRecipients:
    """Comma-separated To/Cc parsed into lists."""

    def test_multiple_recipients(self):
        raw = _make_message(
            headers=[
                _header("To", "bob@example.com, carol@example.com, dave@example.com"),
                _header("Cc", "eve@example.com,  frank@example.com"),
                _header("Bcc", "grace@example.com"),
            ],
            payload_body={"size": 0, "data": ""},
        )

        email = Gmail._parse_message(raw)

        assert email.recipients == [
            "bob@example.com",
            "carol@example.com",
            "dave@example.com",
        ]
        assert email.cc == ["eve@example.com", "frank@example.com"]
        assert email.bcc == ["grace@example.com"]


class TestParseMessageReferences:
    """Space-separated References header parsed into a list."""

    def test_references_parsed(self):
        raw = _make_message(
            headers=[
                _header(
                    "References",
                    "<ref1@example.com> <ref2@example.com> <ref3@example.com>",
                ),
            ],
            payload_body={"size": 0, "data": ""},
        )
        email = Gmail._parse_message(raw)
        assert email.references == [
            "<ref1@example.com>",
            "<ref2@example.com>",
            "<ref3@example.com>",
        ]


# ===========================================================================
# Auth tests (mocked)
# ===========================================================================


class TestAuth:
    """Tests for the _get_service authentication flow."""

    @patch("src.connectors.gmail.build")
    @patch("src.connectors.gmail.Credentials")
    def test_valid_token_loads_service(self, mock_creds_cls, mock_build):
        """Valid existing token is loaded and used to build the service."""
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        gmail = Gmail(
            credentials_path="creds.json", token_path="token.json"
        )

        with patch("builtins.open", mock_open()):
            with patch("os.path.exists", return_value=True):
                service = gmail._get_service()

        mock_creds_cls.from_authorized_user_file.assert_called_once_with(
            "token.json", Gmail.SCOPES
        )
        mock_build.assert_called_once_with("gmail", "v1", credentials=mock_creds)

    @patch("src.connectors.gmail.build")
    @patch("src.connectors.gmail.Request")
    @patch("src.connectors.gmail.Credentials")
    def test_expired_token_refreshes_and_saves(
        self, mock_creds_cls, mock_request_cls, mock_build
    ):
        """Expired token is refreshed and saved back to disk."""
        mock_creds = MagicMock()
        mock_creds.valid = False
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh_tok"
        mock_creds_cls.from_authorized_user_file.return_value = mock_creds

        gmail = Gmail(
            credentials_path="creds.json", token_path="token.json"
        )

        m = mock_open()
        with patch("builtins.open", m):
            with patch("os.path.exists", return_value=True):
                gmail._get_service()

        mock_creds.refresh.assert_called_once_with(mock_request_cls())
        # token should be written back
        m.assert_called_with("token.json", "w")

    @patch("src.connectors.gmail.build")
    @patch("src.connectors.gmail.InstalledAppFlow")
    def test_no_token_runs_installed_app_flow(self, mock_flow_cls, mock_build):
        """When no token.json exists, InstalledAppFlow is used."""
        mock_flow = MagicMock()
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_flow.run_local_server.return_value = mock_creds
        mock_flow_cls.from_client_secrets_file.return_value = mock_flow

        gmail = Gmail(
            credentials_path="creds.json", token_path="token.json"
        )

        m = mock_open()
        with patch("builtins.open", m):
            with patch("os.path.exists", return_value=False):
                gmail._get_service()

        mock_flow_cls.from_client_secrets_file.assert_called_once_with(
            "creds.json", Gmail.SCOPES
        )
        mock_flow.run_local_server.assert_called_once_with(port=0)
        # token should be written
        m.assert_called_with("token.json", "w")


# ===========================================================================
# Fetch tests (mocked)
# ===========================================================================


class TestFetchEmails:
    """Tests for get_unread_emails, get_email, download_attachment."""

    def _mock_service(self):
        """Build a mock Gmail API service."""
        service = MagicMock()
        return service

    def test_get_unread_emails_empty_inbox(self):
        """Empty inbox returns an empty list."""
        service = self._mock_service()
        service.users().messages().list().execute.return_value = {
            "resultSizeEstimate": 0,
        }

        gmail = Gmail.__new__(Gmail)
        gmail._service = service

        result = gmail._fetch_messages_sync(max_results=10)
        assert result == []

    def test_get_unread_emails_fetches_messages(self):
        """Fetches message list, then each message; returns Email objects."""
        service = self._mock_service()

        body_text = "Hello"
        encoded_body = base64.urlsafe_b64encode(body_text.encode()).decode()

        # messages().list() returns two message stubs
        service.users().messages().list().execute.return_value = {
            "messages": [{"id": "m1", "threadId": "t1"}, {"id": "m2", "threadId": "t2"}],
            "resultSizeEstimate": 2,
        }

        def get_side_effect(**kwargs):
            """Return different messages based on the id."""
            mock_req = MagicMock()
            msg_id = kwargs.get("id", "m1")
            mock_req.execute.return_value = _make_message(
                msg_id=msg_id,
                thread_id=f"t_{msg_id}",
                headers=[
                    _header("Subject", f"Subject {msg_id}"),
                    _header("From", "sender@example.com"),
                    _header("To", "recipient@example.com"),
                    _header("Date", "Mon, 02 Mar 2026 10:00:00 +0000"),
                ],
                payload_body={"size": len(body_text), "data": encoded_body},
            )
            return mock_req

        service.users().messages().get.side_effect = get_side_effect

        gmail = Gmail.__new__(Gmail)
        gmail._service = service

        result = gmail._fetch_messages_sync(max_results=10)

        assert len(result) == 2
        assert all(isinstance(e, Email) for e in result)
        assert result[0].id == "m1"
        assert result[1].id == "m2"
        assert result[0].subject == "Subject m1"

    def test_get_email_single_message(self):
        """Fetches a single message by ID."""
        service = self._mock_service()

        body_text = "Single message"
        encoded_body = base64.urlsafe_b64encode(body_text.encode()).decode()

        service.users().messages().get().execute.return_value = _make_message(
            msg_id="m42",
            thread_id="t42",
            headers=[
                _header("Subject", "Important"),
                _header("From", "boss@example.com"),
                _header("To", "me@example.com"),
                _header("Date", "Mon, 02 Mar 2026 12:00:00 +0000"),
            ],
            payload_body={"size": len(body_text), "data": encoded_body},
        )

        gmail = Gmail.__new__(Gmail)
        gmail._service = service

        email = gmail._fetch_message_sync("m42")

        assert isinstance(email, Email)
        assert email.id == "m42"
        assert email.subject == "Important"
        assert email.body_plain == body_text

    def test_download_attachment(self):
        """Downloads attachment data by message_id + attachment_id."""
        service = self._mock_service()

        raw_bytes = b"PDF_CONTENT_HERE"
        encoded = base64.urlsafe_b64encode(raw_bytes).decode()

        service.users().messages().attachments().get().execute.return_value = {
            "data": encoded,
            "size": len(raw_bytes),
        }

        gmail = Gmail.__new__(Gmail)
        gmail._service = service

        result = gmail._download_attachment_sync("msg1", "att1")

        assert result == raw_bytes


class TestAsyncWrappers:
    """Async methods delegate to sync via asyncio.to_thread."""

    @pytest.mark.asyncio
    async def test_get_unread_emails_async(self):
        """Async get_unread_emails wraps _fetch_messages_sync."""
        gmail = Gmail.__new__(Gmail)
        gmail._service = MagicMock()

        expected = [Email(id="1", thread_id="t1")]
        with patch.object(gmail, "_fetch_messages_sync", return_value=expected):
            result = await gmail.get_unread_emails(max_results=5)

        assert result == expected

    @pytest.mark.asyncio
    async def test_get_email_async(self):
        """Async get_email wraps _fetch_message_sync."""
        gmail = Gmail.__new__(Gmail)
        gmail._service = MagicMock()

        expected = Email(id="42", thread_id="t42")
        with patch.object(gmail, "_fetch_message_sync", return_value=expected):
            result = await gmail.get_email("42")

        assert result == expected

    @pytest.mark.asyncio
    async def test_download_attachment_async(self):
        """Async download_attachment wraps _download_attachment_sync."""
        gmail = Gmail.__new__(Gmail)
        gmail._service = MagicMock()

        expected = b"file_data"
        with patch.object(
            gmail, "_download_attachment_sync", return_value=expected
        ):
            result = await gmail.download_attachment("msg1", "att1")

        assert result == expected
