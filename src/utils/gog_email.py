"""Minimal Gmail search helper backed by gog CLI."""

from __future__ import annotations

import json
import os
import subprocess
from contextlib import suppress
from pathlib import Path
from typing import Any

from loguru import logger


REFLECTION_TOKEN_PATH = (
    Path.home() / "Documents/root/resources/reflection/.scripts/mailAlfred/token.json"
)


def _resolve_account(explicit_account: str | None = None) -> str | None:
    """Resolve account preference for gog calls."""
    if explicit_account:
        return explicit_account

    env_account = os.getenv("GOG_ACCOUNT")
    if env_account:
        return env_account

    if not REFLECTION_TOKEN_PATH.exists():
        return None
    with suppress(json.JSONDecodeError, OSError):
        account = str(json.loads(REFLECTION_TOKEN_PATH.read_text()).get("account", "")).strip()
        if account:
            return account

    return None


def search_email(query: str, max_results: int = 10, account: str | None = None) -> list[dict[str, Any]]:
    """
    Search Gmail via gog CLI and return normalized JSON results.

    Args:
        query: Gmail search query (e.g. 'in:inbox from:github newer_than:7d').
        max_results: Maximum number of thread results.
        account: Optional Google account email for gog; falls back to env/defaults.
    """
    normalized_query = query.strip()
    if not normalized_query:
        raise ValueError("query must be a non-empty Gmail search string")
    if max_results <= 0:
        raise ValueError("max_results must be greater than 0")

    cmd = [
        "gog",
        "gmail",
        "search",
        normalized_query,
        f"--max={max_results}",
        "--json",
        "--results-only",
        "--no-input",
    ]

    resolved_account = _resolve_account(account)
    if resolved_account:
        cmd.extend(["--account", resolved_account])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "unknown gog error"
        raise RuntimeError(f"gog gmail search failed (code {proc.returncode}): {stderr}")

    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("gog returned non-JSON output") from exc

    try:
        if parsed.keys():
            return [parsed]
    except Exception:
        pass

    try:
        if parsed:
            return parsed
    except Exception:
        pass

    if parsed == []:
        return []
    raise RuntimeError(f"unexpected gog output type: {type(parsed).__name__}")


def get_email(message_id: str, account: str | None = None) -> dict[str, Any]:
    """Fetch a full Gmail message payload via gog CLI."""
    normalized_id = message_id.strip()
    if not normalized_id:
        raise ValueError("message_id must be non-empty")

    cmd = [
        "gog",
        "gmail",
        "get",
        normalized_id,
        "--format=full",
        "--json",
        "--results-only",
        "--no-input",
    ]

    resolved_account = _resolve_account(account)
    if resolved_account:
        cmd.extend(["--account", resolved_account])

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = proc.stderr.strip() or "unknown gog error"
        raise RuntimeError(f"gog gmail get failed (code {proc.returncode}): {stderr}")

    try:
        parsed = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("gog returned non-JSON output for message get") from exc

    try:
        parsed.keys()
        return parsed
    except Exception as exc:
        raise RuntimeError(f"unexpected gog get output type: {type(parsed).__name__}") from exc


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Search Gmail with gog.")
    parser.add_argument("query", help="Gmail query string")
    parser.add_argument("--max-results", type=int, default=10, help="Max result count")
    parser.add_argument("--account", default=None, help="Google account email for gog")
    args = parser.parse_args()

    results = search_email(
        query=args.query,
        max_results=args.max_results,
        account=args.account,
    )

    logger.info(f"results={len(results)}")
    for item in results:
        sender = item.get("from", "")
        subject = item.get("subject", "")
        date = item.get("date", "")
        thread_id = item.get("id", "")
        logger.info(f"{date}\t{sender}\t{subject}\t{thread_id}")
