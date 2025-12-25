# CLI Reference

Run mailAlfred via the module entry point:

```bash
uv run python -m src.main [options]
```

## Options

- `-n`, `--limit` - Maximum number of emails to classify (default: all unclassified)
- `--scan-limit` - Maximum number of emails to scan before stopping
- `--dry-run` - Do not apply labels, only report what would happen
- `-v`, `--verbose` - Print every classification, not just requires_action
- `-w`, `--watch` - Run continuously and poll for new mail
- `--interval` - Seconds between checks in watch mode (default: 30)
- `-c`, `--concurrency` - Max concurrent LLM requests (default: 10)

## Examples

Classify at most 20 emails:

```bash
uv run python -m src.main -n 20
```

Scan up to 500 emails but only classify 50:

```bash
uv run python -m src.main --scan-limit 500 -n 50
```

Dry run with verbose output:

```bash
uv run python -m src.main --dry-run -v
```

Watch mode (poll every 2 minutes):

```bash
uv run python -m src.main --watch --interval 120
```

## Notes

- An email is considered "already classified" if it has any of the classification labels defined in `src/models/classified_email.py`.
- Labels are created lazily when applying the first classification.
- The CLI uses label presence as the primary guardrail against re-processing.
