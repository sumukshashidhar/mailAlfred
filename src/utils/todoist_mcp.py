"""Minimal Todoist MCP helpers for local scripting."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

from agents.mcp import MCPServerStdio
from dotenv import load_dotenv
from loguru import logger


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROJECT_ENV_PATH = PROJECT_ROOT / ".env"
REFLECTION_ENV_CANDIDATES = (
    Path.home() / "Documents/root/resources/reflection/.scripts/.env",
    Path.home() / "Documents/root/resources/reflection/.env",
)


def _read_env_value(path: Path, keys: tuple[str, ...]) -> str | None:
    if not path.exists():
        return None
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() in keys:
            return value.strip()
    return None


def resolve_todoist_api_key(explicit_key: str | None = None) -> str:
    """Resolve Todoist API key from explicit value, process env, or local env files."""
    if explicit_key:
        return explicit_key

    load_dotenv(dotenv_path=PROJECT_ENV_PATH, override=False)

    env_key = os.getenv("TODOIST_API_KEY") or os.getenv("TODOIST_API_TOKEN")
    if env_key:
        return env_key

    for env_path in REFLECTION_ENV_CANDIDATES:
        file_key = _read_env_value(env_path, ("TODOIST_API_KEY", "TODOIST_API_TOKEN"))
        if file_key:
            return file_key

    raise RuntimeError(
        "Todoist API key not found. Set TODOIST_API_KEY in .env or reflection env files."
    )


async def search_todoist(query: str, todoist_api_key: str | None = None) -> dict[str, Any]:
    """
    Search Todoist via the Todoist MCP server's OpenAI-compatible `search` tool.

    Returns the MCP structured response payload (typically includes `results`).
    """
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must be a non-empty string")

    key = resolve_todoist_api_key(todoist_api_key)
    server = MCPServerStdio(
        params={
            "command": "todoist-ai",
            "env": {"TODOIST_API_KEY": key},
        }
    )

    async with server:
        result = await server.call_tool("search", {"query": normalized_query})

    if result.structuredContent:
        return result.structuredContent

    return {"results": [], "raw": str(result)}


def search_todoist_sync(query: str, todoist_api_key: str | None = None) -> dict[str, Any]:
    """Synchronous wrapper for search_todoist()."""
    return asyncio.run(search_todoist(query=query, todoist_api_key=todoist_api_key))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Search Todoist using MCP.")
    parser.add_argument("query", help="Search query")
    args = parser.parse_args()

    payload = search_todoist_sync(args.query)
    results = payload.get("results", [])
    logger.info(f"results={len(results)}")
    for item in results[:10]:
        item_type = item.get("type", "")
        title = item.get("name") or item.get("content") or ""
        item_id = item.get("id", "")
        logger.info(f"{item_type}\t{title}\t{item_id}")
