# CI/CD

This project includes GitHub Actions workflows for CI and server deploy:

- CI workflow: `.github/workflows/ci.yml`
- Deploy workflow: `.github/workflows/deploy.yml`
- Server deploy script: `scripts/deploy.sh`

## CI behavior

On pull requests and pushes to `main`, CI will:

1. Install dependencies with `uv sync --frozen`
2. Run Python sanity checks:
   - `python -m compileall -q src`
   - `python -m src.main --help`
3. Run `pytest` only if a `tests/` (or `test/`) directory exists

## Deploy behavior

On pushes to `main` (or manual dispatch), deploy will SSH into the server and run:

```bash
cd /root/mail_processing/mailAlfred
SMOKE_RUN=<0-or-1> ./scripts/deploy.sh
```

`scripts/deploy.sh` is intentionally conservative:

- Fails if the working tree is dirty
- Fetches and updates with `git pull --ff-only`
- Runs `uv sync --frozen`
- Runs `systemctl daemon-reload`
- Optionally runs one smoke execution (`mailalfred.service`) when `SMOKE_RUN=1`
- Does **not** enable/disable/start/stop `mailalfred.timer`

## GitHub setup

### 1) Protect `main`

In GitHub branch protection for `main`:

- Require pull request before merging
- Require status checks to pass (include `CI / checks`)

### 2) Create environment

Create environment `production` and add required reviewers for deploy approvals.

### 3) Add repository secrets

Add these secrets in GitHub:

- `DEPLOY_HOST`: `178.156.217.110` (or DNS name)
- `DEPLOY_PORT`: `22`
- `DEPLOY_USER`: deployment SSH user (for current server setup, `root`)
- `DEPLOY_SSH_KEY`: private key for that user
- `DEPLOY_KNOWN_HOSTS`: pinned host key line(s), for example:
  `ssh-keyscan -H 178.156.217.110`

## Manual deploy

From GitHub Actions:

1. Open workflow `Deploy`
2. Click `Run workflow`
3. Choose `smoke_run`:
   - `false`: deploy only
   - `true`: deploy + run `mailalfred.service` once immediately
