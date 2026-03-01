from pydantic import BaseModel, Field, field_validator

ALLOWED_LABELS = {
    "classifications/bulk_content",
    "classifications/marketing",
    "classifications/notifications",
    "classifications/read_later",
    "classifications/records",
    "classifications/opportunities",
    "classifications/requires_action",
    "classifications/unsure",
}

LABEL_ALIASES = {
    "classification/notifications": "classifications/notifications",
    "classfications/notifications": "classifications/notifications",
    "classification/marketing": "classifications/marketing",
    "classfications/marketing": "classifications/marketing",
}


class ClassifiedEmail(BaseModel):
    label: str = Field(
        description="A label that describes the email"
    )
    
    @field_validator("label")
    @classmethod
    def validate_label(cls, v: str) -> str:
        """Validate that the label is in the allowed set."""
        canonical_label = LABEL_ALIASES.get(v.strip(), v.strip())
        if canonical_label not in ALLOWED_LABELS:
            raise ValueError(
                f"Invalid label: {v}. "
                f"Allowed labels are: {sorted(ALLOWED_LABELS)}"
            )
        return canonical_label
