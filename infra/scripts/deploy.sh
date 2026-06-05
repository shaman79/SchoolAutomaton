#!/usr/bin/env bash
# SchoolAutomaton — first-time / full deploy (Linux/macOS). Builds images and starts the stack.
set -euo pipefail
cd "$(dirname "$0")/../.."

if [ ! -f .env ]; then
  echo "No .env found — creating from .env.example. EDIT IT before going to production!"
  cp .env.example .env
fi

echo "Building images..."
docker compose build

echo "Starting stack..."
docker compose up -d

cat <<'EOF'

SchoolAutomaton is up:
  App:   http://localhost:8080
  Admin: http://localhost:8080/admin/login
EOF
