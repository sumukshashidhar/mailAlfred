"""Label translation: triage categories to Gmail label IDs."""

from __future__ import annotations

import json
from pathlib import Path

# Triage agent output label -> Gmail label name
TRIAGE_TO_GMAIL: dict[str, str] = {
    "respond": "c/a/respond",
    "do": "c/a/do",
    "follow_up": "c/a/followup",
    "reference": "c/r/records",
    "read": "c/b/read",
    "notification": "c/b/notif",
    "marketing": "c/b/mktng",
}

# Reverse mapping for convenience
GMAIL_TO_TRIAGE: dict[str, str] = {v: k for k, v in TRIAGE_TO_GMAIL.items()}


class LabelResolver:
    """Resolves triage label names to Gmail label IDs at runtime."""

    def __init__(self) -> None:
        self._name_to_id: dict[str, str] = {}

    async def initialize(self, gmail) -> None:
        """Fetch all Gmail labels and build the name-to-ID mapping.

        Must be called once before resolve().
        """
        labels = await gmail.list_labels()
        for label in labels:
            self._name_to_id[label["name"]] = label["id"]

    @property
    def initialized(self) -> bool:
        return len(self._name_to_id) > 0

    def resolve(self, triage_label: str) -> str:
        """Convert a triage label (e.g. 'do') to a Gmail label ID.

        Raises ValueError if the label is unknown or not found in Gmail.
        """
        gmail_name = TRIAGE_TO_GMAIL.get(triage_label)
        if gmail_name is None:
            raise ValueError(
                f"Unknown triage label: {triage_label!r}. "
                f"Valid labels: {list(TRIAGE_TO_GMAIL.keys())}"
            )
        label_id = self._name_to_id.get(gmail_name)
        if label_id is None:
            raise ValueError(
                f"Gmail label {gmail_name!r} not found. "
                f"Available labels: {list(self._name_to_id.keys())}"
            )
        return label_id

    def get_all_triage_labels(self) -> list[str]:
        """Return all valid triage label names."""
        return list(TRIAGE_TO_GMAIL.keys())
