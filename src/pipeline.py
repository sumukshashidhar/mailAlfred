"""Email triage pipeline: producer-consumer pattern for continuous fetch + classify."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
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
SENTINEL = None  # signals producer is done


# ------------------------------------------------------------------
# High water mark persistence (stream mode only)
# ------------------------------------------------------------------

def _load_high_water_mark() -> str | None:
    if STATE_FILE.exists():
        data = json.loads(STATE_FILE.read_text())
        return data.get("high_water_mark")
    return None


def _save_high_water_mark(date_str: str) -> None:
    STATE_FILE.write_text(json.dumps({"high_water_mark": date_str}))


# ------------------------------------------------------------------
# Shared setup
# ------------------------------------------------------------------

async def _setup() -> tuple[Gmail, Gmail, Todoist, Calendar, LabelResolver, str, dict[str, str], str]:
    """Returns (gmail_fetch, gmail_tools, todoist, calendar, label_resolver, ...).

    Two separate Gmail instances because httplib2 is not thread-safe.
    gmail_fetch is used by the producer, gmail_tools by the consumer/agent tools.
    """
    gmail_fetch = Gmail()
    gmail_tools = Gmail()
    todoist = Todoist()
    calendar = Calendar()

    label_resolver = LabelResolver()
    await label_resolver.initialize(gmail_fetch)

    logger.info("Pre-fetching Todoist and Calendar context...")
    todoist_result, calendar_ctx = await asyncio.gather(
        fetch_todoist_context(todoist),
        fetch_calendar_context(calendar),
    )
    todoist_ctx, todoist_project_ids = todoist_result

    return gmail_fetch, gmail_tools, todoist, calendar, label_resolver, todoist_ctx, todoist_project_ids, calendar_ctx


def _build_untriaged_query(label_resolver: LabelResolver) -> str:
    """Gmail query that excludes emails already carrying any c/ label."""
    excludes = []
    for gmail_name in TRIAGE_TO_GMAIL.values():
        label_id = label_resolver._name_to_id.get(gmail_name)
        if label_id:
            excludes.append(f"-label:{gmail_name.replace('/', '-')}")
    return " ".join(excludes)


# ------------------------------------------------------------------
# Producer: fetches emails page-by-page, pushes onto queue
# ------------------------------------------------------------------

async def _producer(
    gmail: Gmail,
    query: str,
    queue: asyncio.Queue,
    max_emails: int = 0,
) -> None:
    """Fetch emails from Gmail in batched pages and feed them into the queue."""
    try:
        page_token = None
        count = 0
        batch_size = 100

        while True:
            if max_emails > 0:
                remaining = max_emails - count
                if remaining <= 0:
                    break
                page_size = min(batch_size, remaining)
            else:
                page_size = batch_size

            stubs, next_token = await gmail.list_message_ids(
                query=query, max_results=page_size, page_token=page_token,
            )

            if not stubs:
                break

            # Batch fetch all messages in one HTTP request
            emails = await gmail.batch_get_emails(stubs)

            for email in emails:
                await queue.put(email)
                count += 1
                if max_emails > 0 and count >= max_emails:
                    break

            logger.info(f"[producer] Queued {count} emails so far...")

            page_token = next_token
            if not page_token:
                break

    finally:
        await queue.put(SENTINEL)
        logger.info(f"[producer] Done. Total queued: {count}")


# ------------------------------------------------------------------
# Consumer: pulls emails from queue, classifies them
# ------------------------------------------------------------------

async def _consumer(
    queue: asyncio.Queue,
    gmail: Gmail,
    todoist: Todoist,
    calendar: Calendar,
    label_resolver: LabelResolver,
    todoist_ctx: str,
    todoist_project_ids: dict[str, str],
    calendar_ctx: str,
    results: list[dict],
    semaphore: asyncio.Semaphore,
) -> None:
    """Pull emails from queue and classify until sentinel is received."""
    agent = build_triage_agent(todoist_context=todoist_ctx, calendar_context=calendar_ctx)

    async def classify(email: Email) -> dict:
        async with semaphore:
            logger.info(f"[classify] {email.subject[:60]}...")
            try:
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
                logger.info(f"[done] {email.subject[:60]}")
                return {
                    "email_id": email.id,
                    "subject": email.subject,
                    "status": "ok",
                    "output": str(result.final_output)[:200],
                }
            except Exception as e:
                logger.error(f"[fail] {email.subject[:60]} -> {e}")
                return {
                    "email_id": email.id,
                    "subject": email.subject,
                    "status": "error",
                    "error": str(e),
                }

    tasks: list[asyncio.Task] = []

    while True:
        email = await queue.get()
        if email is SENTINEL:
            break
        task = asyncio.create_task(classify(email))
        tasks.append(task)

    # Wait for all in-flight classifications to finish
    if tasks:
        done = await asyncio.gather(*tasks)
        results.extend(done)


# ------------------------------------------------------------------
# Mode 1: Full process
# ------------------------------------------------------------------

async def run_full(limit: int = 0, max_concurrent: int = 64) -> list[dict]:
    """Process ALL inbox emails that lack a c/ classification label.

    Fetches and classifies concurrently (producer-consumer).
    """
    gmail_fetch, gmail_tools, todoist, calendar, label_resolver, todoist_ctx, project_ids, calendar_ctx = await _setup()

    query = f"{_build_untriaged_query(label_resolver)} in:inbox"
    logger.info(f"[full] Starting (query: {query})...")

    queue: asyncio.Queue = asyncio.Queue(maxsize=max_concurrent * 2)
    semaphore = asyncio.Semaphore(max_concurrent)
    results: list[dict] = []

    await asyncio.gather(
        _producer(gmail_fetch, query, queue, max_emails=limit),
        _consumer(queue, gmail_tools, todoist, calendar, label_resolver,
                  todoist_ctx, project_ids, calendar_ctx, results, semaphore),
    )

    ok = sum(1 for r in results if r["status"] == "ok")
    err = sum(1 for r in results if r["status"] == "error")
    logger.info(f"[full] Complete: {ok} succeeded, {err} failed.")
    return results


# ------------------------------------------------------------------
# Mode 2: Stream (high water mark)
# ------------------------------------------------------------------

async def run_stream(limit: int = 50, max_concurrent: int = 64) -> list[dict]:
    """Process only emails newer than the last high water mark.

    Falls back to full mode on first run (no saved mark).
    """
    hwm = _load_high_water_mark()
    if not hwm:
        logger.info("[stream] No high water mark found, falling back to full mode.")
        return await run_full(limit=limit, max_concurrent=max_concurrent)

    gmail_fetch, gmail_tools, todoist, calendar, label_resolver, todoist_ctx, project_ids, calendar_ctx = await _setup()

    query = f"in:inbox after:{hwm}"
    logger.info(f"[stream] Starting (query: {query})...")

    queue: asyncio.Queue = asyncio.Queue(maxsize=max_concurrent * 2)
    semaphore = asyncio.Semaphore(max_concurrent)
    results: list[dict] = []

    await asyncio.gather(
        _producer(gmail_fetch, query, queue, max_emails=limit),
        _consumer(queue, gmail_tools, todoist, calendar, label_resolver,
                  todoist_ctx, project_ids, calendar_ctx, results, semaphore),
    )

    # Advance high water mark
    ok_ids = [r for r in results if r["status"] == "ok"]
    if ok_ids:
        _save_high_water_mark(datetime.now().strftime("%Y/%m/%d"))
        logger.info(f"[stream] High water mark updated to today.")

    ok = sum(1 for r in results if r["status"] == "ok")
    err = sum(1 for r in results if r["status"] == "error")
    logger.info(f"[stream] Complete: {ok} succeeded, {err} failed.")
    return results
