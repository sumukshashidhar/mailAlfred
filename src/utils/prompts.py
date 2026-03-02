from datetime import datetime
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, StrictUndefined, Template

from src.models.classified_email import ALLOWED_LABELS
from src.models.email import Email

MAX_BODY_CHARS = 4000
_PROMPT_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "prompts" / "CLASSIFICATION_PROMPT.j2"


@lru_cache(maxsize=1)
def _read_prompt_from_file() -> str:
    """Read the classification prompt template source from disk."""
    return _PROMPT_TEMPLATE_PATH.read_text()


@lru_cache(maxsize=1)
def _load_prompt_template() -> Template:
    """Load and compile the Jinja template once per process."""
    env = Environment(autoescape=False, undefined=StrictUndefined, keep_trailing_newline=True)
    return env.from_string(_read_prompt_from_file())


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

    template = _load_prompt_template()
    return template.render(
        sender=source_email.sender,
        recipients=recipients_str,
        cc=cc_str,
        date=date_str,
        subject=source_email.subject,
        body=body,
        current_datetime=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        allowed_labels=sorted(ALLOWED_LABELS),
    )
