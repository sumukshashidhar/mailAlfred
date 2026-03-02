# Labels

mailAlfred uses a 12-label taxonomy organized by triage behavior. Labels are stored as Gmail labels under the `classifications/` namespace.

## Taxonomy

### Tier 1 — Must read now
- `classifications/respond` - A real person is waiting for your reply (family, colleagues, lawyers, advisors).
- `classifications/urgent` - Time-critical: failed payments, security incidents, credential leaks, hard deadlines <48h.

### Tier 2 — Review today
- `classifications/action` - Admin tasks needing attention but not time-pressured (permissions, forms, settings).
- `classifications/opportunities` - Mass-mailed opportunities: grants, CFPs, fellowships, jobs, GLG consulting.
- `classifications/academic` - University/research: department lists, seminars, coursework (Campuswire/Canvas), events.

### Tier 3 — Batch review
- `classifications/notifications` - Automated account/service updates, login alerts, credit score changes, infra alerts.
- `classifications/records` - Completed financial records: paid receipts, statements, order confirmations.
- `classifications/read_later` - Quality newsletters, tech blogs, research articles worth reading later.

### Tier 4 — Lowest priority
- `classifications/marketing` - Commercial promotions, sales, loyalty programs, product launches.
- `classifications/bulk` - True noise: PPS digests, USPS scans, cold outbound, mail-merge, monitoring success.

### Fallback
- `classifications/unsure` - Anything that does not fit cleanly elsewhere.

## Label behavior

- Labels are created automatically when first applied.
- An email is considered "already classified" if it has any label from this set.
- Old labels (`requires_action`, `bulk_content`) are aliased to new names for backwards compatibility.

## Customizing the taxonomy

To change labels:

1. Update `ALLOWED_LABELS` in `src/models/classified_email.py`.
2. Update guidance in `prompts/CLASSIFICATION_PROMPT.j2` to match.
3. Adjust `LABEL_COLORS` in `src/main.py` for display.
