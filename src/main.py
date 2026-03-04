import asyncio

from dotenv import load_dotenv

load_dotenv()

from loguru import logger

from src.pipeline import run_pipeline


async def main() -> None:
    logger.info("Starting mailAlfred pipeline...")
    results = await run_pipeline(limit=50, max_concurrent=3)

    for r in results:
        status = r["status"]
        subject = r["subject"][:60]
        if status == "ok":
            logger.info(f"  [OK] {subject} -> {r['final_agent']}")
        else:
            logger.error(f"  [FAIL] {subject} -> {r['error']}")


if __name__ == "__main__":
    asyncio.run(main())
