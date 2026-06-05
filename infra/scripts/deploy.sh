#!/usr/bin/env bash
# SchoolAutomaton — deploy/build on a Linux server (Docker Compose).
#   First run:  creates .env, generates a strong APP_SECRET, then pauses for you to fill secrets.
#   Next runs:  builds images and (re)starts the stack.
# The app is published on 127.0.0.1:${SA_HTTP_PORT}; your existing Cloudflare tunnel on this host
# forwards schoolautomaton.avercode.com to that local port (see DEPLOY.md).
# Usage:  ./infra/scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/../.."

# ---- First run: scaffold .env with a real APP_SECRET, then stop so secrets get filled in. ----
if [ ! -f .env ]; then
  cp .env.example .env
  secret="$(openssl rand -base64 48 2>/dev/null | tr -d '\n' || python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"
  tmp="$(mktemp)"
  sed "s|^APP_SECRET=.*|APP_SECRET=${secret}|" .env > "$tmp" && mv "$tmp" .env
  cat <<'EOF'

Created .env with a freshly generated APP_SECRET.
Now edit .env and set at least:
  ADMIN_PASSWORD        (do NOT leave the placeholder)
  ANTHROPIC_API_KEY     (needed for lesson/quiz generation)
  REPLICATE_API_TOKEN   (needed for illustrations)
  SA_HTTP_PORT          (host port your Cloudflare tunnel forwards to, e.g. 8080)
  SA_CORS_ORIGINS       (https://schoolautomaton.avercode.com)

Then re-run:  ./infra/scripts/deploy.sh
EOF
  exit 0
fi

# ---- Load .env for our own use (port echo). ----
set -a; . ./.env; set +a
PORT="${SA_HTTP_PORT:-8080}"
BIND="${SA_HTTP_BIND:-127.0.0.1}"

echo "Building images..."
docker compose build
echo "Starting stack..."
docker compose up -d

echo
echo "SchoolAutomaton is up."
echo "  Local origin:   http://${BIND}:${PORT}      <-- point your Cloudflare tunnel here"
echo "  Public URL:     ${SA_CORS_ORIGINS:-<set SA_CORS_ORIGINS in .env>}"
echo "  Backend health: docker compose exec backend python -c \"import urllib.request;print(urllib.request.urlopen('http://localhost:8000/healthz').read())\""
echo "  Logs:           docker compose logs -f"
