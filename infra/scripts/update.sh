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
echo "Update complete. App: http://localhost:8080"
