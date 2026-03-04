"""Todoist agent: creates tasks and comments from actionable emails."""

from __future__ import annotations

from agents import Agent, ModelSettings, RunContextWrapper, function_tool
from jinja2 import Environment, FileSystemLoader

from src.agents.context import PROMPTS_DIR, PipelineContext


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


def build_todoist_agent(todoist_context_str: str) -> Agent:
    """Build the Todoist agent with pre-loaded context baked into instructions."""
    env = Environment(loader=FileSystemLoader(PROMPTS_DIR))
    template = env.get_template("todoist_agent.j2")

    instructions = template.render(
        todoist_context=todoist_context_str,
        sender="(provided in the handoff input)",
        subject="(provided in the handoff input)",
        date="(provided in the handoff input)",
        body="(provided in the handoff input)",
    )

    return Agent(
        name="Todoist Agent",
        handoff_description="Handles actionable emails by creating Todoist tasks. Hand off when an email requires the user to take action (labeled 'do').",
        instructions=instructions,
        model="gpt-5.2",
        model_settings=ModelSettings(extra_args={"service_tier": "flex"}),
        tools=[create_task, add_comment],
    )
