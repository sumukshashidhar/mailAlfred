"""Classify unorganized emails in batch."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from src.agents.agent import build_triage_agent, render_email_input
from src.agents.context import PipelineContext, fetch_calendar_context, fetch_todoist_context
from src.cache.email_cache import EmailCache
from src.connectors.calendar import Calendar
from src.connectors.gmail import Gmail
from src.connectors.todoist import Todoist
from src.labels import LabelResolver
from agents import Runner


async def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    concurrency = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    gmail = Gmail()
    cache = EmailCache()
    todoist = Todoist()
    calendar = Calendar()

    label_resolver = LabelResolver()
    await label_resolver.initialize(gmail)

    todoist_result, calendar_ctx = await asyncio.gather(
        fetch_todoist_context(todoist),
        fetch_calendar_context(calendar),
    )
    todoist_ctx, todoist_project_ids = todoist_result
    agent = build_triage_agent(todoist_context=todoist_ctx, calendar_context=calendar_ctx)

    emails = cache.get_unorganized(limit=limit)
    print(f"Processing {len(emails)} emails (concurrency={concurrency})...", flush=True)

    semaphore = asyncio.Semaphore(concurrency)
    ok = 0
    err = 0

    async def process(i, email):
        nonlocal ok, err
        async with semaphore:
            try:
                context = PipelineContext(
                    gmail=gmail, cache=cache, label_resolver=label_resolver,
                    current_email=email, calendar=calendar, todoist=todoist,
                    todoist_project_ids=todoist_project_ids,
                )
                result = await Runner.run(agent, input=render_email_input(email, cache), context=context)
                cache.mark_organized([email.id])
                short = str(result.final_output)[:120]
                print(f"  [{i+1}/{len(emails)}] OK  {email.subject[:50]:50s} | {short}", flush=True)
                ok += 1
            except Exception as e:
                print(f"  [{i+1}/{len(emails)}] ERR {email.subject[:50]:50s} | {e}", flush=True)
                err += 1

    await asyncio.gather(*(process(i, e) for i, e in enumerate(emails)))
    print(f"\nDone: {ok} ok, {err} failed", flush=True)
    cache.close()


if __name__ == "__main__":
    asyncio.run(main())
