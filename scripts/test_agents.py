from __future__ import annotations

import argparse
import html
import json
import re
import shlex
import subprocess
import sys
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents import Agent, ModelSettings, Runner
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from loguru import logger
from pydantic import BaseModel, Field, field_validator
from todoist_api_python.api import TodoistAPI

# Ensure `src/` imports work when this script is run directly.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.models.classified_email import ALLOWED_LABELS, ClassifiedEmail
from src.utils.gog_email import get_email, search_email
from src.utils.template_utils import render_prompt_template
from src.utils.todoist_mcp import resolve_todoist_api_key


MAX_BODY_CHARS = 6000
COMMON_MODEL_SETTINGS = ModelSettings(
    extra_body={"service_tier": "flex"},
    reasoning={"effort": "medium", "summary": "auto"},
)


class TodoistTaskDraft(BaseModel):
    create_task: bool = False
    content: str = ""
    description: str = ""
    due_string: str | None = None
    priority: int | None = Field(default=None, ge=1, le=4)


class CalendarEventDraft(BaseModel):
    create_event: bool = False
    summary: str = ""
    start_rfc3339: str | None = None
    end_rfc3339: str | None = None
    description: str = ""
    location: str = ""


class MainTriageDecision(BaseModel):
    label: str
    delegate_todoist: bool = False
    delegate_calendar: bool = False
    rationale: str = ""

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        return ClassifiedEmail(label=value).label


@dataclass(slots=True)
class CliConfig:
    query: str
    max_results: int
    account: str | None
    execute: bool
    apply_label: bool


@dataclass(slots=True)
class EmailEnvelope:
    sender: str
    subject: str
    thread_id: str | None
    triage_prompt: str
    subagent_prompt: str
    representation: str


def parse_args() -> CliConfig:
    parser = argparse.ArgumentParser(description="Email triage orchestrator with Todoist/Calendar delegation.")
    parser.add_argument("--query", default="in:inbox newer_than:7d", help="Gmail query for gog search")
    parser.add_argument("--max-results", type=int, default=3, help="Maximum emails to triage")
    parser.add_argument("--account", default=None, help="Optional Gmail account for gog")
    parser.add_argument("--execute", action="store_true", help="Apply Todoist/Calendar writes")
    parser.add_argument("--apply-label", action="store_true", help="Apply classified Gmail label (honors --execute)")
    args = parser.parse_args()
    return CliConfig(args.query, args.max_results, args.account, args.execute, args.apply_label)


def _norm(value: Any, fallback: str = "") -> str: return str(value or "").strip() or fallback


def _truncate(text: str, limit: int) -> str: return text if len(text) <= limit else f"{text[:limit]}\n\n[truncated]"


def _headers(payload: dict[str, Any]) -> dict[str, str]:
    raw = ((payload.get("message") or {}).get("payload") or {}).get("headers") or []
    return {
        _norm(item.get("name")).lower(): _norm(item.get("value"))
        for item in raw
        if _norm(item.get("name"))
    }


def _received_timestamp(payload: dict[str, Any]) -> str:
    internal = (payload.get("message") or {}).get("internalDate")
    if internal is None:
        return "(unknown)"
    try:
        return datetime.fromtimestamp(int(str(internal)) / 1000, tz=timezone.utc).isoformat()
    except Exception:
        return "(unknown)"


def _label_string(search_hit: dict[str, Any]) -> str:
    return ", ".join(labels) if (labels := search_hit.get("labels", [])) else "(none)"


