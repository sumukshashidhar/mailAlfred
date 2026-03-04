"""Unified triage agent: classifies emails, creates tasks, manages calendar."""

from __future__ import annotations

from datetime import datetime

from agents import Agent, ModelSettings, RunContextWrapper, function_tool
from jinja2 import Environment, FileSystemLoader

from src.agents.context import PROMPTS_DIR, PipelineContext
from src.models import Email


# ------------------------------------------------------------------
# Classification tools
# ------------------------------------------------------------------


@function_tool
async def apply_label(
    ctx: RunContextWrapper[PipelineContext],
    label: str,
) -> str:
    """Apply a triage label to the current email in Gmail.

    Args:
        label: One of: respond, do, follow_up, reference, read, notification, marketing.
    """
    email = ctx.context.current_email
    resolver = ctx.context.label_resolver
    gmail = ctx.context.gmail

    label_id = resolver.resolve(label)
    await gmail.apply_labels(email.id, add_label_ids=[label_id])
    return f"Applied label '{label}' to email '{email.subject}'."


# ------------------------------------------------------------------
# Context lookup tools
# ------------------------------------------------------------------


@function_tool
async def search_emails(
    ctx: RunContextWrapper[PipelineContext],
    query: str,
) -> str:
    """Search past emails by keyword for additional context.

    Args:
        query: Search term to look for in subjects and bodies.
    """
    results = ctx.context.cache.search_emails(query, limit=10)
    if not results:
        return "No matching emails found."
    lines = []
    for e in results:
        lines.append(f"- [{e.date}] {e.sender}: {e.subject}")
    return "\n".join(lines)


@function_tool
async def get_email_thread(
    ctx: RunContextWrapper[PipelineContext],
    thread_id: str,
) -> str:
    """Get all emails in a conversation thread for context.

    Args:
        thread_id: The Gmail thread ID.
    """
    thread = ctx.context.cache.get_email_thread(thread_id)
    if not thread:
        return "No emails found in this thread."
    lines = []
    for e in thread:
        body_preview = (e.body_plain or "")[:300]
        lines.append(f"--- [{e.date}] {e.sender}: {e.subject}\n{body_preview}\n")
    return "\n".join(lines)


@function_tool
async def get_emails_from_sender(
    ctx: RunContextWrapper[PipelineContext],
    sender: str,
) -> str:
    """Get recent emails from a sender to understand patterns.

    Args:
        sender: Sender email address or name to search for.
    """
    results = ctx.context.cache.get_emails_from_sender(sender, limit=10)
    if not results:
        return "No emails found from this sender."
    lines = []
    for e in results:
        labels = ", ".join(e.labels) if e.labels else "none"
        lines.append(f"- [{e.date}] {e.subject} (labels: {labels})")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Todoist tools
# ------------------------------------------------------------------


@function_tool
async def create_task(
    ctx: RunContextWrapper[PipelineContext],
    content: str,
    description: str = "",
    project_id: str = "",
    priority: int = 1,
    due_string: str = "",
    labels: str = "",
) -> str:
    """Create a new Todoist task.

    Args:
        content: Task title (clear, actionable, imperative form).
        description: Longer description with context.
        project_id: Target project ID (omit for Inbox).
        priority: 1 (normal) to 4 (urgent).
        due_string: Natural language due date (e.g. 'tomorrow', 'Friday', 'March 10').
        labels: Comma-separated label names to apply.
    """
    label_list = [lb.strip() for lb in labels.split(",") if lb.strip()] if labels else None

    result = await ctx.context.todoist.create_task(
        content=content,
        description=description,
        project_id=project_id or None,
        priority=priority,
        due_string=due_string or None,
        labels=label_list,
    )
    return f"Created task '{result['content']}' (id: {result['id']})."


