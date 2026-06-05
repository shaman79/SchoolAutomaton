#!/usr/bin/env bash
# SchoolAutomaton — update an existing deployment: pull, and ONLY if there are new commits,
# rebuild + restart (data on the sa-data volume is preserved). Safe to run on a schedule:
#   - no new commits  -> fast no-op (no rebuild, no restart)
#   - overlapping runs -> skipped via a lock
# Force a rebuild even with no changes:  ./infra/scripts/update.sh --force
set -euo pipefail
cd "$(dirname "$0")/../.."

FORCE=0
[ "${1:-}" = "--force" ] && FORCE=1

# Avoid overlapping runs (matters when scheduled every few minutes).
LOCK=".sa-update.lock"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$LOCK"
  if ! flock -n 9; then echo "[update] another run is in progress — skipping."; exit 0; fi
fi

before="none"; after="none"
if [ -d .git ]; then
  before="$(git rev-parse HEAD 2>/dev/null || echo none)"
  echo "[update] pulling latest changes..."
  git pull --ff-only
  after="$(git rev-parse HEAD 2>/dev/null || echo none)"
fi

if [ "$FORCE" -ne 1 ] && [ "$before" = "$after" ]; then
  echo "[update] already up to date ($after) — nothing to rebuild."
  exit 0
fi

echo "[update] changes detected ($before -> $after); rebuilding + restarting..."
docker compose build
docker compose up -d
docker image prune -f >/dev/null

PORT="8080"; [ -f .env ] && PORT="$(grep -E '^SA_HTTP_PORT=' .env | cut -d= -f2 | tr -d '[:space:]' || true)"; PORT="${PORT:-8080}"
echo "[update] complete. Local origin: http://127.0.0.1:${PORT} (served publicly via your Cloudflare tunnel)."
