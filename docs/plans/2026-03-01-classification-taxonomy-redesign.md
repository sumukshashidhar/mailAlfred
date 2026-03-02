# Classification Taxonomy Redesign

**Date:** 2026-03-01
**Status:** Approved

## Problem

Analysis of 500 recent emails revealed the current 8-label taxonomy is poorly calibrated:

- `bulk_content` is a dumping ground absorbing 60% of all emails (301/500), hiding marketing, academic, and quality content
- `requires_action` is too broad — 21% of its emails are mislabeled service notifications (Prime Intellect "Action Failed" x5, Delta outage notices)
- `marketing` (2.6%) and `records` (1.8%) are severely underused despite many qualifying emails existing
- 49 emails (9.8%) are completely unclassified (Campuswire, LinkedIn, Google security alerts, paper decisions)
- Same sender gets different classifications: illinois.edu spans 5 categories, Prime Intellect spans 3

Natural clustering of the 500 emails identified 27 distinct email types, but only ~30 emails out of 500 genuinely need immediate human attention. Over 50% is auto-archivable.

## Design: 12-Label Taxonomy

Labels map to **triage behavior** (what you do next), not email topic.

### Tier 1 — Must read now

**`classifications/respond`**
A real person is waiting for your reply. Family, colleagues, immigration lawyers, active recruiter threads, advisor/student requests. Human-written tone, direct address.

**`classifications/urgent`**
Time-critical automated alerts: failed payments, security incidents (GitGuardian), credential leaks, hard deadlines within 48 hours, account locks, unpaid invoices.

### Tier 2 — Review today

**`classifications/action`**
Administrative tasks needing attention but not time-pressured: permissions reviews, settings changes, forms to complete, volunteer signups with future deadlines, Google Cloud billing updates.

**`classifications/opportunities`**
Mass-mailed opportunities: grants, CFPs, fellowships, job postings, GLG consulting requests, conference reviewer invitations, career events. Not personally addressed; not direct obligations.

**`classifications/academic`**
University and research communications: department mailing lists, seminar announcements, coursework notifications (Campuswire/Canvas), grad student events, NLP seminar threads, department newsletters, GradLinks, Siebel School weekly news.

### Tier 3 — Batch review

**`classifications/notifications`**
Automated account/service updates: login alerts, credit score changes, service status, calendar updates and cancellations, infrastructure success/failure reports, LinkedIn message notifications, app install confirmations. If it requires payment or a decision, use `urgent` or `action` instead.

**`classifications/records`**
Financial records to archive: paid receipts, completed order confirmations, payment-received notices, credit card statements, billing statements. Must be *completed* transactions. Unpaid invoices or failed payments go to `urgent`.

**`classifications/read_later`**
Quality content worth reading when time permits: Substack newsletters, tech blog posts (Pragmatic Engineer), research-adjacent articles, PyTorch/framework newsletters, The Information briefings, developer tool deep dives. Not bulk noise — content the user has opted into and values.

### Tier 4 — Lowest priority

**`classifications/marketing`**
Commercial promotions and sales: discounts, product launches, loyalty program perks, reward challenges, upgrade pushes. Company-wide campaigns, not account-specific updates.

**`classifications/bulk`**
True noise with no triage value: PPS end-user digests, USPS daily mail scans, social platform notification digests, mailing list noise that doesn't fit academic, automated monitoring success confirmations, cold outbound, mail-merge greetings.

**`classifications/unsure`**
Fallback for emails that don't fit any category. Consider current date/time during classification.

## Changes Required

### 1. Label definitions (`src/models/classified_email.py`)

Replace `ALLOWED_LABELS` with the new 12-label set. Update `LABEL_ALIASES` to handle the old label names as aliases for migration.

Old labels to alias:
- `classifications/requires_action` → keep as alias, map to `classifications/respond` (safest default)
- `classifications/bulk_content` → keep as alias, map to `classifications/bulk`

### 2. Classification prompt (`prompts/CLASSIFICATION_PROMPT.j2`)

Rewrite with:
- 12 labels organized by tier (sieve metaphor preserved)
- Clearer boundary definitions informed by the misclassification patterns found
- Explicit guidance against keyword traps ("Action" in subject does not mean requires action)
- Emphasis on distinguishing "awareness" items from "action" items
- Examples drawn from real emails in the dataset

### 3. Gmail connector (`src/connectors/gmail_connector.py`)

The `is_classified` check uses label IDs. New labels will get new IDs on first creation. The existing logic of checking for ANY classification label should work, but the label creation code needs to handle the new names.

### 4. No structural code changes needed

The pipeline (scan → classify → label) is unchanged. Only the label set and prompt content change. The Pydantic validation, inference code, and batch processing logic are all label-agnostic.

## Data Evidence

Based on analysis of 500 real emails:

| New Label | Expected emails (of 500) | Source |
|---|---|---|
| respond | ~10 | Split from requires_action (personal replies) |
| urgent | ~8 | Split from requires_action (time-critical alerts) |
| action | ~6 | Split from requires_action (admin tasks) |
| opportunities | ~45 | Current opportunities + GLG + reviewer invites |
| academic | ~89 | From bulk_content (77 UIUC) + unclassified Campuswire (20) |
| notifications | ~50 | Current notifications + Prime Intellect + LinkedIn + calendar |
| records | ~20 | Current records + statements from notifications |
| read_later | ~40 | Current read_later + Substacks from bulk |
| marketing | ~43 | Current marketing + Southwest/AmEx/Starbucks from bulk |
| bulk | ~180 | Residual from bulk_content after splits |
| unsure | ~0 | Fallback |
| unclassified | ~9 | Remaining edge cases |

The `respond` bucket drops from 38 noisy emails to ~10 genuine "someone needs a reply" items.
