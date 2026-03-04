from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Attachment:
    """Email attachment metadata and content."""

    filename: str
    mime_type: str
    size: int
    attachment_id: str = ""
    data: bytes = b""


@dataclass
class Email:
    """Email fetched from Gmail."""

    # Identifiers
    id: str
    thread_id: str

    # Core headers
    subject: str = ""
    sender: str = ""
    recipients: list[str] = field(default_factory=list)
    cc: list[str] = field(default_factory=list)
    bcc: list[str] = field(default_factory=list)
    date: datetime | None = None

    # Threading headers
    message_id: str = ""
    in_reply_to: str = ""
    references: list[str] = field(default_factory=list)

    # Body content
    snippet: str = ""
    body_plain: str = ""
    body_html: str = ""

    # Metadata
    labels: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)

