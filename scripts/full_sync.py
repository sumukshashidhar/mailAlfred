"""Full sync: fetch all Gmail emails into the local DuckDB cache."""

import asyncio
import sys
from pathlib import Path

# Add project root to path so `src` is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

from src.cache.email_cache import EmailCache
from src.connectors.gmail import Gmail
from src.sync import sync


async def main() -> None:
    max_emails = int(sys.argv[1]) if len(sys.argv) > 1 else 0
    label = f" (limit: {max_emails})" if max_emails else " (all)"

    print(f"Starting full sync{label}...")
    gmail = Gmail()
    cache = EmailCache()

    count = await sync(gmail, cache, max_emails=max_emails)
    print(f"Synced {count} emails. Total cached: {cache.count()}")
    cache.close()


if __name__ == "__main__":
    asyncio.run(main())
