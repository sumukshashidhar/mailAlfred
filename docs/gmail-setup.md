# Gmail Setup

Configure Gmail API access for mailAlfred.

## 1) Create or select a Google Cloud project

- Open Google Cloud Console
- Create a new project (or select an existing one)
- Go to APIs & Services -> Library
- Enable the Gmail API

## 2) Configure OAuth consent screen

If prompted:

- User type: External
- App name: mailAlfred
- Add your email as a test user

## 3) Create OAuth client credentials

- APIs & Services -> Credentials
- Create Credentials -> OAuth client ID
- Application type: Desktop app
- Download the JSON
- Save as `credentials.json` in the project root

## Scopes requested

mailAlfred requires:

- `https://www.googleapis.com/auth/gmail.readonly`
- `https://www.googleapis.com/auth/gmail.modify`

The modify scope is used to apply Gmail labels.

## Authorization flow

On first run:

1. A browser window opens for Google sign-in
2. Grant the requested permissions
3. A `token.json` file is created in the project root

Subsequent runs reuse `token.json` automatically.

## Revoking access

- Go to your Google Account security page
- Remove mailAlfred from third-party access
- Delete `token.json` locally if you want to re-authenticate
