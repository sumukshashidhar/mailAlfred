"""Tests for the sync() function."""

import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.sync import sync
from src.models import Email


def _make_email(id="m1", thread_id="t1", **kwargs):
    return Email(id=id, thread_id=thread_id, **kwargs)


class TestSync:
    @pytest.mark.asyncio
    async def test_first_sync_fetches_all(self):
        """First sync (no high-water mark) fetches all emails."""
        cache = MagicMock()
        cache.get_last_sync_date.return_value = None

        gmail = MagicMock()
        gmail.fetch_all_emails = AsyncMock(
            return_value=[_make_email(id="m1"), _make_email(id="m2")]
        )

        count = await sync(gmail, cache)

        gmail.fetch_all_emails.assert_called_once_with(after_date=None)
        cache.upsert_emails.assert_called_once()
        cache.update_sync_state.assert_called_once()
        assert count == 2

    @pytest.mark.asyncio
    async def test_delta_sync_uses_high_water_mark(self):
        """Subsequent sync uses last_sync_date as after_date."""
        last = datetime(2026, 3, 1, tzinfo=timezone.utc)
        cache = MagicMock()
        cache.get_last_sync_date.return_value = last

        gmail = MagicMock()
        gmail.fetch_all_emails = AsyncMock(return_value=[_make_email(id="m3")])

        count = await sync(gmail, cache)

        gmail.fetch_all_emails.assert_called_once_with(after_date=last)
        assert count == 1

    @pytest.mark.asyncio
    async def test_sync_no_new_emails(self):
        """Sync with no new emails returns 0."""
        cache = MagicMock()
        cache.get_last_sync_date.return_value = datetime(
            2026, 3, 4, tzinfo=timezone.utc
        )

        gmail = MagicMock()
        gmail.fetch_all_emails = AsyncMock(return_value=[])

        count = await sync(gmail, cache)

        assert count == 0
        cache.upsert_emails.assert_called_once_with([])
        cache.update_sync_state.assert_called_once()
