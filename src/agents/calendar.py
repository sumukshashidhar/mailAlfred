"""Calendar agent: enriches/creates Google Calendar events from emails."""

from __future__ import annotations

from datetime import datetime

from agents import Agent, ModelSettings, RunContextWrapper, function_tool
from jinja2 import Environment, FileSystemLoader

from src.agents.context import PROMPTS_DIR, PipelineContext


@function_tool
async def update_event(
    ctx: RunContextWrapper[PipelineContext],
    event_id: str,
    notes: str,
) -> str:
    """Add notes/details to an existing Google Calendar event.

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
    """List Google Calendar events in a date range (fallback if pre-loaded context isn't enough).

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


def build_calendar_agent(calendar_context_str: str) -> Agent:
    """Build the calendar agent with pre-loaded context baked into instructions."""
    env = Environment(loader=FileSystemLoader(PROMPTS_DIR))
    template = env.get_template("calendar_agent.j2")

    instructions = template.render(
        calendar_context=calendar_context_str,
        sender="(provided in the handoff input)",
        subject="(provided in the handoff input)",
        date="(provided in the handoff input)",
        body="(provided in the handoff input)",
    )

    return Agent(
        name="Calendar Agent",
        handoff_description="Handles calendar invites, meeting requests, and scheduling emails. Hand off when an email contains calendar-relevant information.",
        instructions=instructions,
        model="gpt-5.2",
        model_settings=ModelSettings(extra_args={"service_tier": "flex"}),
        tools=[update_event, create_event, list_events],
    )
