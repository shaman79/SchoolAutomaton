#!/usr/bin/env bash
# SchoolAutomaton — update an existing deployment (Linux/macOS): pull, rebuild, restart, prune.
set -euo pipefail
cd "$(dirname "$0")/../.."

if [ -d .git ]; then
  echo "Pulling latest changes..."
  git pull --ff-only
fi

echo "Rebuilding images..."
docker compose build

echo "Recreating containers (data volume preserved)..."
docker compose up -d

docker image prune -f >/dev/null

PORT="8080"; [ -f .env ] && PORT="$(grep -E '^SA_HTTP_PORT=' .env | cut -d= -f2 | tr -d '[:space:]')"; PORT="${PORT:-8080}"
echo "Update complete. Local origin: http://127.0.0.1:${PORT} (served publicly via your Cloudflare tunnel)."
