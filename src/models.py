from dataclasses import dataclass, field


@dataclass
class Email:
    """Email fetched from Gmail."""

    id: str
    thread_id: str
    subject: str
    sender: str
    body_plain: str = ""
    snippet: str = ""
    date: str | None = None
    labels: list[str] = field(default_factory=list)
