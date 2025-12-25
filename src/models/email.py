"""
Email data model for Gmail messages.
"""
from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional


class Email(BaseModel):
    """Represents a Gmail email message with parsed fields."""
    
    id: str = Field(description="Unique Gmail message ID")
    thread_id: str = Field(description="Thread ID this message belongs to")
    subject: str = Field(default="", description="Email subject line")
    sender: str = Field(default="", description="From address")
    recipients: list[str] = Field(default_factory=list, description="To addresses")
    cc: list[str] = Field(default_factory=list, description="CC addresses")
    date: Optional[datetime] = Field(default=None, description="Date the email was sent")
    snippet: str = Field(default="", description="Short snippet preview of the email")
    body_plain: str = Field(default="", description="Plain text body")
    body_html: str = Field(default="", description="HTML body")
    labels: list[str] = Field(default_factory=list, description="Gmail labels applied to this message")
    
    def __str__(self) -> str:
        return f"Email(id={self.id}, subject={self.subject[:50]}..., from={self.sender})"
    
    def __repr__(self) -> str:
        return self.__str__()

