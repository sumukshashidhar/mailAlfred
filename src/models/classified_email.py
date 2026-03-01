from pydantic import BaseModel, Field, field_validator

ALLOWED_LABELS = {
    "classifications/respond",
    "classifications/urgent",
    "classifications/action",
    "classifications/opportunities",
    "classifications/academic",
    "classifications/notifications",
    "classifications/records",
    "classifications/read_later",
    "classifications/marketing",
    "classifications/bulk",
    "classifications/unsure",
}

LABEL_ALIASES = {
    # Old labels → new canonical names
    "classifications/requires_action": "classifications/respond",
    "classifications/bulk_content": "classifications/bulk",
    # Typo aliases (keep existing)
    "classification/notifications": "classifications/notifications",
    "classfications/notifications": "classifications/notifications",
    "classification/marketing": "classifications/marketing",
    "classfications/marketing": "classifications/marketing",
    # New typo aliases
    "classification/respond": "classifications/respond",
    "classification/urgent": "classifications/urgent",
    "classification/action": "classifications/action",
    "classification/academic": "classifications/academic",
    "classification/bulk": "classifications/bulk",
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
