"""Email triage pipeline: sync, classify, label, and act."""

from __future__ import annotations

import asyncio

from agents import Runner
from loguru import logger

from src.agents.agent import build_triage_agent, render_email_input
from src.agents.context import PipelineContext, fetch_calendar_context, fetch_todoist_context
from src.cache.email_cache import EmailCache
from src.connectors.calendar import Calendar
from src.connectors.gmail import Gmail
from src.connectors.todoist import Todoist
from src.labels import LabelResolver
from src.models import Email
from src.sync import sync


async def run_pipeline(limit: int = 5, max_concurrent: int = 3) -> list[dict]:
    """Run the full email triage pipeline.

    1. Sync Gmail to local cache.
    2. Pre-fetch Todoist and Calendar context.
    3. Build the triage agent (single agent, all tools).
    4. Process unorganized emails concurrently.
    5. Mark processed emails as organized.

    Returns:
        List of result dicts with email_id, subject, and outcome.
    """
    # --- Init connectors ---
    gmail = Gmail()
    cache = EmailCache()
    todoist = Todoist()
    calendar = Calendar()

    # --- Sync emails ---
    logger.info("Syncing emails from Gmail...")
    new_count = await sync(gmail, cache, max_emails=limit)
    logger.info(f"Synced {new_count} new emails. Total cached: {cache.count()}")

    # --- Resolve label IDs ---
    logger.info("Resolving Gmail label IDs...")
    label_resolver = LabelResolver()
    await label_resolver.initialize(gmail)

    # --- Pre-fetch context (parallel) ---
    logger.info("Pre-fetching Todoist and Calendar context...")
    todoist_ctx, calendar_ctx = await asyncio.gather(
        fetch_todoist_context(todoist),
        fetch_calendar_context(calendar),
    )

    # --- Build agent ---
    agent = build_triage_agent(todoist_context=todoist_ctx, calendar_context=calendar_ctx)

    # --- Process unorganized emails ---
    unorganized = cache.get_unorganized(limit=limit)
    logger.info(f"Processing {len(unorganized)} unorganized emails...")

    if not unorganized:
        logger.info("No unorganized emails to process.")
        return []

    semaphore = asyncio.Semaphore(max_concurrent)

    async def process_one(email: Email) -> dict:
        async with semaphore:
            logger.info(f"Triaging: {email.subject[:60]}...")
            try:
                context = PipelineContext(
                    gmail=gmail,
                    cache=cache,
                    label_resolver=label_resolver,
                    current_email=email,
                    calendar=calendar,
                    todoist=todoist,
                )

                result = await Runner.run(
                    agent,
                    input=render_email_input(email),
                    context=context,
                )

                cache.mark_organized([email.id])
                logger.info(f"Done: {email.subject[:60]}")
                return {
                    "email_id": email.id,
                    "subject": email.subject,
                    "status": "ok",
                    "output": str(result.final_output)[:200],
                }
            except Exception as e:
                logger.error(f"Failed: {email.subject[:60]} -> {e}")
                return {
                    "email_id": email.id,
                    "subject": email.subject,
                    "status": "error",
                    "error": str(e),
                }

    results = await asyncio.gather(*(process_one(e) for e in unorganized))
    results = list(results)

    ok = sum(1 for r in results if r["status"] == "ok")
    err = sum(1 for r in results if r["status"] == "error")
    logger.info(f"Pipeline complete: {ok} succeeded, {err} failed.")

    cache.close()
    return results
