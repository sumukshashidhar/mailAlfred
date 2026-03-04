"""Todoist API v1 connector."""

from __future__ import annotations

import os
import uuid

import httpx


class Todoist:
    """Async Todoist client using the unified API v1."""

    BASE_URL = "https://api.todoist.com/api/v1"

    def __init__(self, token: str | None = None) -> None:
        self._token = token or os.environ["TODOIST_API_TOKEN"]

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    # ------------------------------------------------------------------
    # Read operations (used for context pre-loading)
    # ------------------------------------------------------------------

    async def get_projects(self) -> list[dict]:
        """List all projects."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.BASE_URL}/projects", headers=self._headers
            )
            resp.raise_for_status()
            return resp.json().get("results", [])

    async def get_labels(self) -> list[dict]:
        """List all personal labels."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.BASE_URL}/labels", headers=self._headers
            )
            resp.raise_for_status()
            return resp.json().get("results", [])

    async def get_tasks(self, project_id: str | None = None) -> list[dict]:
        """List active tasks, optionally filtered by project."""
        params: dict[str, str] = {}
        if project_id:
            params["project_id"] = project_id
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.BASE_URL}/tasks",
                headers=self._headers,
                params=params,
            )
            resp.raise_for_status()
            return resp.json().get("results", [])

    # ------------------------------------------------------------------
    # Write operations (used as agent tools)
    # ------------------------------------------------------------------

    async def create_task(
        self,
        content: str,
        *,
        description: str = "",
        project_id: str | None = None,
        priority: int = 1,
        due_string: str | None = None,
        labels: list[str] | None = None,
    ) -> dict:
        """Create a new task.

        Args:
            content: Task title.
            description: Longer description / notes.
            project_id: Target project ID.
            priority: 1 (normal) to 4 (urgent).
            due_string: Natural language due date (e.g. "tomorrow").
            labels: List of label names to apply.
        """
        body: dict = {"content": content, "description": description, "priority": priority}
        if project_id:
            body["project_id"] = project_id
        if due_string:
            body["due_string"] = due_string
        if labels:
            body["labels"] = labels

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.BASE_URL}/tasks",
                headers={**self._headers, "X-Request-Id": str(uuid.uuid4())},
                json=body,
            )
            resp.raise_for_status()
            return resp.json()

    async def add_comment(self, task_id: str, content: str) -> dict:
        """Add a comment to an existing task."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.BASE_URL}/comments",
                headers={**self._headers, "X-Request-Id": str(uuid.uuid4())},
                json={"task_id": task_id, "content": content},
            )
            resp.raise_for_status()
            return resp.json()
