"""
Gmail Connector - Fetch and classify emails with persistent tracking.

Features:
    - Iterator pattern for lazy email fetching with pagination
    - Pointer logic: stops at first seen email (assumes chronological order)
    - Persistent seen-email cache via diskcache
    - Label management: create, add, remove labels (including nested sublabels)

Usage:
    from src.connectors.gmail_connector import GmailConnector

    with GmailConnector() as gmail:
        for email in gmail:
            logger.info(email.subject)
            gmail.classify_email(email.id, "classifications/bulk_content")
"""

import base64
import os
import webbrowser
from contextlib import suppress
from email.utils import parsedate_to_datetime
from itertools import islice
from pathlib import Path
from typing import Iterator, Optional

from diskcache import Cache
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from loguru import logger

from src.models.email import Email


# Gmail API scopes
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Default configuration
DEFAULT_CREDENTIALS_PATH = "credentials.json"
DEFAULT_TOKEN_PATH = "token.json"
DEFAULT_CACHE_DIR = ".cache/gmail_seen"
MAX_RESULTS_PER_PAGE = 100


class GmailConnector:
    """
    Gmail API connector with seen-email tracking and label management.
    
    Supports iteration over new emails with automatic pointer logic -
    stops fetching when encountering an already-seen email ID.
    """

    def __init__(
        self,
        credentials_path: str = DEFAULT_CREDENTIALS_PATH,
        token_path: str = DEFAULT_TOKEN_PATH,
        cache_dir: str = DEFAULT_CACHE_DIR,
        label_ids: Optional[list[str]] = None,
        query: Optional[str] = None,
    ):
        self._credentials_path = credentials_path
        self._token_path = token_path
        self._label_ids = label_ids or ["INBOX"]
        self._query = query
        
        # Lazy-initialized Gmail service
        self._service = None
        
        # Persistent cache for seen email IDs
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        self._seen_cache = Cache(cache_dir)
        
        # In-memory cache for label name -> ID mapping
        self._label_cache: dict[str, str] = {}

    # -------------------------------------------------------------------------
    # Context Manager
    # -------------------------------------------------------------------------

    def __enter__(self) -> "GmailConnector":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self.close()
        return False

    def close(self) -> None:
        """Close the diskcache connection."""
        self._seen_cache.close()

    # -------------------------------------------------------------------------
    # Gmail Service
    # -------------------------------------------------------------------------

    @property
    def service(self):
        """Lazily initialize and return the Gmail API service."""
        if self._service is None:
            self._service = self._authenticate()
        return self._service

    def _authenticate(self):
        """Authenticate with Gmail API using OAuth2."""
        creds = self._load_cached_credentials()
        if creds and creds.valid:
            return build("gmail", "v1", credentials=creds)
        creds = self._refresh_or_login(creds)
        self._save_token(creds)
        return build("gmail", "v1", credentials=creds)

    def _load_cached_credentials(self) -> Optional[Credentials]:
        if not os.path.exists(self._token_path):
            return None
        return Credentials.from_authorized_user_file(self._token_path, SCOPES)

    def _refresh_or_login(self, creds: Optional[Credentials]) -> Credentials:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            return creds
        return self._run_oauth_flow()

    def _run_oauth_flow(self) -> Credentials:
        if not os.path.exists(self._credentials_path):
            raise FileNotFoundError(
                f"OAuth credentials not found: {self._credentials_path}\n"
                "Download from Google Cloud Console → APIs & Services → Credentials"
            )
        flow = InstalledAppFlow.from_client_secrets_file(self._credentials_path, SCOPES)
        try:
            return flow.run_local_server(port=0)
        except webbrowser.Error:
            logger.info("No runnable browser detected; falling back to manual auth flow.")
            return flow.run_local_server(port=0, open_browser=False)

    def _save_token(self, creds: Credentials) -> None:
        with open(self._token_path, "w") as f:
            f.write(creds.to_json())

    # -------------------------------------------------------------------------
    # Email Iteration
    # -------------------------------------------------------------------------

    def __iter__(self) -> Iterator[Email]:
        """Iterate over new (unseen) emails, stopping at first seen email."""
        return self.iter_messages()

    def fetch_all(
        self,
        message_format: str = "full",
        metadata_headers: Optional[list[str]] = None,
    ) -> Iterator[Email]:
        """Iterate over ALL emails (ignores seen cache, doesn't stop early)."""
        return self.iter_messages(
            use_seen_cache=False,
            message_format=message_format,
            metadata_headers=metadata_headers,
        )

    def iter_messages(
        self,
        use_seen_cache: bool = True,
        message_format: str = "full",
        metadata_headers: Optional[list[str]] = None,
    ) -> Iterator[Email]:
        """Iterate over emails with configurable Gmail format and metadata headers."""
        return _EmailIterator(
            service=self.service,
            seen_cache=self._seen_cache,
            label_ids=self._label_ids,
            query=self._query,
            use_seen_cache=use_seen_cache,
            message_format=message_format,
            metadata_headers=metadata_headers,
        )

    def fetch_email(
        self,
        msg_id: str,
        message_format: str = "full",
        metadata_headers: Optional[list[str]] = None,
    ) -> Email:
        """Fetch a single email by ID with the requested Gmail message format."""
        params = {"userId": "me", "id": msg_id, "format": message_format}
        if message_format == "metadata" and metadata_headers:
            params["metadataHeaders"] = metadata_headers
        msg = self.service.users().messages().get(**params).execute()
        return _EmailIterator.parse_message(msg)

    # -------------------------------------------------------------------------
    # Seen Cache Management
    # -------------------------------------------------------------------------

    def get_seen_count(self) -> int:
        """Return count of emails in the seen cache."""
        return len(self._seen_cache)

    def clear_seen_cache(self) -> None:
        """Clear seen cache (next iteration will fetch all emails)."""
        self._seen_cache.clear()

    def mark_as_seen(self, email_id: str) -> None:
        """Manually mark an email as seen."""
        self._seen_cache.set(email_id, True)

    def is_seen(self, email_id: str) -> bool:
        """Check if an email has been seen."""
        return email_id in self._seen_cache

    # -------------------------------------------------------------------------
    # Label Management
    # -------------------------------------------------------------------------

    def list_labels(self) -> list[dict]:
        """List all Gmail labels."""
        response = self.service.users().labels().list(userId="me").execute()
        return response.get("labels", [])

    def get_label_id(self, label_name: str) -> Optional[str]:
        """Get label ID by name (cached)."""
        if label_name in self._label_cache:
            return self._label_cache[label_name]
        
        for label in self.list_labels():
            self._label_cache[label["name"]] = label["id"]
        
        return self._label_cache.get(label_name)

    def create_label(self, label_name: str, visible: bool = True) -> str:
        """Create a new label (supports nested labels via '/')."""
        body = {
            "name": label_name,
            "labelListVisibility": "labelShow" if visible else "labelHide",
            "messageListVisibility": "show",
        }
        result = self.service.users().labels().create(userId="me", body=body).execute()
        self._label_cache[label_name] = result["id"]
        return result["id"]

    def get_or_create_label(self, label_name: str) -> str:
        """Get label ID, creating the label if it doesn't exist."""
        label_id = self.get_label_id(label_name)
        if label_id is None:
            label_id = self.create_label(label_name)
        return label_id

    def add_labels(self, email_id: str, label_names: list[str]) -> None:
        """Add labels to an email."""
        label_ids = [self.get_or_create_label(name) for name in label_names]
        self.service.users().messages().modify(
            userId="me", id=email_id, body={"addLabelIds": label_ids}
        ).execute()

    def add_labels_bulk(self, email_ids: list[str], label_names: list[str]) -> None:
        """Add labels to multiple emails using Gmail batchModify."""
        if not email_ids:
            return
        label_ids = [self.get_or_create_label(name) for name in label_names]
        body = {"ids": email_ids, "addLabelIds": label_ids}
        self.service.users().messages().batchModify(userId="me", body=body).execute()

    def remove_labels(self, email_id: str, label_names: list[str]) -> None:
        """Remove labels from an email."""
        label_ids = [lid for name in label_names if (lid := self.get_label_id(name))]
        if label_ids:
            self.service.users().messages().modify(
                userId="me", id=email_id, body={"removeLabelIds": label_ids}
            ).execute()

    def classify_email(self, email_id: str, label_name: str) -> None:
        """Add a classification label to an email (e.g., 'classifications/bulk_content')."""
        self.add_labels(email_id, [label_name])


