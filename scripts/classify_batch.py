"""Classify emails in batch. Usage: python scripts/classify_batch.py [full|stream] [limit] [concurrency]"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.pipeline import run_full, run_stream


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "full"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    concurrency = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    if mode == "stream":
        results = await run_stream(limit=limit, max_concurrent=concurrency)
    else:
        results = await run_full(limit=limit, max_concurrent=concurrency)

    ok = sum(1 for r in results if r["status"] == "ok")
    err = sum(1 for r in results if r["status"] == "error")

    for r in results:
        status = r["status"]
        subject = r["subject"][:50]
        if status == "ok":
            output = r.get("output", "")[:100]
            print(f"  [OK]  {subject:50s} | {output}")
        else:
            print(f"  [ERR] {subject:50s} | {r.get('error', '')[:100]}")

    print(f"\nDone: {ok} ok, {err} failed")


if __name__ == "__main__":
    asyncio.run(main())
