"""Google Calendar API connector."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class Calendar:
    """Async-friendly Google Calendar connector.

    Reuses the shared token.json (written by Gmail connector with all scopes).
    """

    def __init__(
        self,
        token_path: str = "token.json",
    ) -> None:
        self._token_path = token_path
        self._service = None

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _get_service(self):
        """Load credentials from shared token and build Calendar service."""
        if self._service is not None:
            return self._service

        if not os.path.exists(self._token_path):
            raise FileNotFoundError(
                f"{self._token_path} not found. Run the Gmail connector first "
                "to authenticate with all scopes."
            )

        creds = Credentials.from_authorized_user_file(self._token_path)

        if creds.expired and creds.refresh_token:
            creds.refresh(Request())

        self._service = build("calendar", "v3", credentials=creds)
        return self._service

    # ------------------------------------------------------------------
    # Sync helpers
    # ------------------------------------------------------------------

    def _list_events_sync(
        self,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
        max_results: int = 250,
        calendar_id: str = "primary",
    ) -> list[dict]:
        """List events in a time range."""
        service = self._get_service()

        now = datetime.now(timezone.utc)
        if time_min is None:
            time_min = now - timedelta(weeks=2)
        if time_max is None:
            time_max = now + timedelta(weeks=1)

        events: list[dict] = []
        page_token = None

        while True:
            kwargs: dict = {
                "calendarId": calendar_id,
                "timeMin": time_min.isoformat(),
                "timeMax": time_max.isoformat(),
                "maxResults": max_results,
                "singleEvents": True,
                "orderBy": "startTime",
            }
            if page_token:
                kwargs["pageToken"] = page_token

            response = service.events().list(**kwargs).execute()
            events.extend(response.get("items", []))

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return events

    def _get_event_sync(self, event_id: str, calendar_id: str = "primary") -> dict:
        """Get a single event by ID."""
        service = self._get_service()
        return service.events().get(
            calendarId=calendar_id, eventId=event_id
        ).execute()

    def _update_event_sync(
        self,
        event_id: str,
        body: dict,
        calendar_id: str = "primary",
    ) -> dict:
        """Patch an event with the given fields."""
        service = self._get_service()
        return service.events().patch(
            calendarId=calendar_id, eventId=event_id, body=body
        ).execute()

    def _create_event_sync(
        self,
        summary: str,
        start: str,
        end: str,
        description: str = "",
        calendar_id: str = "primary",
    ) -> dict:
        """Create a new calendar event."""
        service = self._get_service()
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        return service.events().insert(
            calendarId=calendar_id, body=body
        ).execute()

    # ------------------------------------------------------------------
    # Public async API
    # ------------------------------------------------------------------

    async def list_events(
        self,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
        max_results: int = 250,
    ) -> list[dict]:
        """List events in a time range, asynchronously."""
        return await asyncio.to_thread(
            self._list_events_sync, time_min, time_max, max_results
        )

    async def get_event(self, event_id: str) -> dict:
        """Get a single event by ID, asynchronously."""
        return await asyncio.to_thread(self._get_event_sync, event_id)

    async def update_event(self, event_id: str, body: dict) -> dict:
        """Patch an event, asynchronously."""
        return await asyncio.to_thread(self._update_event_sync, event_id, body)

    async def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        description: str = "",
    ) -> dict:
        """Create a new calendar event, asynchronously."""
        return await asyncio.to_thread(
            self._create_event_sync, summary, start, end, description
        )