def clean_email_body(raw_body: str) -> str:
    soup = BeautifulSoup(raw_body or "", "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = html.unescape(soup.get_text("\n"))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def build_envelope(search_hit: dict[str, Any], account: str | None) -> EmailEnvelope:
    message_id = _norm(search_hit.get("id"), "")
    payload = get_email(message_id, account=account) if message_id else {}
    headers = _headers(payload)
    message = payload.get("message") or {}
    cleaned_body = clean_email_body(_norm(payload.get("body"), "")) or _norm(message.get("snippet"), "")
    context = {
        "sender": _norm(search_hit.get("from")),
        "to": _norm(headers.get("to"), "(unknown)"),
        "cc": _norm(headers.get("cc"), "(none)"),
        "reply_to": _norm(headers.get("reply-to"), "(none)"),
        "subject": _norm(search_hit.get("subject")),
        "sent_timestamp": _norm(headers.get("date") or search_hit.get("date"), "(unknown)"),
        "received_timestamp": _received_timestamp(payload),
        "search_date": _norm(search_hit.get("date"), "(unknown)"),
        "thread_id": _norm(message.get("threadId"), "(unknown)"),
        "message_id_header": _norm(headers.get("message-id"), "(unknown)"),
        "message_id": _norm(message.get("id") or search_hit.get("id"), "(unknown)"),
        "message_count": _norm(search_hit.get("messageCount"), "0"),
        "current_labels": _label_string(search_hit),
        "current_datetime": datetime.now().isoformat(),
        "body": _truncate(cleaned_body, MAX_BODY_CHARS),
    }
    thread_id = context["thread_id"] if context["thread_id"] != "(unknown)" else None
    return EmailEnvelope(
        sender=context["sender"],
        subject=context["subject"],
        thread_id=thread_id,
        triage_prompt=render_prompt_template("triage/main_triage_input.j2", email=context),
        subagent_prompt=render_prompt_template("triage/subagent_input.j2", email=context),
        representation=render_prompt_template("triage/email_representation.j2", email=context),
    )


def extract_reasoning_summaries(run_result: Any) -> list[str]:
    return [
        text
        for response in run_result.raw_responses
        for item in (response.output or [])
        if item.type == "reasoning"
        for summary in (item.summary or [])
        if (text := _norm(summary.text))
    ]


def log_reasoning(name: str, run_result: Any) -> None:
    summaries = extract_reasoning_summaries(run_result)
    if not summaries:
        logger.info(f"{name} reasoning_summary: (none returned for this run)")
        return
    logger.info(f"{name} reasoning_summary:")
    for i, summary in enumerate(summaries, start=1):
        logger.info(f"  {i}. {summary}")


def _run_json_command(cmd: list[str]) -> tuple[int, dict[str, Any] | list[Any], str]:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode:
        return proc.returncode, {}, _norm(proc.stderr, f"command failed ({proc.returncode})")
    try:
        return 0, json.loads(proc.stdout.strip() or "{}"), ""
    except json.JSONDecodeError:
        return 0, {"raw": proc.stdout.strip()}, ""


def maybe_create_todoist_task(draft: TodoistTaskDraft | None, execute: bool) -> dict[str, Any]:
    if not draft or not draft.create_task: return {"status": "skipped", "reason": "agent_decided_no_task"}
    if not (content := draft.content.strip()): return {"status": "skipped", "reason": "missing_task_content"}
    if not execute:
        return {"status": "dry_run", "content": content, "description": draft.description, "due_string": draft.due_string, "priority": draft.priority}
    task = TodoistAPI(resolve_todoist_api_key()).add_task(
        content=content,
        description=draft.description or None,
        due_string=draft.due_string or None,
        priority=draft.priority,
    )
    return {"status": "created", "id": _norm(task.id, ""), "url": task.url, "content": task.content}


def maybe_create_calendar_event(draft: CalendarEventDraft | None, account: str | None, execute: bool) -> dict[str, Any]:
    if not draft or not draft.create_event: return {"status": "skipped", "reason": "agent_decided_no_event"}
    if not all([draft.summary.strip(), draft.start_rfc3339, draft.end_rfc3339]): return {"status": "skipped", "reason": "missing_event_fields"}
    cmd = [
        "gog", "calendar", "create", "primary",
        f"--summary={draft.summary}",
        f"--from={draft.start_rfc3339}",
        f"--to={draft.end_rfc3339}",
        "--json", "--results-only", "--no-input",
    ]
    if description := draft.description.strip(): cmd.append(f"--description={description}")
    if location := draft.location.strip(): cmd.append(f"--location={location}")
    if account: cmd.extend(["--account", account])
    if not execute: return {"status": "dry_run", "command": " ".join(shlex.quote(part) for part in cmd)}
    code, payload, error = _run_json_command(cmd)
    if code: return {"status": "error", "error": error}
    event_id = ""
    with suppress(Exception):
        event_id = _norm(payload.get("id") or payload.get("eventId"), "")
    return {"status": "created", "id": event_id or None, "payload": payload}


def maybe_apply_gmail_label(thread_id: str | None, label_name: str, account: str | None, execute: bool) -> dict[str, Any]:
    if not thread_id: return {"status": "skipped", "reason": "missing_thread_id"}
    cmd = ["gog", "gmail", "thread", "modify", thread_id, f"--add={label_name}", "--json", "--results-only", "--no-input"]
    if account: cmd.extend(["--account", account])
    if not execute: return {"status": "dry_run", "command": " ".join(shlex.quote(part) for part in cmd)}
    code, payload, error = _run_json_command(cmd)
    if code: return {"status": "error", "error": error}
    return {"status": "applied", "payload": payload}


def build_agents() -> tuple[Agent, Agent, Agent]:
    main_agent = Agent(
        name="MainTriageAgent",
        model="gpt-5-mini",
        model_settings=COMMON_MODEL_SETTINGS,
        output_type=MainTriageDecision,
        instructions=render_prompt_template("triage/main_agent_instructions.j2", allowed_labels=sorted(ALLOWED_LABELS)),
    )
    todoist_agent = Agent(
        name="TodoistAgent",
        model="gpt-5-mini",
        model_settings=COMMON_MODEL_SETTINGS,
        output_type=TodoistTaskDraft,
        instructions=render_prompt_template("triage/todoist_agent_instructions.j2"),
    )
    calendar_agent = Agent(
        name="CalendarAgent",
        model="gpt-5-mini",
        model_settings=COMMON_MODEL_SETTINGS,
        output_type=CalendarEventDraft,
        instructions=render_prompt_template("triage/calendar_agent_instructions.j2"),
    )
    return main_agent, todoist_agent, calendar_agent


def _run_main(agent: Agent, prompt: str) -> tuple[MainTriageDecision, Any]:
    run = Runner.run_sync(agent, prompt)
    try:
        decision = MainTriageDecision.model_validate(run.final_output)
    except Exception:
        decision = MainTriageDecision(label="classifications/unsure", rationale=str(run.final_output))
    return decision, run


def _run_todoist(agent: Agent, prompt: str, enabled: bool) -> tuple[TodoistTaskDraft | None, Any | None]:
    if not enabled: return None, None
    run = Runner.run_sync(agent, prompt)
    try:
        return TodoistTaskDraft.model_validate(run.final_output), run
    except Exception:
        logger.warning(f"todoist_unparsed_output: {run.final_output}")
        return None, run


def _run_calendar(agent: Agent, prompt: str, enabled: bool) -> tuple[CalendarEventDraft | None, Any | None]:
    if not enabled: return None, None
    run = Runner.run_sync(agent, prompt)
    try:
        return CalendarEventDraft.model_validate(run.final_output), run
    except Exception:
        logger.warning(f"calendar_unparsed_output: {run.final_output}")
        return None, run


def triage_one_email(
    main_agent: Agent,
    todoist_agent: Agent,
    calendar_agent: Agent,
    envelope: EmailEnvelope,
    cfg: CliConfig,
    index: int,
    total: int,
) -> dict[str, str]:
    logger.info(f"=== EMAIL {index}/{total} ===")
    logger.info(f"sender: {envelope.sender}")
    logger.info(f"subject: {envelope.subject}")
    logger.info(f"representation:\n{'-' * 80}\n{envelope.representation}\n{'-' * 80}")

    decision, main_run = _run_main(main_agent, envelope.triage_prompt)
    logger.info(f"label: {decision.label}")
    logger.info(f"orchestrator_rationale: {decision.rationale}")
    logger.info(f"delegate_todoist={decision.delegate_todoist} delegate_calendar={decision.delegate_calendar}")
    log_reasoning("main_agent", main_run)

    label_result = {"status": "skipped", "reason": "apply_label_flag_false"}
    if cfg.apply_label:
        label_result = maybe_apply_gmail_label(envelope.thread_id, decision.label, cfg.account, cfg.execute)
        logger.info(f"gmail_label: {label_result}")

    todoist_draft, todoist_run = _run_todoist(todoist_agent, envelope.subagent_prompt, decision.delegate_todoist)
    calendar_draft, calendar_run = _run_calendar(calendar_agent, envelope.subagent_prompt, decision.delegate_calendar)
    if todoist_run: log_reasoning("todoist_agent", todoist_run)
    if calendar_run: log_reasoning("calendar_agent", calendar_run)

    todoist_result = maybe_create_todoist_task(todoist_draft, cfg.execute)
    calendar_result = maybe_create_calendar_event(calendar_draft, cfg.account, cfg.execute)
    logger.info(f"todoist: {todoist_result}")
    logger.info(f"calendar: {calendar_result}")

    return {
        "sender": envelope.sender,
        "subject": envelope.subject,
        "label": decision.label,
        "label_status": _norm(label_result.get("status"), "skipped"),
        "todoist_status": _norm(todoist_result.get("status"), "skipped"),
        "calendar_status": _norm(calendar_result.get("status"), "skipped"),
    }


def main() -> None:
    cfg = parse_args()
    load_dotenv(override=True)
    main_agent, todoist_agent, calendar_agent = build_agents()

    emails = search_email(query=cfg.query, max_results=cfg.max_results, account=cfg.account)
    if not emails:
        logger.info("No emails found.")
        return

    envelopes = [build_envelope(search_hit=item, account=cfg.account) for item in emails]
    records = [
        triage_one_email(main_agent, todoist_agent, calendar_agent, envelope, cfg, index=i, total=len(envelopes))
        for i, envelope in enumerate(envelopes, start=1)
    ]

    logger.info("=== SUMMARY ===")
    for i, row in enumerate(records, start=1):
        logger.info(
            f"{i:>2}. label={row['label']} ({row['label_status']}) | "
            f"todoist={row['todoist_status']} | calendar={row['calendar_status']} | "
            f"{row['sender']} | {row['subject']}"
        )
    logger.info("Writes were ENABLED (--execute)." if cfg.execute else "Dry-run mode: no Todoist or Calendar writes were made. Use --execute to apply.")


if __name__ == "__main__":
    main()
