# Labels

mailAlfred uses a small, explicit taxonomy to keep the workflow focused. Labels are stored as Gmail labels under the `classifications/` namespace.

## Taxonomy

- `classifications/bulk_content` - Newsletters, promotions, automated notifications, bulk mail, login alerts, CFPs.
- `classifications/read_later` - Informational content worth reading but not urgent.
- `classifications/records` - Receipts, paid invoices, order confirmations, statements.
- `classifications/requires_action` - Directly addressed messages, approvals, unpaid invoices, security alerts, time-sensitive requests.
- `classifications/unsure` - Anything that does not fit cleanly elsewhere.

## Label behavior

- Labels are created automatically when first applied.
- An email is considered "already classified" if it has any label from this set.

## Customizing the taxonomy

To change labels:

1. Update `ALLOWED_LABELS` in `src/models/classified_email.py`.
2. Update guidance in `prompts/CLASSIFICATION_PROMPT.md` to match.
3. Adjust any downstream logic that depends on labels (for example, `src/main.py`).

Keep the taxonomy small; performance and accuracy degrade as label sets grow.
