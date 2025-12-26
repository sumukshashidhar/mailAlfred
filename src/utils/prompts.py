from pathlib import Path
from functools import lru_cache
from datetime import datetime
from src.models.email import Email
from src.models.classified_email import ALLOWED_LABELS


MAX_BODY_CHARS = 4000

@lru_cache(maxsize=1)
def _read_prompt_from_file() -> str:
    """Read the classification prompt template from the markdown file."""
    prompt_path = Path(__file__).parent.parent.parent / "prompts" / "CLASSIFICATION_PROMPT.md"
    return prompt_path.read_text()

def _truncate_body(body: str) -> str:
    if len(body) <= MAX_BODY_CHARS:
        return body
    return body[:MAX_BODY_CHARS] + "\n\n[truncated]"


def get_email_classification_prompt(source_email: Email) -> str:
    """
    Build the full classification prompt for a given email.
    
    Combines the classification instructions from the prompt file
    with the email details (from, to, subject, body, etc.).
    """
    system_prompt = _read_prompt_from_file()
    
    # Format recipients and CC as comma-separated strings
    recipients_str = ", ".join(source_email.recipients) if source_email.recipients else "(none)"
    cc_str = ", ".join(source_email.cc) if source_email.cc else "(none)"
    
    # Format the date
    date_str = source_email.date.strftime("%Y-%m-%d %H:%M:%S") if source_email.date else "(unknown)"
    
    # Use plain text body, fall back to snippet if empty
    body = source_email.body_plain.strip() if source_email.body_plain else source_email.snippet
    body = _truncate_body(body)
    
    # Build the email context
    email_context = f"""
---
EMAIL TO CLASSIFY:
---
From: {source_email.sender}
To: {recipients_str}
CC: {cc_str}
Date: {date_str}
Subject: {source_email.subject}

Body:
{body}
---

Current datetime: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

Please classify this email into exactly one of the following labels:
{sorted(ALLOWED_LABELS)}

Respond with ONLY the label (e.g., "classifications/requires_action").
"""

    return system_prompt + email_context
