#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ENV="${ROOT_DIR}/.env"
REFLECTION_ENV="${HOME}/Documents/root/resources/reflection/.scripts/.env"

if [[ -f "${PROJECT_ENV}" ]]; then
  set -a
  source "${PROJECT_ENV}"
  set +a
fi

# Accept either naming convention and normalize to TODOIST_API_KEY.
if [[ -z "${TODOIST_API_KEY:-}" && -n "${TODOIST_API_TOKEN:-}" ]]; then
  export TODOIST_API_KEY="${TODOIST_API_TOKEN}"
fi

if [[ -z "${TODOIST_API_KEY:-}" && -f "${REFLECTION_ENV}" ]]; then
  token_line="$(grep -E '^TODOIST_API_(KEY|TOKEN)=' "${REFLECTION_ENV}" | head -n 1 || true)"
  if [[ -n "${token_line}" ]]; then
    export TODOIST_API_KEY="${token_line#*=}"
  fi
fi

if [[ -z "${TODOIST_API_KEY:-}" ]]; then
  echo "Missing TODOIST_API_KEY. Add it to ${PROJECT_ENV} or ${REFLECTION_ENV}." >&2
  exit 1
fi

if ! command -v todoist-ai >/dev/null 2>&1; then
  echo "todoist-ai is not installed. Run: npm install -g @doist/todoist-ai" >&2
  exit 1
fi

exec todoist-ai
