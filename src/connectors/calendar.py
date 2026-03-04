"""Google Calendar API connector."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


WRITE_CALENDAR_NAME = "Assistant"


class Calendar:
    """Async-friendly Google Calendar connector.

    Reads from all calendars; writes only to the "Assistant" calendar.
    Never invites attendees.
    """

    def __init__(
        self,
        token_path: str = "token.json",
    ) -> None:
        self._token_path = token_path
        self._service = None
        self._calendar_ids: list[str] | None = None
        self._calendar_name_to_id: dict[str, str] | None = None
        self._write_calendar_id: str | None = None

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

    def _get_all_calendar_ids(self) -> list[str]:
        """Fetch all calendar IDs the user has access to.

        Also builds the name-to-ID mapping and resolves the write calendar.
        """
        if self._calendar_ids is not None:
            return self._calendar_ids

        service = self._get_service()
        calendars: list[str] = []
        name_to_id: dict[str, str] = {}
        page_token = None

        while True:
            response = service.calendarList().list(pageToken=page_token).execute()
            for entry in response.get("items", []):
                calendars.append(entry["id"])
                name_to_id[entry.get("summary", "")] = entry["id"]
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        self._calendar_ids = calendars
        self._calendar_name_to_id = name_to_id
        self._write_calendar_id = name_to_id.get(WRITE_CALENDAR_NAME)
        if not self._write_calendar_id:
            raise ValueError(
                f"Calendar '{WRITE_CALENDAR_NAME}' not found. "
                f"Available: {list(name_to_id.keys())}"
            )
        return calendars

    @property
    def write_calendar_id(self) -> str:
        """The resolved ID of the write-only calendar."""
        if self._write_calendar_id is None:
            self._get_all_calendar_ids()
        return self._write_calendar_id  # type: ignore[return-value]

    def _list_events_sync(
        self,
        time_min: datetime | None = None,
        time_max: datetime | None = None,
        max_results: int = 250,
    ) -> list[dict]:
        """List events across all calendars in a time range."""
        service = self._get_service()

        now = datetime.now(timezone.utc)
        if time_min is None:
            time_min = now - timedelta(weeks=2)
        if time_max is None:
            time_max = now + timedelta(weeks=1)

        all_events: list[dict] = []

        for cal_id in self._get_all_calendar_ids():
            page_token = None
            while True:
                kwargs: dict = {
                    "calendarId": cal_id,
                    "timeMin": time_min.isoformat(),
                    "timeMax": time_max.isoformat(),
                    "maxResults": max_results,
                    "singleEvents": True,
                    "orderBy": "startTime",
                }
                if page_token:
                    kwargs["pageToken"] = page_token

                response = service.events().list(**kwargs).execute()
                for item in response.get("items", []):
                    item["_calendarId"] = cal_id
                    all_events.append(item)

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

        # Sort all events by start time across calendars
        def _sort_key(ev: dict) -> str:
            s = ev.get("start", {})
            return s.get("dateTime", s.get("date", ""))

        all_events.sort(key=_sort_key)
        return all_events

    def _get_event_sync(self, event_id: str, calendar_id: str | None = None) -> dict:
        """Get a single event by ID."""
        service = self._get_service()
        return service.events().get(
            calendarId=calendar_id or self.write_calendar_id, eventId=event_id
        ).execute()

    def _update_event_sync(
        self,
        event_id: str,
        body: dict,
        calendar_id: str | None = None,
    ) -> dict:
        """Patch an event with the given fields.

        Always strips attendees to prevent sending invitations.
        """
        service = self._get_service()
        body.pop("attendees", None)
        return service.events().patch(
            calendarId=calendar_id or self.write_calendar_id,
            eventId=event_id,
            body=body,
            sendUpdates="none",
        ).execute()

    def _create_event_sync(
        self,
        summary: str,
        start: str,
        end: str,
        description: str = "",
    ) -> dict:
        """Create a new event in the Assistant calendar.

        Never includes attendees.
        """
        service = self._get_service()
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start},
            "end": {"dateTime": end},
        }
        return service.events().insert(
            calendarId=self.write_calendar_id,
            body=body,
            sendUpdates="none",
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
        """List events across all calendars, asynchronously."""
        return await asyncio.to_thread(
            self._list_events_sync, time_min, time_max, max_results
        )

    async def get_event(self, event_id: str, calendar_id: str | None = None) -> dict:
        """Get a single event by ID, asynchronously."""
        return await asyncio.to_thread(self._get_event_sync, event_id, calendar_id)

    async def update_event(
        self, event_id: str, body: dict, calendar_id: str | None = None
    ) -> dict:
        """Patch an event (always in Assistant calendar), asynchronously."""
        return await asyncio.to_thread(
            self._update_event_sync, event_id, body, calendar_id
        )

    async def create_event(
        self,
        summary: str,
        start: str,
        end: str,
        description: str = "",
    ) -> dict:
        """Create a new event in the Assistant calendar, asynchronously."""
        return await asyncio.to_thread(
            self._create_event_sync, summary, start, end, description
        )