class _EmailIterator:
    """
    Internal iterator for fetching emails with optional pointer logic.
    
    Yields Email objects in reverse chronological order.
    If use_seen_cache=True, stops when encountering an already-seen email.
    If use_seen_cache=False, iterates through all emails.
    """

    def __init__(
        self,
        service,
        seen_cache: Cache,
        label_ids: list[str],
        query: Optional[str],
        use_seen_cache: bool = True,
        message_format: str = "full",
        metadata_headers: Optional[list[str]] = None,
    ):
        self._service = service
        self._seen_cache = seen_cache
        self._label_ids = label_ids
        self._query = query
        self._use_seen_cache = use_seen_cache
        self._message_format = message_format
        self._metadata_headers = metadata_headers
        
        self._page: list[dict] = []
        self._index: int = 0
        self._next_token: Optional[str] = None
        self._started: bool = False
        self._done: bool = False

    def __iter__(self) -> Iterator[Email]:
        return self

    def __next__(self) -> Email:
        if self._done:
            raise StopIteration
        
        # Fetch pages until we have an email to return
        while self._index >= len(self._page):
            if self._started and self._next_token is None:
                self._done = True
                raise StopIteration
            self._fetch_page()
            if not self._page:
                self._done = True
                raise StopIteration
        
        msg_id = self._page[self._index]["id"]
        self._index += 1
        
        # Pointer logic: stop at first seen email (only if using seen cache)
        if self._use_seen_cache and msg_id in self._seen_cache:
            self._done = True
            raise StopIteration
        
        email = self._fetch_email(msg_id)
        
        # Only update seen cache if using it
        if self._use_seen_cache:
            self._seen_cache.set(msg_id, True)
        
        return email

    def _fetch_page(self) -> None:
        """Fetch next page of message IDs."""
        params = {
            "userId": "me",
            "labelIds": self._label_ids,
            "maxResults": MAX_RESULTS_PER_PAGE,
        }
        if self._query:
            params["q"] = self._query
        if self._next_token:
            params["pageToken"] = self._next_token
        
        response = self._service.users().messages().list(**params).execute()
        self._page = response.get("messages", [])
        self._next_token = response.get("nextPageToken")
        self._index = 0
        self._started = True

    def _fetch_email(self, msg_id: str) -> Email:
        """Fetch and parse a single email."""
        params = {"userId": "me", "id": msg_id, "format": self._message_format}
        if self._message_format == "metadata" and self._metadata_headers:
            params["metadataHeaders"] = self._metadata_headers
        msg = self._service.users().messages().get(**params).execute()
        return self.parse_message(msg)

    @staticmethod
    def parse_message(msg: dict) -> Email:
        """Parse Gmail API message into Email model."""
        payload = msg.get("payload", {})
        headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
        
        # Parse date
        date = None
        if "date" in headers:
            try:
                date = parsedate_to_datetime(headers["date"])
            except (ValueError, TypeError):
                pass
        
        # Parse body
        body_plain, body_html = _EmailIterator._extract_body(payload)
        
        return Email(
            id=msg["id"],
            thread_id=msg["threadId"],
            subject=headers.get("subject", ""),
            sender=headers.get("from", ""),
            recipients=_EmailIterator._split_addresses(headers.get("to", "")),
            cc=_EmailIterator._split_addresses(headers.get("cc", "")),
            date=date,
            snippet=msg.get("snippet", ""),
            body_plain=body_plain,
            body_html=body_html,
            labels=msg.get("labelIds", []),
        )

    @staticmethod
    def _split_addresses(value: str) -> list[str]:
        """Split comma-separated email addresses."""
        return [addr.strip() for addr in value.split(",")] if value else []

    @staticmethod
    def _extract_body(payload: dict) -> tuple[str, str]:
        """Extract plain and HTML body from message payload."""
        if "parts" in payload:
            return _EmailIterator._extract_body_from_parts(payload["parts"])
        return _EmailIterator._extract_single_body(payload)

    @staticmethod
    def _decode_body_data(data: str) -> str:
        with suppress(Exception):
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        return ""

    @staticmethod
    def _extract_single_body(payload: dict) -> tuple[str, str]:
        decoded = _EmailIterator._decode_body_data(payload.get("body", {}).get("data", ""))
        mime = payload.get("mimeType", "")
        plain = decoded if mime == "text/plain" else ""
        html = decoded if mime == "text/html" else ""
        return plain, html

    @staticmethod
    def _extract_body_from_parts(parts: list[dict]) -> tuple[str, str]:
        plain, html = "", ""
        queue = list(parts)
        while queue and (not plain or not html):
            part = queue.pop(0)
            mime = part.get("mimeType", "")
            data = part.get("body", {}).get("data", "")
            plain = plain or (_EmailIterator._decode_body_data(data) if mime == "text/plain" else "")
            html = html or (_EmailIterator._decode_body_data(data) if mime == "text/html" else "")
            queue.extend(part.get("parts", []))
        return plain, html


