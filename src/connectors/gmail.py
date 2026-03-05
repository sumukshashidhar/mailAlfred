"""Gmail API connector: auth, fetch, parse, and attachment download."""

from __future__ import annotations

import asyncio
import base64
import os
import stat
from datetime import datetime
from email.utils import getaddresses, parsedate_to_datetime

from bs4 import BeautifulSoup
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from tqdm import tqdm

from src.models import Attachment, Email


class Gmail:
    """Async-friendly Gmail connector wrapping the Google API client."""

    SCOPES = [
        # Gmail - full access
        "https://mail.google.com/",
        # Calendar - full access
        "https://www.googleapis.com/auth/calendar",
        # Drive - full access
        "https://www.googleapis.com/auth/drive",
    ]

    def __init__(
        self,
        credentials_path: str = "credentials.json",
        token_path: str = "token.json",
    ) -> None:
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._service = None
        self._lock = asyncio.Lock()  # httplib2 is not thread-safe

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
            fd = os.open(
                self._token_path,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                stat.S_IRUSR | stat.S_IWUSR,  # 0o600
            )
            with os.fdopen(fd, "w") as f:
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

        # Parse address list headers (RFC 5322 compliant)
        def _split_addresses(value: str) -> list[str]:
            if not value:
                return []
            return [addr for _, addr in getaddresses([value]) if addr]

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
            recipients=_split_addresses(headers.get("to", "")),
            cc=_split_addresses(headers.get("cc", "")),
            bcc=_split_addresses(headers.get("bcc", "")),
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

            # Skip attachments (they have a filename) and container parts.
            if part.get("filename") or parts:
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

    def _fetch_all_messages_sync(
        self,
        query: str = "",
        after_date: datetime | None = None,
        batch_size: int = 100,
        max_emails: int = 0,
    ) -> list[Email]:
        """Fetch messages matching query, with pagination.

        Args:
            max_emails: Stop after fetching this many. 0 means no limit.
        """
        service = self._get_service()

        q = query
        if after_date:
            date_str = after_date.strftime("%Y/%m/%d")
            q = f"{q} after:{date_str}".strip()

        all_emails: list[Email] = []
        page_token = None
        pbar = tqdm(
            total=max_emails if max_emails > 0 else None,
            desc="Fetching emails",
            unit="email",
        )

        while True:
            page_size = batch_size
            if max_emails > 0:
                remaining = max_emails - len(all_emails)
                if remaining <= 0:
                    break
                page_size = min(batch_size, remaining)

            kwargs: dict = {"userId": "me", "maxResults": page_size}
            if q:
                kwargs["q"] = q
            if page_token:
                kwargs["pageToken"] = page_token

            response = service.users().messages().list(**kwargs).execute()
            messages = response.get("messages", [])

            for stub in messages:
                if max_emails > 0 and len(all_emails) >= max_emails:
                    break
                raw = (
                    service.users()
                    .messages()
                    .get(userId="me", id=stub["id"], format="full")
                    .execute()
                )
                all_emails.append(self._parse_message(raw))
                pbar.update(1)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        pbar.close()
        return all_emails

    def _fetch_messages_sync(self, max_results: int = 10) -> list[Email]:
        """Fetch unread messages synchronously."""
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
        service = self._get_service()
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
        service = self._get_service()
        response = (
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
            .execute()
        )
        data = response.get("data")
        if not data:
            raise ValueError(
                f"No data returned for attachment {attachment_id} "
                f"on message {message_id}"
            )
        return base64.urlsafe_b64decode(data)

    # ------------------------------------------------------------------
    # Thread fetch (sync)
    # ------------------------------------------------------------------

    def _get_thread_sync(self, thread_id: str) -> list[Email]:
        """Fetch all messages in a thread, ordered chronologically."""
        service = self._get_service()
        response = (
            service.users()
            .threads()
            .get(userId="me", id=thread_id, format="full")
            .execute()
        )
        messages = response.get("messages", [])
        return [self._parse_message(m) for m in messages]

    # ------------------------------------------------------------------
    # Label operations (sync)
    # ------------------------------------------------------------------

    def _list_labels_sync(self) -> list[dict]:
        """List all Gmail labels. Returns list of {id, name, type, ...}."""
        service = self._get_service()
        response = service.users().labels().list(userId="me").execute()
        return response.get("labels", [])

    def _apply_labels_sync(
        self,
        email_id: str,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> dict:
        """Modify labels on a message."""
        service = self._get_service()
        body: dict = {}
        if add_label_ids:
            body["addLabelIds"] = add_label_ids
        if remove_label_ids:
            body["removeLabelIds"] = remove_label_ids
        return (
            service.users()
            .messages()
            .modify(userId="me", id=email_id, body=body)
            .execute()
        )

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def fetch_all_emails(
        self,
        query: str = "",
        after_date: datetime | None = None,
        batch_size: int = 100,
        max_emails: int = 0,
    ) -> list[Email]:
        """Fetch emails matching query, with pagination, asynchronously."""
        async with self._lock:
            return await asyncio.to_thread(
                self._fetch_all_messages_sync, query, after_date, batch_size, max_emails
            )

    async def list_message_ids(
        self,
        query: str = "",
        max_results: int = 100,
        page_token: str | None = None,
    ) -> tuple[list[str], str | None]:
        """Return a page of message IDs matching the query."""
        async with self._lock:
            return await asyncio.to_thread(
                self._list_message_ids_sync, query, max_results, page_token,
            )

    def _list_message_ids_sync(
        self,
        query: str,
        max_results: int,
        page_token: str | None,
    ) -> tuple[list[str], str | None]:
        service = self._get_service()
        kwargs: dict = {"userId": "me", "maxResults": max_results}
        if query:
            kwargs["q"] = query
        if page_token:
            kwargs["pageToken"] = page_token
        response = service.users().messages().list(**kwargs).execute()
        ids = [m["id"] for m in response.get("messages", [])]
        return ids, response.get("nextPageToken")

    async def batch_get_emails(self, email_ids: list[str]) -> list[Email]:
        """Fetch multiple emails in a single batched HTTP request."""
        async with self._lock:
            return await asyncio.to_thread(self._batch_get_emails_sync, email_ids)

    def _batch_get_emails_sync(self, email_ids: list[str]) -> list[Email]:
        """Use Gmail BatchHttpRequest to fetch many messages at once."""
        service = self._get_service()
        results: dict[str, Email] = {}

        def _callback(request_id, response, exception):
            if exception is not None:
                return
            results[request_id] = self._parse_message(response)

        batch = service.new_batch_http_request(callback=_callback)
        for eid in email_ids:
            batch.add(
                service.users().messages().get(userId="me", id=eid, format="full"),
                request_id=eid,
            )
        batch.execute()

        # Return in original order
        return [results[eid] for eid in email_ids if eid in results]

    async def get_unread_emails(self, max_results: int = 10) -> list[Email]:
        """Fetch unread emails asynchronously."""
        async with self._lock:
            return await asyncio.to_thread(self._fetch_messages_sync, max_results)

    async def get_thread(self, thread_id: str) -> list[Email]:
        """Fetch all messages in a thread, asynchronously."""
        async with self._lock:
            return await asyncio.to_thread(self._get_thread_sync, thread_id)

    async def get_email(self, email_id: str) -> Email:
        """Fetch a single email by ID asynchronously."""
        async with self._lock:
            return await asyncio.to_thread(self._fetch_message_sync, email_id)

    async def download_attachment(
        self, message_id: str, attachment_id: str
    ) -> bytes:
        """Download attachment data asynchronously."""
        async with self._lock:
            return await asyncio.to_thread(
                self._download_attachment_sync, message_id, attachment_id
            )

    async def list_labels(self) -> list[dict]:
        """List all Gmail labels asynchronously."""
        async with self._lock:
            return await asyncio.to_thread(self._list_labels_sync)

    async def apply_labels(
        self,
        email_id: str,
        add_label_ids: list[str] | None = None,
        remove_label_ids: list[str] | None = None,
    ) -> dict:
        """Modify labels on a message asynchronously."""
        async with self._lock:
            return await asyncio.to_thread(
                self._apply_labels_sync, email_id, add_label_ids, remove_label_ids
            )
