"""Gmail API connector: auth, fetch, parse, and attachment download."""

from __future__ import annotations

import asyncio
import base64
import os
from datetime import datetime
from email.utils import parsedate_to_datetime

from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from src.models import Attachment, Email


class Gmail:
    """Async-friendly Gmail connector wrapping the Google API client."""

    SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

    def __init__(
        self,
        credentials_path: str = "credentials.json",
        token_path: str = "token.json",
    ) -> None:
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._service = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _get_service(self):
        """Lazily authenticate and build the Gmail API service."""
        if self._service is not None:
            return self._service

        creds: Credentials | None = None

        if os.path.exists(self._token_path):
            creds = Credentials.from_authorized_user_file(
                self._token_path, self.SCOPES
            )

        if creds is None or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    self._credentials_path, self.SCOPES
                )
                creds = flow.run_local_server(port=0)
            with open(self._token_path, "w") as f:
                f.write(creds.to_json())

        self._service = build("gmail", "v1", credentials=creds)
        return self._service

    # ------------------------------------------------------------------
    # Message parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_message(raw: dict) -> Email:
        """Parse a Gmail API message resource into an Email dataclass."""
        payload = raw.get("payload", {})
        headers_list = payload.get("headers", [])

        # Build a case-insensitive header lookup (first occurrence wins).
        headers: dict[str, str] = {}
        for h in headers_list:
            key = h["name"].lower()
            if key not in headers:
                headers[key] = h["value"]

        # Parse date
        date: datetime | None = None
        date_str = headers.get("date", "")
        if date_str:
            try:
                date = parsedate_to_datetime(date_str)
            except (ValueError, TypeError):
                date = None

        # Parse comma-separated list headers
        def _split_comma(value: str) -> list[str]:
            return [s.strip() for s in value.split(",") if s.strip()]

        # Parse space-separated References header
        def _split_space(value: str) -> list[str]:
            return [s for s in value.split() if s]

        # Extract body
        body_plain, body_html = Gmail._extract_body(payload)

        # Extract attachments
        attachments = Gmail._extract_attachments(payload)

        return Email(
            id=raw.get("id", ""),
            thread_id=raw.get("threadId", ""),
            subject=headers.get("subject", ""),
            sender=headers.get("from", ""),
            recipients=_split_comma(headers.get("to", "")),
            cc=_split_comma(headers.get("cc", "")),
            bcc=_split_comma(headers.get("bcc", "")),
            date=date,
            message_id=headers.get("message-id", ""),
            in_reply_to=headers.get("in-reply-to", ""),
            references=_split_space(headers.get("references", "")),
            snippet=raw.get("snippet", ""),
            body_plain=body_plain,
            body_html=body_html,
            labels=raw.get("labelIds", []),
            attachments=attachments,
        )

    @staticmethod
    def _extract_body(payload: dict) -> tuple[str, str]:
        """Walk MIME parts and return (plain_text, raw_html).

        If no text/plain part exists but text/html does, BeautifulSoup is used
        to derive plain text from the HTML.
        """
        plain: str = ""
        html: str = ""

        def _decode_data(body: dict) -> str:
            data = body.get("data", "")
            if not data:
                return ""
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

        def _walk(part: dict) -> None:
            nonlocal plain, html
            mime = part.get("mimeType", "")
            parts = part.get("parts")

            if parts:
                for sub in parts:
                    _walk(sub)
                return

            # Leaf part — skip attachments (they have a filename).
            if part.get("filename"):
                return

            body = part.get("body", {})
            if mime == "text/plain" and not plain:
                plain = _decode_data(body)
            elif mime == "text/html" and not html:
                html = _decode_data(body)

        _walk(payload)

        # If no text/plain but we have html, derive plain from html.
        if not plain and html:
            plain = Gmail._html_to_text(html)

        return plain, html

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Strip HTML tags using BeautifulSoup."""
        soup = BeautifulSoup(html, "html.parser")
        return soup.get_text(separator="\n", strip=True)

    @staticmethod
    def _extract_attachments(payload: dict) -> list[Attachment]:
        """Walk MIME parts and collect attachment metadata."""
        attachments: list[Attachment] = []

        def _walk(part: dict) -> None:
            filename = part.get("filename", "")
            parts = part.get("parts")

            if parts:
                for sub in parts:
                    _walk(sub)

            if filename:
                body = part.get("body", {})
                attachments.append(
                    Attachment(
                        filename=filename,
                        mime_type=part.get("mimeType", ""),
                        size=body.get("size", 0),
                        attachment_id=body.get("attachmentId", ""),
                    )
                )

        _walk(payload)
        return attachments

    # ------------------------------------------------------------------
    # Sync fetch helpers
    # ------------------------------------------------------------------

    def _fetch_messages_sync(self, max_results: int = 10) -> list[Email]:
        """Fetch unread messages synchronously."""
        service = self._get_service() if self._service is None else self._service
        response = (
            service.users()
            .messages()
            .list(userId="me", q="is:unread", maxResults=max_results)
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

    def _fetch_message_sync(self, email_id: str) -> Email:
        """Fetch a single message by ID synchronously."""
        service = self._get_service() if self._service is None else self._service
        raw = (
            service.users()
            .messages()
            .get(userId="me", id=email_id, format="full")
            .execute()
        )
        return self._parse_message(raw)

    def _download_attachment_sync(
        self, message_id: str, attachment_id: str
    ) -> bytes:
        """Download attachment data and return raw bytes."""
        service = self._get_service() if self._service is None else self._service
        response = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        data = response.get("data", "")
        return base64.urlsafe_b64decode(data)

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def get_unread_emails(self, max_results: int = 10) -> list[Email]:
        """Fetch unread emails asynchronously."""
        return await asyncio.to_thread(self._fetch_messages_sync, max_results)

    async def get_email(self, email_id: str) -> Email:
        """Fetch a single email by ID asynchronously."""
        return await asyncio.to_thread(self._fetch_message_sync, email_id)

    async def download_attachment(
        self, message_id: str, attachment_id: str
    ) -> bytes:
        """Download attachment data asynchronously."""
        return await asyncio.to_thread(
            self._download_attachment_sync, message_id, attachment_id
        )
