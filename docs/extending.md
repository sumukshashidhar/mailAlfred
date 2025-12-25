# Extending mailAlfred

This project is designed to be modified. The default pipeline is small and explicit, so you can replace pieces without touching everything else.

## Connector interface

A connector is responsible for:

- Fetching message metadata and body content
- Normalizing into the `Email` Pydantic model
- Applying labels or other actions

`GmailConnector` is the reference implementation. If you build a new connector, keep the same high-level interface:

- A generator or iterator that yields `Email`
- A `classify_email(email_id, label_name)` method or equivalent

## Classifier contract

Classification expects:

- Input: prompt string containing an email context
- Output: a Pydantic model that validates the label

`ClassifiedEmail` enforces the label set. If you add fields (priority score, confidence, etc), extend the model and update the prompt instructions accordingly.

## Prompt template

Prompts are loaded from `prompts/CLASSIFICATION_PROMPT.md` and combined with email context in `src/utils/prompts.py`.

Common extensions:

- Add user-specific rules
- Add examples for few-shot learning
- Add metadata signals (thread length, sender domain, mailbox label)

## Model backends

`src/utils/inference.py` uses the OpenAI SDK with structured output parsing. To use a different backend:

1. Keep the same coroutine signature for `do_structured_output_inference`
2. Return an instance of the schema Pydantic model
3. Preserve retry behavior where possible

## Post-classification actions

After a label is produced, `src/main.py` applies the Gmail label. You can extend this step to:

- Archive or star messages
- Forward to another address
- Emit metrics to an external system
- Write results to a database for audits

Keep the pipeline stateless unless you need persistence.
