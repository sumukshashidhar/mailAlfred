"""Shared Jinja template utilities for prompt rendering."""

from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined

PROMPTS_DIR = Path(__file__).parent.parent.parent / "prompts"


@lru_cache(maxsize=1)
def _get_environment() -> Environment:
    """Create a Jinja environment rooted at the repository prompts directory."""
    return Environment(
        loader=FileSystemLoader(str(PROMPTS_DIR)),
        autoescape=False,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_prompt_template(template_path: str, **context: Any) -> str:
    """Render a prompt template by relative path under prompts/."""
    template = _get_environment().get_template(template_path)
    return template.render(**context)
