# Classification Taxonomy Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the 8-label classification taxonomy with a 12-label taxonomy that splits `requires_action` into urgency tiers and separates academic/bulk/marketing emails properly.

**Architecture:** Only the label definitions, classification prompt, and display logic change. The pipeline (scan → classify → label) is untouched. No new dependencies.

**Tech Stack:** Python 3.12, Pydantic, OpenAI structured output, Gmail API labels.

**Design doc:** `docs/plans/2026-03-01-classification-taxonomy-redesign.md`

---

### Task 1: Update label definitions in classified_email.py

**Files:**
- Modify: `src/models/classified_email.py`

**Step 1: Replace ALLOWED_LABELS with the new 12-label set**

Replace the entire `ALLOWED_LABELS` set with:

```python
ALLOWED_LABELS = {
    "classifications/respond",
    "classifications/urgent",
    "classifications/action",
    "classifications/opportunities",
    "classifications/academic",
    "classifications/notifications",
    "classifications/records",
    "classifications/read_later",
    "classifications/marketing",
    "classifications/bulk",
    "classifications/unsure",
}
```

**Step 2: Update LABEL_ALIASES for backwards compatibility**

Replace the `LABEL_ALIASES` dict with:

```python
LABEL_ALIASES = {
    # Old labels → new canonical names
    "classifications/requires_action": "classifications/respond",
    "classifications/bulk_content": "classifications/bulk",
    # Typo aliases (keep existing)
    "classification/notifications": "classifications/notifications",
    "classfications/notifications": "classifications/notifications",
    "classification/marketing": "classifications/marketing",
    "classfications/marketing": "classifications/marketing",
    # New typo aliases
    "classification/respond": "classifications/respond",
    "classification/urgent": "classifications/urgent",
    "classification/action": "classifications/action",
    "classification/academic": "classifications/academic",
    "classification/bulk": "classifications/bulk",
}
```

**Step 3: Verify — run Python import check**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -c "from src.models.classified_email import ALLOWED_LABELS, ClassifiedEmail; print(sorted(ALLOWED_LABELS)); print(ClassifiedEmail(label='classifications/respond')); print(ClassifiedEmail(label='classifications/requires_action'))"`

Expected: Prints the 11 labels (unsure included), a ClassifiedEmail with label `classifications/respond`, and the alias mapping `requires_action` → `respond`.

**Step 4: Commit**

```bash
git add src/models/classified_email.py
git commit -m "feat: update label taxonomy from 8 to 12 labels

Split requires_action into respond/urgent/action.
Rename bulk_content to bulk.
Add academic label.
Add backwards-compatible aliases for old label names."
```

---

### Task 2: Rewrite the classification prompt

**Files:**
- Modify: `prompts/CLASSIFICATION_PROMPT.j2`

**Step 1: Replace the entire prompt file**

Write the new prompt. Key design decisions informed by the data analysis:
- Preserve the sieve metaphor (lowest to highest priority)
- Add explicit anti-patterns for misclassifications seen in data (Prime Intellect "Action Failed", keyword traps)
- Include boundary clarifications for the most confused pairs (notifications vs records, marketing vs bulk, respond vs action)
- Reference the user's real context (800-900 emails/day, PhD student, UIUC)

New prompt content:

```markdown
You are an email classifier. Your job is to categorize emails into exactly one of the labels below based on what the user should DO with this email, not what it is about.

CONTEXT: The user is a PhD student who receives 800-900 emails daily. They need to focus on genuine obligations. Reducing cognitive load from low-value emails directly enables their research impact.

Here are the labels, sorted from lowest priority to highest. Think of this like a sieve — start from the bottom and only escalate when the email genuinely requires more attention.

## TIER 4 — Lowest priority

- `classifications/bulk`: True noise with no triage value. PPS/IT security digests, USPS daily mail scans, social platform notification digests (LinkedIn "X messaged you"), mailing list noise that doesn't fit academic, automated monitoring SUCCESS confirmations (backup completed, server healthy), cold outbound, mail-merge greetings, generic mass content. If it is a newsletter the user subscribed to and would want to read, prefer `read_later`. If it is a promotional campaign, prefer `marketing`.

- `classifications/marketing`: Commercial promotions and sales campaigns. Discounts, product launches, loyalty program perks (Bilt Rent Day, credit card rewards), upgrade pushes, seasonal sales (Southwest "$59 sale!"), app feature announcements, webinar invitations from vendors. If it is account-specific and operational (status alert, credit score change), prefer `notifications`. If it is a job/grant/fellowship announcement, prefer `opportunities`.

