#!/usr/bin/env bash
# ============================================================================
#  SchoolAutomaton — one-shot installer/deployer for a Linux server.
#
#  Just run it:   ./infra/scripts/deploy.sh
#
#  It will:
#    1. check (and optionally install) Docker Engine + the Compose v2 plugin
#    2. ask for settings (web port, public URL, admin login, API keys) — pressing
#       Enter keeps the current/sane default; APP_SECRET is generated for you
#    3. write .env (chmod 600), build the images, and start the stack
#    4. verify the backend is healthy and the web port responds
#
#  Re-run any time to change settings or update (data on the sa-data volume is kept).
#  Serve it publicly by pointing your Cloudflare tunnel at http://localhost:<port>.
# ============================================================================
set -euo pipefail
umask 077                    # files we create (.env, temp copies) are owner-only
cd "$(dirname "$0")/../.."   # repo root

# ---------- pretty output ----------
c_say()  { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
c_ok()   { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
c_warn() { printf '\033[1;33m  ! \033[0m%s\n' "$*" >&2; }
c_die()  { printf '\033[1;31m  ✗ %s\033[0m\n' "$*" >&2; exit 1; }
have()   { command -v "$1" >/dev/null 2>&1; }
is_tty() { [ -t 0 ] && [ -t 1 ]; }

[ -f docker-compose.yml ] && [ -f .env.example ] || c_die "Run this from the SchoolAutomaton repo (docker-compose.yml not found)."

# ---------- sudo / docker invocation ----------
SUDO=""
if [ "$(id -u)" -ne 0 ]; then have sudo && SUDO="sudo"; fi
DOCKER=(docker)
dc() { "${DOCKER[@]}" compose "$@"; }

# ---------- 1. runtime prerequisites ----------
ensure_docker() {
  if docker info >/dev/null 2>&1; then DOCKER=(docker); c_ok "Docker is installed and usable."; return; fi
  if [ -n "$SUDO" ] && $SUDO docker info >/dev/null 2>&1; then
    DOCKER=("$SUDO" docker); c_ok "Docker usable via sudo."; return
  fi
  c_warn "Docker is not installed (or not usable by this user)."
  if ! is_tty; then c_die "Install Docker first (https://get.docker.com), then re-run."; fi
  printf "Install Docker Engine now via the official get.docker.com script? [Y/n] "
  read -r ans || true; case "${ans:-Y}" in [Nn]*) c_die "Docker is required.";; esac
  [ "$(id -u)" -eq 0 ] || [ -n "$SUDO" ] || c_die "Need root or sudo to install Docker."
  c_say "Installing Docker Engine (this can take a minute)..."
  curl -fsSL https://get.docker.com | $SUDO sh
  $SUDO systemctl enable --now docker >/dev/null 2>&1 || true
  _user="${SUDO_USER:-${USER:-$(id -un)}}"
  [ "$(id -u)" -eq 0 ] || $SUDO usermod -aG docker "$_user" >/dev/null 2>&1 || true
  if docker info >/dev/null 2>&1; then DOCKER=(docker)
  elif [ -n "$SUDO" ] && $SUDO docker info >/dev/null 2>&1; then DOCKER=("$SUDO" docker)
  else c_die "Docker installed but not usable yet — log out/in (for the docker group) and re-run."; fi
  c_ok "Docker installed."
}
ensure_compose() {
  dc version >/dev/null 2>&1 || c_die "Docker Compose v2 plugin is missing. Install 'docker-compose-plugin' and re-run."
  c_ok "Docker Compose v2 available."
}
ensure_docker
ensure_compose

# ---------- 2. configure .env ----------
[ -f .env ] || { cp .env.example .env; c_ok "Created .env from template."; }
chmod 600 .env 2>/dev/null || true

cur() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2- || true; }
setkv() {  # setkv KEY VALUE  — in-place, order-preserving, value-safe (no escaping issues)
  local k="$1" v="$2" tmp; tmp="$(mktemp)"
  SA_V="$v" awk -v k="$k" '
    $0 ~ "^" k "=" && !d { print k "=" ENVIRON["SA_V"]; d=1; next }
    { print }
    END { if (!d) print k "=" ENVIRON["SA_V"] }
  ' .env > "$tmp" && mv "$tmp" .env
  chmod 600 .env 2>/dev/null || true
}
ask() {  # ask VAR "Prompt" "default"   (visible)
  local __v="$1" prompt="$2" def="${3:-}" ans
  if is_tty; then read -r -p "  $prompt${def:+ [$def]}: " ans || true; ans="${ans:-$def}"; else ans="$def"; fi
  printf -v "$__v" '%s' "$ans"
}
ask_secret() {  # ask_secret VAR "Prompt" "default"   (hidden; Enter keeps default)
  local __v="$1" prompt="$2" def="${3:-}" ans=""
  if is_tty; then
    read -rs -p "  $prompt${def:+ [keep current]}: " ans || true; echo
    ans="${ans:-$def}"
  else ans="$def"; fi
  printf -v "$__v" '%s' "$ans"
}

# APP_SECRET — generate if missing/weak/placeholder.
appsecret="$(cur APP_SECRET)"
if [ -z "$appsecret" ] || [ "$appsecret" = "change-me-please-a-long-random-string" ] || [ "${#appsecret}" -lt 32 ]; then
  appsecret="$(openssl rand -base64 48 2>/dev/null | tr -d '\n' || head -c 48 /dev/urandom | base64 | tr -d '\n=' )"
  setkv APP_SECRET "$appsecret"
  c_ok "Generated a strong APP_SECRET."
