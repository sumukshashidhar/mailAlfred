# LLM Setup

Configure the language model used for classification.

## OpenAI (default)

Create `.env` in the project root:

```bash
OPENAI_API_KEY=sk-your-key-here
```

mailAlfred uses the OpenAI Python SDK and the Responses API with structured output parsing.

## OpenAI-compatible providers

You can point the SDK to any OpenAI-compatible endpoint:

```bash
OPENAI_API_KEY=your-key
OPENAI_BASE_URL=https://your-provider.com/v1
```

Common options:

- Azure OpenAI
- Ollama (`http://localhost:11434/v1`)
- LM Studio (`http://localhost:1234/v1`)
- Together AI

## Model settings

Defaults are defined in `src/utils/inference.py`:

- `DEFAULT_MODEL = "gpt-5-mini"`
- `DEFAULT_SERVICE_TIER = "flex"`
- `DEFAULT_TIMEOUT = 900`

Change these constants if you want a different model, timeout, or service tier.

## Model selection guidance

- Use smaller models for speed/cost when the label taxonomy is stable
- Use larger models when accuracy on nuanced email content matters
- If you use a third-party provider, ensure it supports structured output parsing
