"""Gmail-to-cache synchronisation."""

from src.cache.email_cache import EmailCache
from src.connectors.gmail import Gmail


async def sync(gmail: Gmail, cache: EmailCache, max_emails: int = 0) -> int:
    """Sync Gmail to local cache. Returns count of new emails.

    Args:
        max_emails: Limit how many emails to fetch. 0 means no limit.
    """
    last_sync = cache.get_last_sync_date()
    emails = await gmail.fetch_all_emails(after_date=last_sync, max_emails=max_emails)
    cache.upsert_emails(emails)
    cache.update_sync_state()
    return len(emails)
