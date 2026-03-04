"""Email triage pipeline: fetch untriaged emails from Gmail, classify, and act."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from agents import Runner
from loguru import logger

from src.agents.agent import build_triage_agent, render_email_input
from src.agents.context import PipelineContext, fetch_calendar_context, fetch_todoist_context
from src.connectors.calendar import Calendar
from src.connectors.gmail import Gmail
from src.connectors.todoist import Todoist
from src.labels import LabelResolver, TRIAGE_TO_GMAIL
from src.models import Email

STATE_FILE = Path("mailalfred_state.json")


def _load_high_water_mark() -> str | None:
    """Load the last processed date from state file."""
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text())
        return data.get("high_water_mark")
    return None


def _save_high_water_mark(date_str: str) -> None:
    """Save the high water mark to state file."""
    STATE_FILE.write_text(json.dumps({"high_water_mark": date_str}))


def _build_untriaged_query(label_resolver: LabelResolver) -> str:
    """Build a Gmail search query for emails without any triage label."""
    # Exclude emails that already have any of our triage labels
    excludes = []
    for gmail_name in TRIAGE_TO_GMAIL.values():
        label_id = label_resolver._name_to_id.get(gmail_name)
        if label_id:
            excludes.append(f"-label:{gmail_name.replace('/', '-')}")
    return " ".join(excludes)


async def run_pipeline(limit: int = 50, max_concurrent: int = 1) -> list[dict]:
    """Run the full email triage pipeline.

    1. Fetch untriaged emails directly from Gmail.
    2. Pre-fetch Todoist and Calendar context.
    3. Build the triage agent.
    4. Process emails sequentially or with limited concurrency.

    Returns:
        List of result dicts with email_id, subject, and outcome.
    """
    # --- Init connectors ---
    gmail = Gmail()
    todoist = Todoist()
    calendar = Calendar()

    # --- Resolve label IDs ---
    logger.info("Resolving Gmail label IDs...")
    label_resolver = LabelResolver()
    await label_resolver.initialize(gmail)

    # --- Fetch untriaged emails from Gmail ---
    query = _build_untriaged_query(label_resolver)
    hwm = _load_high_water_mark()
    if hwm:
        query = f"{query} after:{hwm}"
    query = f"{query} in:inbox"

    logger.info(f"Fetching untriaged emails (query: {query})...")
    emails = await gmail.fetch_all_emails(query=query, max_emails=limit)
    logger.info(f"Found {len(emails)} untriaged emails.")

    if not emails:
        logger.info("No untriaged emails to process.")
        return []

    # --- Pre-fetch context (parallel) ---
    logger.info("Pre-fetching Todoist and Calendar context...")
    todoist_result, calendar_ctx = await asyncio.gather(
        fetch_todoist_context(todoist),
        fetch_calendar_context(calendar),
    )
    todoist_ctx, todoist_project_ids = todoist_result

    # --- Build agent ---
    agent = build_triage_agent(todoist_context=todoist_ctx, calendar_context=calendar_ctx)

    # --- Process emails ---
    semaphore = asyncio.Semaphore(max_concurrent)
    results: list[dict] = []

    async def process_one(email: Email) -> dict:
        async with semaphore:
            logger.info(f"Triaging: {email.subject[:60]}...")
            try:
                # Fetch thread for context
                thread = await gmail.get_thread(email.thread_id)

                context = PipelineContext(
                    gmail=gmail,
                    label_resolver=label_resolver,
                    current_email=email,
                    calendar=calendar,
                    todoist=todoist,
                    todoist_project_ids=todoist_project_ids,
                )

                result = await Runner.run(
                    agent,
                    input=render_email_input(email, thread),
                    context=context,
                )

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

    results = list(await asyncio.gather(*(process_one(e) for e in emails)))

    # --- Update high water mark ---
    dates = [e.date for e in emails if e.date]
    if dates:
        newest = max(dates)
        _save_high_water_mark(newest.strftime("%Y/%m/%d"))

    ok = sum(1 for r in results if r["status"] == "ok")
    err = sum(1 for r in results if r["status"] == "error")
    logger.info(f"Pipeline complete: {ok} succeeded, {err} failed.")

    return results
