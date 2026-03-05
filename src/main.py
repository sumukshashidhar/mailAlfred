import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from loguru import logger

from src.pipeline import run_full, run_stream


async def main() -> None:
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"

    if mode == "stream":
        logger.info("Starting mailAlfred in stream mode...")
        results = await run_stream()
    else:
        logger.info("Starting mailAlfred in full mode...")
        results = await run_full()

    for r in results:
        status = r["status"]
        subject = r["subject"][:60]
        if status == "ok":
            logger.info(f"  [OK] {subject}")
        else:
            logger.error(f"  [FAIL] {subject} -> {r['error']}")


if __name__ == "__main__":
    asyncio.run(main())