## TIER 3 — Batch review

- `classifications/read_later`: Quality content worth reading when time permits. Substack newsletters, tech blog deep dives (Pragmatic Engineer, a16z), research-adjacent articles, framework release notes (PyTorch, LiteLLM), The Information briefings, developer tool changelogs. This is content the user chose to subscribe to and values. NOT bulk noise — the user would be upset if this was auto-archived.

- `classifications/records`: Financial records to keep for archival. Paid receipts, completed order confirmations, "payment received" notices, credit card statements ("Your statement is ready"), billing statements, equity statements. CRITICAL: the transaction must be COMPLETED/PAID. Unpaid invoices, failed payments, or outstanding bills go to `urgent` instead.

- `classifications/notifications`: Automated account or service updates that are informational. Login alerts, credit score changes, service status updates, subscription reminders, platform notices, calendar event updates/cancellations, app install confirmations, infrastructure alerts (both success AND failure — e.g., "Environment Action Failed" from compute platforms, CI/CD run failures, disk usage reports). IMPORTANT: the word "Action" in a subject line does NOT mean the email requires action — "Environment Action Failed" is a system notification, not a request. If it requires a decision, payment, or reply, escalate to `action` or `urgent`.

## TIER 2 — Review today

- `classifications/academic`: University and research communications. Department mailing lists (announce@, corporate@, cs-speakerseries@), seminar and colloquium announcements, coursework notifications (Campuswire/Canvas digests, homework releases), grad student events, NLP/vision/robotics seminar threads and replies, department newsletters (GradLinks, Siebel School Weekly), engineering college events, campus recreation. If the email is a grant/fellowship/job announcement, prefer `opportunities`. If a specific person is directly asking the user to do something, prefer `respond` or `action`.

- `classifications/opportunities`: Mass-mailed opportunities that may be valuable. Grants, CFPs, fellowships, job or funding calls, conference announcements, scholarship deadlines, GLG consulting requests, reviewer invitations, career events, recruiting event invitations. These are broadcast, not personally addressed. If the sender is explicitly asking for a personal response or it is a warm intro, use `respond`.

- `classifications/action`: Administrative tasks needing attention but NOT time-pressured. GitHub permission requests, Google Workspace settings reviews, Cloud billing update notices, forms to complete, volunteer signups with future deadlines, configuration changes. These are "do this sometime this week" items. If the deadline is within 48 hours or the consequence of ignoring is severe, use `urgent`. If a real person is waiting for a reply, use `respond`.

## TIER 1 — Must read now

- `classifications/urgent`: Time-critical alerts where delay has consequences. Failed payments ("payment was unsuccessful"), security incidents (GitGuardian secret detection, account locks), credential leaks, unpaid invoices, overdue bills, hard deadlines within 48 hours, trade-in device return warnings. These are automated but ignoring them causes real damage. If a human is personally waiting for a reply, use `respond` instead.

- `classifications/respond`: A real person is directly waiting for Sumuk's reply. Family emails, immigration lawyer correspondence, active recruiter conversation threads (not initial cold outreach), advisor/student requests addressed to Sumuk personally, forwarded items with a request from the forwarder, direct personalized messages with human-written tone that reference ongoing work. BE VERY CAREFUL: cleverly worded outbound/sales emails that mimic personal tone do NOT belong here. If it is mass-mailed or automated, it is NOT respond.

## FALLBACK

- `classifications/unsure`: If it fits none of the above, classify here. Consider the current date and time during classification.

## KEY DECISION BOUNDARIES

1. "Action" in the subject does NOT mean requires action. "Environment Action Failed" is a notification.
2. Statements ("Your statement is ready") are records, not notifications.
3. Southwest Airlines sales emails are marketing, not bulk.
4. Substack newsletters are read_later, not bulk.
5. Campuswire/Canvas course digests are academic, not bulk.
6. Credit score changes are notifications, not records.
7. Calendar invitation updates/cancellations are notifications. New invitations needing RSVP are action.
8. LinkedIn "X messaged you" are bulk (the message is on LinkedIn, not in the email).
9. GLG consulting requests are opportunities (paid expert network), not marketing.
10. Conference paper decisions (ICLR, COLM) are opportunities if informational, respond if reviewer action needed.
```

**Step 2: Verify the prompt loads**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -c "from src.utils.prompts import _read_prompt_from_file; p = _read_prompt_from_file(); print(f'Prompt length: {len(p)} chars'); assert 'classifications/respond' in p; assert 'classifications/academic' in p; print('OK')"`

Expected: Prints prompt length and "OK".

