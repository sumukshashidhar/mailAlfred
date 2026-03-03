from datetime import datetime
from functools import lru_cache
from pathlib import Path

from src.models.classified_email import ALLOWED_LABELS
from src.models.email import Email
from src.utils.template_utils import render_prompt_template

MAX_BODY_CHARS = 4000
_PROMPT_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "prompts" / "CLASSIFICATION_PROMPT.j2"


@lru_cache(maxsize=1)
def _read_prompt_from_file() -> str:
    """Read the classification prompt template source from disk."""
    return _PROMPT_TEMPLATE_PATH.read_text()


def _truncate_body(body: str) -> str:
    if len(body) <= MAX_BODY_CHARS:
        return body
    return body[:MAX_BODY_CHARS] + "\n\n[truncated]"


def get_email_classification_prompt(source_email: Email) -> str:
    """Build a rendered classification prompt for a given email."""
    recipients_str = ", ".join(source_email.recipients) if source_email.recipients else "(none)"
    cc_str = ", ".join(source_email.cc) if source_email.cc else "(none)"
    date_str = source_email.date.strftime("%Y-%m-%d %H:%M:%S") if source_email.date else "(unknown)"

    body = source_email.body_plain.strip() if source_email.body_plain else source_email.snippet
    body = _truncate_body(body)

    return render_prompt_template(
        "CLASSIFICATION_PROMPT.j2",
        sender=source_email.sender,
        recipients=recipients_str,
        cc=cc_str,
        date=date_str,
        subject=source_email.subject,
        body=body,
        current_datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        allowed_labels=sorted(ALLOWED_LABELS),
    )
