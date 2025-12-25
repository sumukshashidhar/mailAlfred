# Contributing

Thanks for considering a contribution. This project values correctness, clarity, and small, reviewable changes.

## Development setup

```bash
git clone https://github.com/sumukshashidhar/mailAlfred.git
cd mailAlfred
uv sync
```

## Running locally

```bash
uv run python -m src.main --dry-run -n 5 -v
```

## Code organization

- `src/` holds application logic
- `prompts/` holds LLM prompt templates
- `docs/` holds documentation

## Guidelines

- Keep changes focused and easy to review
- Prefer explicit, typed data models (Pydantic)
- If you change labels, update both the model and prompt
- Keep prompt changes conservative and measurable

## Commit style

Use conventional commits (for example: `feat: ...`, `fix: ...`, `docs: ...`).

## Pull requests

- Include context and reasoning in the PR description
- Call out behavior changes and any breaking changes
- Add or update docs for user-facing changes
