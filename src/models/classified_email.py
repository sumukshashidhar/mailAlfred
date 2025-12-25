from pydantic import BaseModel, Field, field_validator

ALLOWED_LABELS = {
    "classifications/bulk_content",
    "classifications/read_later",
    "classifications/records",
    "classifications/requires_action",
    "classifications/unsure",
}

class ClassifiedEmail(BaseModel):
    label: str = Field(
        description="A label that describes the email"
    )
    
    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str) -> str:
        """Validate that the label is in the allowed set."""
        if v not in ALLOWED_LABELS:
            raise ValueError(
                f"Invalid label: {v}. "
                f"Allowed labels are: {sorted(ALLOWED_LABELS)}"
            )
        return v