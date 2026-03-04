"""Triage agent: classifies emails, applies labels, hands off to sub-agents."""

from __future__ import annotations

from agents import Agent, ModelSettings, RunContextWrapper, function_tool
from jinja2 import Environment, FileSystemLoader

from src.agents.context import PROMPTS_DIR, PipelineContext
from src.models import Email


# ------------------------------------------------------------------
# Tools
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
# Agent builder
# ------------------------------------------------------------------


def build_triage_agent(
    calendar_agent: Agent,
    todoist_agent: Agent,
) -> Agent:
    """Build the triage agent with tools and handoffs to sub-agents."""
    env = Environment(loader=FileSystemLoader(PROMPTS_DIR))
    template = env.get_template("email_triage.j2")

    # Render with placeholders — per-email content comes via Runner input.
    instructions = template.render(
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
        tools=[apply_label, search_emails, get_email_thread, get_emails_from_sender],
        handoffs=[calendar_agent, todoist_agent],
    )


def render_email_for_triage(email: Email) -> str:
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
