#!/usr/bin/env python3
"""Inspect recent Gmail inbox emails for triage classification analysis.

Fetches ~40 recent emails (mix of read/unread) and prints key fields,
then lists all available Gmail labels on the account.
"""

import sys
import os

# Ensure project root is on sys.path so `src.*` imports work.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.connectors.gmail import Gmail


def main() -> None:
    gmail = Gmail(
        credentials_path=os.path.join(PROJECT_ROOT, "credentials.json"),
        token_path=os.path.join(PROJECT_ROOT, "token.json"),
    )

    # ── 1. Fetch recent emails (mix of read & unread) ──────────────
    # Use the raw API to fetch message stubs, then fetch each one individually
    # with progress output so we can see it working.
    print("=" * 80, flush=True)
    print("FETCHING RECENT EMAILS (up to 50, read + unread)", flush=True)
    print("=" * 80, flush=True)

    service = gmail._get_service()
    response = (
        service.users()
        .messages()
        .list(userId="me", maxResults=50)
        .execute()
    )
    stubs = response.get("messages", [])
    print(f"Found {len(stubs)} message stubs, fetching full details...", flush=True)

    emails = []
    for idx, stub in enumerate(stubs):
        raw = (
            service.users()
            .messages()
            .get(userId="me", id=stub["id"], format="full")
            .execute()
        )
        email = gmail._parse_message(raw)
        emails.append(email)
        print(f"  [{idx+1}/{len(stubs)}] fetched: {email.subject[:60]}", flush=True)

    print(f"\nTotal emails fetched: {len(emails)}\n", flush=True)

    for i, email in enumerate(emails, 1):
        body_preview = (email.body_plain or "")[:200].replace("\n", " ").strip()
        labels_str = ", ".join(email.labels) if email.labels else "(none)"
        date_str = email.date.strftime("%Y-%m-%d %H:%M") if email.date else "unknown"

        print(f"--- Email {i}/{len(emails)} ---", flush=True)
        print(f"  Date:    {date_str}", flush=True)
        print(f"  From:    {email.sender}", flush=True)
        print(f"  Subject: {email.subject}", flush=True)
        print(f"  Labels:  {labels_str}", flush=True)
        print(f"  Snippet: {email.snippet}", flush=True)
        print(f"  Body:    {body_preview}", flush=True)
        print(flush=True)

    # ── 2. List all Gmail labels ───────────────────────────────────
    print("=" * 80, flush=True)
    print("ALL GMAIL LABELS", flush=True)
    print("=" * 80, flush=True)

    labels = gmail._list_labels_sync()
    labels_sorted = sorted(labels, key=lambda l: l.get("name", ""))
    for label in labels_sorted:
        ltype = label.get("type", "")
        print(f"  {label['id']:40s}  {label.get('name', ''):40s}  ({ltype})", flush=True)

    print(f"\nTotal labels: {len(labels)}", flush=True)


if __name__ == "__main__":
    main()
