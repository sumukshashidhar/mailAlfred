"""Gmail-to-cache synchronisation."""

from src.cache.email_cache import EmailCache
from src.connectors.gmail import Gmail


async def sync(gmail: Gmail, cache: EmailCache) -> int:
    """Sync Gmail to local cache. Returns count of new emails."""
    last_sync = cache.get_last_sync_date()
    emails = await gmail.fetch_all_emails(after_date=last_sync)
    cache.upsert_emails(emails)
    cache.update_sync_state()
    return len(emails)
