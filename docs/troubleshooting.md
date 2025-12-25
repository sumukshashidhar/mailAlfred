# Troubleshooting

## Gmail OAuth errors

**"OAuth credentials not found"**
- Ensure `credentials.json` exists in the project root
- Confirm the OAuth client is a Desktop app

**Browser authorization never opens**
- Run from a local machine (not a remote server without a browser)
- Check firewall rules that block localhost callbacks

**Invalid or expired token**
- Delete `token.json` and re-run to re-authenticate

## Gmail API errors

**"Gmail API has not been used in project"**
- Enable the Gmail API in Google Cloud Console

**403 / insufficient permissions**
- Verify the OAuth consent screen is configured and your account is a test user
- Re-authenticate after changing scopes

## LLM errors

**Missing API key**
- Set `OPENAI_API_KEY` in `.env`
- Ensure the key has access to the selected model

**Rate limits / 429s**
- Lower `--concurrency`
- Use a faster model or a provider tier with higher limits

**Structured output parsing fails**
- Make sure the provider supports structured output
- Tighten instructions in `prompts/CLASSIFICATION_PROMPT.md`

## Classification behavior

**Emails are reprocessed**
- Only emails with existing classification labels are skipped
- Ensure labels exist and were successfully applied

**Labels not appearing**
- Confirm Gmail API `modify` scope is granted
- Check Gmail label list for `classifications/*`

## Advanced: seen-cache behavior

If you are using `GmailConnector` directly, it uses a disk cache at `.cache/gmail_seen` to stop iteration once a previously-seen email ID is found. Delete this directory if you want to iterate from the top again.