# -----------------------------------------------------------------------------
# Convenience Function
# -----------------------------------------------------------------------------

def fetch_new_emails(
    credentials_path: str = DEFAULT_CREDENTIALS_PATH,
    token_path: str = DEFAULT_TOKEN_PATH,
    cache_dir: str = DEFAULT_CACHE_DIR,
    label_ids: Optional[list[str]] = None,
    query: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[Email]:
    """Fetch new emails as a list (convenience wrapper)."""
    with GmailConnector(credentials_path, token_path, cache_dir, label_ids, query) as gmail:
        return list(islice(gmail, limit)) if limit else list(gmail)


def _print_demo_email(index: int, email: Email) -> None:
    logger.info(f"[{index}] {email.sender[:40]}")
    logger.info(f"    Subject: {email.subject[:60]}")
    logger.info(f"    Date: {email.date}")


def _run_demo() -> None:
    logger.info("Fetching new emails from Gmail...")
    with GmailConnector() as gmail:
        for i, email in enumerate(islice(gmail, 5), start=1):
            _print_demo_email(i, email)
        logger.info("... (stopping after 5 emails)")
        logger.info(f"Seen cache size: {gmail.get_seen_count()}")


# -----------------------------------------------------------------------------
# CLI Demo
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    _run_demo()
