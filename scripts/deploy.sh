#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
SMOKE_RUN="${SMOKE_RUN:-0}"
UV_BIN="${UV_BIN:-}"

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[deploy] missing required command: $1" >&2
    exit 1
  fi
}

require_cmd git
require_cmd systemctl
require_cmd flock

if [ -z "$UV_BIN" ]; then
  if command -v uv >/dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
  elif [ -x /root/.local/bin/uv ]; then
    UV_BIN="/root/.local/bin/uv"
  else
    echo "[deploy] missing required command: uv (set UV_BIN or install uv)" >&2
    exit 1
  fi
fi

cd "$APP_DIR"

exec 9>/tmp/mailalfred-deploy.lock
if ! flock -n 9; then
  echo "[deploy] another deployment is already running" >&2
  exit 1
fi

echo "[deploy] app_dir=$APP_DIR"

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "[deploy] working tree is dirty; refusing to deploy" >&2
  git status --short >&2
  exit 1
fi

current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [ "$current_branch" != "$BRANCH" ]; then
  echo "[deploy] switching branch: $current_branch -> $BRANCH"
  git checkout "$BRANCH"
fi

echo "[deploy] fetching $REMOTE/$BRANCH"
git fetch --prune "$REMOTE"

echo "[deploy] applying fast-forward update"
git pull --ff-only "$REMOTE" "$BRANCH"

echo "[deploy] syncing dependencies with uv lock"
"$UV_BIN" sync --frozen

echo "[deploy] reloading systemd units"
systemctl daemon-reload

if [ "$SMOKE_RUN" = "1" ]; then
  echo "[deploy] smoke run enabled; starting mailalfred.service once"
  systemctl start mailalfred.service
fi

timer_enabled="$(systemctl is-enabled mailalfred.timer 2>/dev/null || true)"
timer_active="$(systemctl is-active mailalfred.timer 2>/dev/null || true)"
echo "[deploy] mailalfred.timer enabled=$timer_enabled active=$timer_active"
echo "[deploy] done"