@function_tool
async def add_comment(
    ctx: RunContextWrapper[PipelineContext],
    task_id: str,
    content: str,
) -> str:
    """Add a comment to an existing Todoist task for reference.

    Args:
        task_id: The Todoist task ID.
        content: Comment text (email context, key quotes, etc.).
    """
    result = await ctx.context.todoist.add_comment(task_id=task_id, content=content)
    return f"Added comment to task (comment id: {result['id']})."


# ------------------------------------------------------------------
# Calendar tools
# ------------------------------------------------------------------


@function_tool
async def update_event(
    ctx: RunContextWrapper[PipelineContext],
    event_id: str,
    notes: str,
) -> str:
    """Append notes to an existing Google Calendar event.

    Args:
        event_id: The Google Calendar event ID.
        notes: Additional notes or details to append to the event description.
    """
    current = await ctx.context.calendar.get_event(event_id)
    existing_desc = current.get("description", "")
    new_desc = f"{existing_desc}\n\n---\n{notes}" if existing_desc else notes

    result = await ctx.context.calendar.update_event(
        event_id, {"description": new_desc}
    )
    return f"Updated event '{result.get('summary', event_id)}' with new notes."


@function_tool
async def create_event(
    ctx: RunContextWrapper[PipelineContext],
    summary: str,
    start: str,
    end: str,
    description: str = "",
) -> str:
    """Create a new Google Calendar event.

    Args:
        summary: Event title.
        start: Start time in ISO 8601 format (e.g. '2026-03-05T09:00:00-05:00').
        end: End time in ISO 8601 format.
        description: Event description or notes.
    """
    result = await ctx.context.calendar.create_event(
        summary=summary, start=start, end=end, description=description
    )
    return f"Created event '{result.get('summary')}' (id: {result.get('id')})."


@function_tool
async def list_events(
    ctx: RunContextWrapper[PipelineContext],
    date_from: str,
    date_to: str,
) -> str:
    """List Google Calendar events in a date range.

    Args:
        date_from: Start date in ISO 8601 format.
        date_to: End date in ISO 8601 format.
    """
    time_min = datetime.fromisoformat(date_from)
    time_max = datetime.fromisoformat(date_to)
    events = await ctx.context.calendar.list_events(
        time_min=time_min, time_max=time_max
    )
    if not events:
        return "No events found in that range."
    lines = []
    for ev in events:
        start = ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))
        lines.append(f"- {ev.get('summary', '(no title)')} | {start} | id: {ev.get('id')}")
    return "\n".join(lines)


# ------------------------------------------------------------------
# Agent builder
# ------------------------------------------------------------------

ALL_TOOLS = [
    # Classification
    apply_label,
    # Context
    search_emails,
    get_email_thread,
    get_emails_from_sender,
    # Todoist
    create_task,
    add_comment,
    # Calendar
    update_event,
    create_event,
    list_events,
]


def build_triage_agent(
    todoist_context: str,
    calendar_context: str,
) -> Agent:
    """Build the unified triage agent with all tools and pre-loaded context."""
    env = Environment(loader=FileSystemLoader(PROMPTS_DIR))
    template = env.get_template("triage.j2")

    instructions = template.render(
        todoist_context=todoist_context,
        calendar_context=calendar_context,
        # Per-email fields are placeholders; actual content comes via Runner input.
        sender="(see Current Email below)",
        recipients="(see Current Email below)",
        date="(see Current Email below)",
        subject="(see Current Email below)",
        body="(see Current Email below)",
        thread_context="",
    )

    return Agent(
        name="Triage Agent",
        instructions=instructions,
        model="gpt-5.2",
        model_settings=ModelSettings(extra_args={"service_tier": "flex"}),
        tools=ALL_TOOLS,
    )


def render_email_input(email: Email) -> str:
    """Format an email as input text for the triage agent."""
    parts = [
        f"From: {email.sender}",
        f"To: {', '.join(email.recipients)}",
        f"Date: {email.date}",
        f"Subject: {email.subject}",
        f"Thread ID: {email.thread_id}",
        "",
        email.body_plain or email.snippet or "(no body)",
    ]
    return "\n".join(parts)
