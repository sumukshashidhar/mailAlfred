"""Pre-fetch context and unified pipeline context."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.connectors.calendar import Calendar
from src.connectors.gmail import Gmail
from src.connectors.todoist import Todoist
from src.labels import LabelResolver
from src.models import Email

# Absolute path to prompts directory (avoids cwd-dependent FileSystemLoader)
PROMPTS_DIR = str(Path(__file__).parent.parent.parent / "prompts")


@dataclass
class PipelineContext:
    """Shared context passed through Runner.run() to all tools."""

    gmail: Gmail
    label_resolver: LabelResolver
    current_email: Email
    calendar: Calendar
    todoist: Todoist
    todoist_project_ids: dict[str, str]  # lowercase name -> project ID


# ------------------------------------------------------------------
# Context pre-fetchers
# ------------------------------------------------------------------


async def fetch_todoist_context(todoist: Todoist) -> tuple[str, dict[str, str]]:
    """Fetch projects, labels, and active tasks.

    Returns:
        Tuple of (formatted markdown context, project name->ID mapping).
    """
    projects, labels, tasks = await asyncio.gather(
        todoist.get_projects(),
        todoist.get_labels(),
        todoist.get_tasks(),
    )

    # Build name -> ID lookup (lowercase keys for fuzzy matching)
    project_ids = {p["name"].lower(): p["id"] for p in projects}

    lines: list[str] = []

    # Projects (names only, no IDs)
    lines.append("## Your Todoist Projects\n")
    for p in projects:
        lines.append(f"- {p['name']}")
    lines.append("")

    # Labels (names only)
    lines.append("## Your Todoist Labels\n")
    for lb in labels:
        lines.append(f"- {lb['name']}")
    lines.append("")

    # Active tasks (grouped by project)
    lines.append("## Current Active Tasks\n")
    project_names = {p["id"]: p["name"] for p in projects}
    by_project: dict[str, list[dict]] = {}
    for t in tasks:
        pid = t.get("project_id", "")
        by_project.setdefault(pid, []).append(t)

    for pid, group in by_project.items():
        pname = project_names.get(pid, "No Project")
        lines.append(f"### {pname}\n")
        for t in group:
            due = ""
            if t.get("due"):
                due = f" (due: {t['due'].get('string', t['due'].get('date', ''))})"
            priority = t.get("priority", 1)
            lines.append(f"- [{_priority_label(priority)}] {t['content']}{due}")
        lines.append("")

    return "\n".join(lines), project_ids


async def fetch_calendar_context(
    calendar: Calendar,
    weeks_back: int = 1,
    weeks_forward: int = 2,
) -> str:
    """Fetch recent and upcoming calendar events; return as formatted markdown."""
    now = datetime.now(timezone.utc)
    time_min = now - timedelta(weeks=weeks_back)
    time_max = now + timedelta(weeks=weeks_forward)

    events = await calendar.list_events(time_min=time_min, time_max=time_max)

    lines: list[str] = []
    lines.append(
        f"## Your Calendar ({weeks_back}w back, {weeks_forward}w ahead)\n"
    )

    if not events:
        lines.append("No events in this range.\n")
        return "\n".join(lines)

    for ev in events:
        start = _event_time(ev, "start")
        end = _event_time(ev, "end")
        summary = ev.get("summary", "(no title)")
        location = ev.get("location", "")

        line = f"- **{summary}** | {start} - {end}"
        if location:
            line += f" | {location}"
        lines.append(line)

    lines.append("")
    return "\n".join(lines)


def _event_time(event: dict, key: str) -> str:
    """Extract a human-readable time from a Calendar event start/end."""
    time_obj = event.get(key, {})
    return time_obj.get("dateTime", time_obj.get("date", "unknown"))


def _priority_label(priority: int) -> str:
    """Convert Todoist priority int to a readable label."""
    return {4: "P1-Urgent", 3: "P2-High", 2: "P3-Medium"}.get(priority, "P4-Normal")
