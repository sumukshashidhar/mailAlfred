# mailAlfred

mailAlfred is an automated Gmail triage tool. It scans your inbox, classifies messages with an LLM, and applies Gmail labels so you can focus on what needs action.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/preview_image_dark.png">
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/preview_image_light.png">
  <img alt="mailAlfred preview" src="docs/assets/preview_image_light.png">
</picture>

Key ideas:
- Small, explicit label taxonomy aligned with real-world workflow
- Structured output (Pydantic) to keep LLM responses predictable
- Parallel classification with concurrency controls
- Gmail-native labels and OAuth, no custom storage needed
- Extensible design: swap prompts, labels, connectors, or model backends

## Quickstart

Prereqs: Python 3.12+, `uv`, Gmail account, OpenAI-compatible API key.

```bash
git clone https://github.com/sumukshashidhar/mailAlfred.git
cd mailAlfred
uv sync

# Add Gmail OAuth credentials
# - Download credentials.json from Google Cloud Console
# - Put it in the project root

# Add your LLM key
cat > .env <<'ENV'
OPENAI_API_KEY=sk-your-key-here
ENV

# Dry run
uv run python -m src.main --dry-run -n 5 -v

# Real run
uv run python -m src.main
```

## Documentation

Start here: `docs/README.md`.

- Getting started and setup guides
- CLI reference and labels
- Architecture and extension points
- Troubleshooting and contributing

## Project Layout

- `src/main.py` - CLI entry point and orchestration
- `src/connectors/gmail_connector.py` - Gmail API integration
- `src/utils/inference.py` - LLM inference and retries
- `src/utils/prompts.py` - Prompt assembly
- `src/models/` - Pydantic models
- `prompts/CLASSIFICATION_PROMPT.md` - Classification instructions
- `docs/` - Documentation

## License

MIT. See `LICENSE`.