fi

# Compute sane defaults (treat template placeholders as empty).
def_port="$(cur SA_HTTP_PORT)";  def_port="${def_port:-8080}"
def_bind="$(cur SA_HTTP_BIND)";  def_bind="${def_bind:-127.0.0.1}"
def_url="$(cur SA_CORS_ORIGINS)"; case "$def_url" in ""|*localhost*) def_url="https://schoolautomaton.avercode.com";; esac
def_aun="$(cur ADMIN_USERNAME)"; def_aun="${def_aun:-admin}"
def_apw="$(cur ADMIN_PASSWORD)"; case "$def_apw" in change-me-too|admin) def_apw="";; esac
def_akey="$(cur ANTHROPIC_API_KEY)"; case "$def_akey" in sk-ant-...) def_akey="";; esac
def_rkey="$(cur REPLICATE_API_TOKEN)"; case "$def_rkey" in r8_...) def_rkey="";; esac

c_say "Settings (press Enter to keep the shown value):"
ask port "Web port your Cloudflare tunnel forwards to" "$def_port"
ask bind "Bind interface (127.0.0.1 = tunnel-only, 0.0.0.0 = also direct)" "$def_bind"
ask url  "Public URL" "$def_url"
ask aun  "Admin username" "$def_aun"

apw="$def_apw"
if is_tty; then
  while :; do
    ask_secret apw "Admin password (min 8 chars)" "$def_apw"
    case "$apw" in
      ""|admin|change-me-too) c_warn "Choose a real admin password (not blank/admin).";;
      ?|??|???|????|?????|??????|???????) c_warn "Use at least 8 characters.";;
      *) break;;
    esac
  done
else
  # Non-interactive: never silently deploy a weak/empty admin (the prod guard + tunnel exposure).
  case "$apw" in
    ""|admin|change-me-too) c_die "Set a strong ADMIN_PASSWORD in .env before a non-interactive deploy (cannot prompt).";;
  esac
fi

ask_secret akey "Anthropic API key (blank = skip; generation stays off)" "$def_akey"
ask_secret rkey "Replicate API token (blank = skip; illustrations stay off)" "$def_rkey"

setkv SA_HTTP_PORT "$port"
setkv SA_HTTP_BIND "$bind"
setkv SA_CORS_ORIGINS "$url"
setkv ADMIN_USERNAME "$aun"
setkv ADMIN_PASSWORD "$apw"
setkv ANTHROPIC_API_KEY "$akey"
setkv REPLICATE_API_TOKEN "$rkey"
setkv SA_ENV production   # reflect the real runtime in .env (compose also enforces this)
setkv SA_DEBUG false
c_ok "Wrote .env (chmod 600)."

# ---------- 3. build + run ----------
c_say "Building images (first build can take a few minutes)..."
dc build
c_say "Starting the stack..."
dc up -d

# ---------- 4. verify ----------
c_say "Verifying the backend is healthy..."
cid="$(dc ps -q backend || true)"
healthy=0
if [ -z "$cid" ]; then
  c_warn "Backend container not found — check: docker compose ps && docker compose logs backend"
else
  for ((i = 1; i <= 40; i++)); do
    status="$("${DOCKER[@]}" inspect -f '{{ if .State.Health }}{{ .State.Health.Status }}{{ else }}none{{ end }}' "$cid" 2>/dev/null || echo unknown)"
    if [ "$status" = healthy ]; then healthy=1; break; fi
    # No healthcheck defined? accept a running container.
    if [ "$status" = none ]; then
      if "${DOCKER[@]}" inspect -f '{{.State.Running}}' "$cid" 2>/dev/null | grep -q true; then healthy=1; break; fi
    fi
    if [ $((i % 5)) -eq 0 ]; then printf '  … still starting (%ss elapsed)\n' "$((i * 3))"; fi
    sleep 3
  done
fi
if [ "$healthy" = 1 ]; then c_ok "Backend is up."; else c_warn "Backend not healthy yet — check: docker compose logs backend"; fi

web_ok=0
if have curl; then
  if curl -fsS -o /dev/null --max-time 5 "http://127.0.0.1:${port}/" 2>/dev/null; then web_ok=1; fi
elif have wget; then
  if wget -q -O /dev/null "http://127.0.0.1:${port}/" 2>/dev/null; then web_ok=1; fi
fi
if [ "$web_ok" = 1 ]; then c_ok "Web app responds on 127.0.0.1:${port}."; else c_warn "Could not confirm the web port locally (it may still be fine via the tunnel)."; fi

# ---------- done ----------
pub="${url%%,*}"   # first origin if SA_CORS_ORIGINS holds a comma-separated list
cat <<EOF

$(printf '\033[1;32m✔ SchoolAutomaton is deployed.\033[0m')

  Local origin :  http://${bind}:${port}      <-- point your Cloudflare tunnel here
  Public URL   :  ${pub}
  Admin login  :  ${pub%/}/admin/login   (user: ${aun})

  Cloudflare tunnel ingress (match the port):
      hostname: schoolautomaton.avercode.com
      service:  http://localhost:${port}

  Logs:    docker compose logs -f
  Update:  ./infra/scripts/update.sh
EOF
[ -n "$akey" ] || c_warn "No Anthropic key set — lesson/quiz generation is disabled until you add ANTHROPIC_API_KEY (re-run this script)."
