# Getting Started

Get mailAlfred running quickly and safely.

## Prerequisites

- Python 3.12+
- `uv` package manager
- Gmail account
- OpenAI-compatible API key

## Installation

```bash
git clone https://github.com/sumukshashidhar/mailAlfred.git
cd mailAlfred
uv sync
```

## Setup

### 1) Gmail OAuth credentials

Download OAuth credentials from Google Cloud Console and save as `credentials.json` in the project root.

See `gmail-setup.md` for the full walkthrough.

### 2) LLM credentials

Create `.env` in the project root:

```bash
OPENAI_API_KEY=sk-your-key-here
# Optional: use a compatible provider endpoint
# OPENAI_BASE_URL=https://your-provider.com/v1
```

See `llm-setup.md` for provider options.

## First Run

Dry run first to validate permissions and labels:

```bash
uv run python -m src.main --dry-run -n 5 -v
```

Real run:

```bash
uv run python -m src.main
```

On first run, a browser window opens for Gmail authorization. A `token.json` file is saved for subsequent runs.

## What happens next

mailAlfred scans the inbox, sends each unclassified email to the LLM, and applies a Gmail label. A summary table shows counts by label.

## Next steps

- `cli-reference.md` for all CLI options
- `labels.md` to understand or change the taxonomy
- `architecture.md` for system design and extension points
