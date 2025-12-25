# Architecture

This document describes mailAlfred's system design and the main extension points.

## High-level flow

1. Fetch emails from Gmail
2. Build a classification prompt
3. Call the LLM with structured output parsing
4. Apply a Gmail label back to the message
5. Emit a summary of results

```
Gmail API -> Email model -> Prompt -> LLM -> ClassifiedEmail -> Gmail label
```

## Core modules

- `src/main.py`
  - CLI parsing
  - Orchestrates scan -> classify -> label
  - Concurrency control via asyncio + semaphore

- `src/connectors/gmail_connector.py`
  - Gmail OAuth and API integration
  - Email parsing and body extraction
  - Label creation and application
  - Optional seen-email cache for incremental iteration

- `src/utils/prompts.py`
  - Loads `prompts/CLASSIFICATION_PROMPT.md`
  - Injects email context and current timestamp

- `src/utils/inference.py`
  - OpenAI-compatible client
  - Structured output parsing into Pydantic models
  - Retry logic with exponential backoff

- `src/models/`
  - `Email` for parsed Gmail messages
  - `ClassifiedEmail` for LLM output validation

## Concurrency model

Classification requests are executed concurrently with an asyncio semaphore. This keeps throughput high while avoiding provider rate limits. The concurrency limit is configurable via CLI.

## Label strategy

mailAlfred treats Gmail labels as the source of truth. If a message already has any classification label, it is skipped. This avoids re-processing and keeps the pipeline stateless.

## Extensibility

mailAlfred is intentionally modular. Common extensions include:

- Custom label taxonomies (`src/models/classified_email.py` and `prompts/CLASSIFICATION_PROMPT.md`)
- Alternative prompt formats or richer context (`src/utils/prompts.py`)
- New connectors (e.g., IMAP, Outlook) by mirroring the `GmailConnector` interface
- Different LLM backends (replace or wrap `src/utils/inference.py`)
- Additional actions (forward, archive, reply) after classification

See `extending.md` for implementation guidance.