**Step 3: Commit**

```bash
git add prompts/CLASSIFICATION_PROMPT.j2
git commit -m "feat: rewrite classification prompt for 12-label taxonomy

Organized by triage tiers (4 levels from bulk to respond).
Added explicit anti-patterns from data analysis (keyword traps, boundary clarifications).
10 key decision boundaries documented to reduce misclassification."
```

---

### Task 3: Update LABEL_COLORS and display logic in main.py

**Files:**
- Modify: `src/main.py`

**Step 1: Replace LABEL_COLORS dict**

Replace the `LABEL_COLORS` dict (around line 42) with:

```python
LABEL_COLORS = {
    "classifications/respond": "bold red",
    "classifications/urgent": "bold yellow",
    "classifications/action": "yellow",
    "classifications/opportunities": "green",
    "classifications/academic": "bright_cyan",
    "classifications/notifications": "blue",
    "classifications/records": "bright_black",
    "classifications/read_later": "cyan",
    "classifications/marketing": "dim",
    "classifications/bulk": "dim",
    "classifications/unsure": "magenta",
    "errors": "red",
}
```

**Step 2: Update the verbose display filter**

In the `process_emails` function, find the line (around line 259):

```python
if verbose or label == "classifications/requires_action":
```

Replace with:

```python
if verbose or label in ("classifications/respond", "classifications/urgent"):
```

This shows respond and urgent emails by default (not just in verbose mode), since those are the two highest-priority tiers.

**Step 3: Verify the import still works**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -c "from src.main import LABEL_COLORS, ALLOWED_LABELS; print(f'{len(LABEL_COLORS)} colors, {len(ALLOWED_LABELS)} labels'); assert 'classifications/respond' in LABEL_COLORS"`

Expected: Prints "12 colors, 11 labels" and no assertion error.

**Step 4: Commit**

```bash
git add src/main.py
git commit -m "feat: update display colors and default visibility for new labels

respond and urgent emails shown by default (replaces requires_action).
Color scheme: respond=bold red, urgent=bold yellow, academic=bright cyan."
```

---

### Task 4: Update docs/labels.md

**Files:**
- Modify: `docs/labels.md`

**Step 1: Replace the taxonomy section**

Replace the entire file content with updated documentation reflecting the new 12-label taxonomy, organized by tier.

```markdown
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
```

**Step 2: Commit**

```bash
git add docs/labels.md
git commit -m "docs: update labels.md for 12-label taxonomy"
```

---

### Task 5: Smoke test with dry run

**Files:** None (runtime verification only)

**Step 1: Run mailAlfred in dry-run mode on a small sample**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m src.main --dry-run -n 10 -v`

Expected: Should classify 10 emails using the new labels. Check that:
- No errors
- Labels are from the new set (respond, urgent, action, academic, etc.)
- No emails get the old labels (requires_action, bulk_content)

**Step 2: Verify label distribution looks reasonable**

Manually check the 10 results. At least some should be academic, notifications, or bulk rather than everything falling into one bucket.

**Step 3: If any issues, fix and re-run**

Common issues:
- Pydantic validation error: check ALLOWED_LABELS matches what the LLM returns
- LLM returns old label names: check that LABEL_ALIASES handles them

**Step 4: Commit any fixes if needed**

---

### Task 6: Run a larger dry-run validation

**Files:** None (runtime verification only)

**Step 1: Run on 50 emails in dry-run + verbose mode**

Run: `cd /Users/sumukshashidhar/Documents/root/projects/mailAlfred && uv run python -m src.main --dry-run -n 50 -v`

Expected: Classify 50 emails. The summary table should show a distribution across multiple labels, not 60% in one bucket.

**Step 2: Check for the key improvements from the data analysis**

Verify:
- Southwest/Starbucks/AmEx emails → `marketing` (not bulk)
- Campuswire/GradLinks emails → `academic` (not bulk or unclassified)
- Substack newsletters → `read_later` (not bulk)
- Prime Intellect "Action Failed" → `notifications` (not respond/urgent)
- Statements → `records` (not notifications)
- Personal emails → `respond`
- Failed payments → `urgent`

**Step 3: Final commit**

```bash
git add -A
git commit -m "feat: complete taxonomy redesign from 8 to 12 labels

Data-driven redesign based on analysis of 500 real emails.
Key changes:
- Split requires_action into respond/urgent/action
- New academic label for university/research emails
- Renamed bulk_content to bulk (narrower scope)
- Rewritten prompt with explicit boundary rules
- Backwards-compatible aliases for old label names"
```
