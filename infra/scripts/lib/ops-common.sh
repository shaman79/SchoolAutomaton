# shellcheck shell=bash
# Shared helpers for update.sh, deploy.sh, backup.sh and restore.sh.
# Source it from the repo root:  . infra/scripts/lib/ops-common.sh
#
# Settings are read from the environment first, then from .env (see .env.example):
#   SA_HTTP_PORT / SA_HTTP_BIND     where nginx listens (health checks go through it)
#   SA_ALERT_WEBHOOK_URL            optional; failures are POSTed there as plain text (ntfy.sh style)
#   SA_ALERT_FORMAT                 text (default) | slack | discord  (the latter two send JSON)
#   SA_DEPLOY_MAX_WAIT_S            max wait for running lesson generations before a restart (600)
#   SA_DEPLOY_HEALTH_TIMEOUT_S      how long a new release gets to become healthy (120)
#   SA_BACKUP_DIR, SA_BACKUP_KEEP_DAILY, SA_BACKUP_KEEP_WEEKLY   see backup.sh

# shellcheck disable=SC2034  # used by the sourcing scripts
SA_STATE_DIR=".sa-deploy"     # deployed-commit, bad-commit, alert de-dup stamps (gitignored)
# shellcheck disable=SC2034
SA_LOCK_FILE=".sa-update.lock" # ONE lock for deploys, updates, backups and restores
# shellcheck disable=SC2034
SA_LOG_DIR="logs"             # update.log, backup.log (gitignored, size-rotated)
# Compose services and the image each one is tagged as (must match `image:` in docker-compose.yml).
SA_SERVICES=(backend frontend)
sa_image_of() { echo "schoolautomaton-$1"; }

if ! declare -p DOCKER >/dev/null 2>&1; then DOCKER=(docker); fi
sa_docker() { "${DOCKER[@]}" "$@"; }
sa_dc() { "${DOCKER[@]}" compose "$@"; }

SA_LOG_TAG="${SA_LOG_TAG:-ops}"
sa_log() { printf '%s [%s] %s\n' "$(date '+%F %T')" "$SA_LOG_TAG" "$*"; }

# sa_rotate_log FILE [MAX_BYTES] [KEEP] — size-based rotation (FILE.1 … FILE.KEEP).
sa_rotate_log() {
  local f="$1" max="${2:-1048576}" keep="${3:-5}" size i
  [ -f "$f" ] || return 0
  size=$(wc -c < "$f" 2>/dev/null || echo 0)
  [ "$size" -ge "$max" ] || return 0
  for ((i = keep - 1; i >= 1; i--)); do [ -f "$f.$i" ] && mv -f "$f.$i" "$f.$((i + 1))"; done
  mv -f "$f" "$f.1"
}

# sa_env KEY [DEFAULT] — environment wins, then .env (first match, dotenv-style: optional quotes,
# trailing ` # comment` stripped), then DEFAULT.
sa_env() {
  local key="$1" def="${2:-}" val=""
  if [ -n "${!key:-}" ]; then printf '%s' "${!key}"; return 0; fi
  if [ -f .env ]; then
    val="$(grep -E "^[[:space:]]*(export[[:space:]]+)?${key}=" .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' || true)"
    case "$val" in
      \"*) val="${val#\"}"; val="${val%%\"*}" ;;
      \'*) val="${val#\'}"; val="${val%%\'*}" ;;
      *)   val="$(printf '%s' "$val" | sed -E 's/[[:space:]]+#.*$//; s/^[[:space:]]+//; s/[[:space:]]+$//')" ;;
    esac
  fi
  printf '%s' "${val:-$def}"
}

# Base URL of nginx as reachable from this host.
sa_base_url() {
  local bind port
  bind="$(sa_env SA_HTTP_BIND 127.0.0.1)"; port="$(sa_env SA_HTTP_PORT 8080)"
  case "$bind" in ""|0.0.0.0|"*"|"::"|"[::]") bind=127.0.0.1 ;; esac
  printf 'http://%s:%s' "$bind" "$port"
}

# ---------------------------------------------------------------- alerts
_sa_json_escape() {
  local s="$1"
  s="${s//\\/\\\\}"; s="${s//\"/\\\"}"; s="${s//$'\n'/\\n}"; s="${s//$'\r'/}"; s="${s//$'\t'/\\t}"
  printf '%s' "$s"
}

# sa_alert KEY MESSAGE [PRIORITY] — log + POST to SA_ALERT_WEBHOOK_URL (if set). The same KEY+MESSAGE
# is sent at most once per SA_ALERT_REPEAT_S (default 6 h). Never fails the caller.
sa_alert() {
  local key="$1" msg="$2" prio="${3:-high}" url fmt stamp now last body
  msg="SchoolAutomaton @ $(uname -n): $msg"
  sa_log "ALERT: $msg"
  url="$(sa_env SA_ALERT_WEBHOOK_URL)"
  [ -n "$url" ] || { sa_log "(no SA_ALERT_WEBHOOK_URL set — alert only logged)"; return 0; }
  mkdir -p "$SA_STATE_DIR" 2>/dev/null || true
  stamp="$SA_STATE_DIR/alert-${key//[^A-Za-z0-9_.-]/_}"
  now=$(date +%s)
  if [ -f "$stamp" ] && [ "$(tail -n +2 "$stamp")" = "$msg" ]; then
    last=$(head -1 "$stamp")
    if [ $((now - ${last:-0})) -lt "$(sa_env SA_ALERT_REPEAT_S 21600)" ]; then
      sa_log "(same alert sent $(( (now - last) / 60 )) min ago — not repeating)"; return 0
    fi
  fi
  fmt="$(sa_env SA_ALERT_FORMAT text)"
  case "$fmt" in
    slack)   body="{\"text\":\"$(_sa_json_escape "$msg")\"}" ;;
    discord) body="{\"content\":\"$(_sa_json_escape "$msg")\"}" ;;
    *)       body="$msg" ;;
  esac
  if [ "$fmt" = slack ] || [ "$fmt" = discord ]; then
    curl -fsS -m 15 --retry 2 -o /dev/null -H 'Content-Type: application/json' --data-binary "$body" "$url" 2>&1 \
      || { sa_log "WARNING: could not deliver alert to webhook"; return 0; }
  else
    # Plain text body; Title/Priority/Tags are ntfy headers (ignored by other receivers).
    curl -fsS -m 15 --retry 2 -o /dev/null -H 'Content-Type: text/plain; charset=utf-8' \
      -H 'Title: SchoolAutomaton' -H "Priority: $prio" -H 'Tags: warning' --data-binary "$body" "$url" 2>&1 \
      || { sa_log "WARNING: could not deliver alert to webhook"; return 0; }
  fi
  printf '%s\n%s\n' "$now" "$msg" > "$stamp" 2>/dev/null || true
  return 0
}

# ---------------------------------------------------------------- health
# Health contract: GET /api/v1/health -> 200 {"status":"ok","db":"ok","active_generations":N},
# 503 when the DB is unreachable. Checked THROUGH nginx, so nginx -> backend is covered too.
SA_LAST_HEALTH=""

_sa_get() {  # _sa_get URL -> prints body, then the HTTP status on the last line ("000" if unreachable)
  curl -sS -m 5 -w '\n%{http_code}' "$1" 2>/dev/null || printf '\n000'
}

sa_api_healthy() {
  local out code body
  out="$(_sa_get "$(sa_base_url)/api/v1/health")"
  code="${out##*$'\n'}"; body="${out%$'\n'*}"
  SA_LAST_HEALTH="api=$code $(printf '%s' "$body" | tr -d '\n' | cut -c1-160)"
  if [ "$code" = 200 ] && printf '%s' "$body" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"'; then
    return 0
  fi
  # Transitional: a backend from before /api/v1/health existed answers FastAPI's JSON 404. That still
  # proves nginx -> backend works (a dead backend gives nginx's 502), so accept it as liveness.
  if [ "$code" = 404 ] && printf '%s' "$body" | grep -q '"detail"'; then
    SA_LAST_HEALTH="$SA_LAST_HEALTH (legacy backend without /api/v1/health: accepted FastAPI 404 as liveness)"
    return 0
  fi
  return 1
}

# The SPA shell loads and the first JS bundle it references is served.
sa_spa_ok() {
  local base html asset
  base="$(sa_base_url)"
  html="$(curl -fsS -m 5 "$base/" 2>/dev/null)" || { SA_LAST_HEALTH="$SA_LAST_HEALTH; spa=unreachable"; return 1; }
  asset="$(printf '%s' "$html" | grep -oE '/assets/[^"]+\.js' | head -1 || true)"
  [ -n "$asset" ] || { SA_LAST_HEALTH="$SA_LAST_HEALTH; spa=no-asset-reference"; return 1; }
  curl -fsS -m 5 -o /dev/null "$base$asset" 2>/dev/null || { SA_LAST_HEALTH="$SA_LAST_HEALTH; spa=asset-missing $asset"; return 1; }
}

# sa_wait_healthy [TIMEOUT_S] — API + SPA healthy twice in a row (5 s apart, to catch crash loops).
sa_wait_healthy() {
  local timeout="${1:-$(sa_env SA_DEPLOY_HEALTH_TIMEOUT_S 120)}" start ok=0
  start=$(date +%s)
  while :; do
    if sa_api_healthy && sa_spa_ok; then
      ok=$((ok + 1))
      [ "$ok" -ge 2 ] && { sa_log "healthy: $SA_LAST_HEALTH"; return 0; }
      sleep 5; continue
    fi
    ok=0
    if [ $(( $(date +%s) - start )) -ge "$timeout" ]; then
      sa_log "NOT healthy after ${timeout}s: $SA_LAST_HEALTH"; return 1
    fi
    sleep 3
  done
}

# Number of lesson/test generations in flight (0 if unknown/unreachable/field missing).
sa_active_generations() {
  local out code n
  out="$(_sa_get "$(sa_base_url)/api/v1/health")"; code="${out##*$'\n'}"
  [ "$code" = 200 ] || { echo 0; return 0; }
  n="$(printf '%s' "${out%$'\n'*}" | tr -d '\n' | sed -n 's/.*"active_generations"[[:space:]]*:[[:space:]]*\([0-9][0-9]*\).*/\1/p')"
  echo "${n:-0}"
}

# Don't restart the backend under a child whose lesson is being generated: poll every 10 s, up to
# SA_DEPLOY_MAX_WAIT_S (default 600), then go ahead anyway.
sa_wait_for_generations() {
  local max n start waited
  max="$(sa_env SA_DEPLOY_MAX_WAIT_S 600)"; start=$(date +%s)
  while :; do
    n="$(sa_active_generations)"
    [ "$n" -gt 0 ] 2>/dev/null || return 0
    waited=$(( $(date +%s) - start ))
    if [ "$waited" -ge "$max" ]; then
      sa_log "still $n generation(s) running after ${waited}s (SA_DEPLOY_MAX_WAIT_S=$max) — restarting anyway"
      return 0
    fi
    sa_log "$n lesson/test generation(s) in progress — waiting before restarting the backend (${waited}s/${max}s)"
    sleep 10
  done
}

# ---------------------------------------------------------------- images / rollback
_sa_image_id() { sa_docker image inspect -f '{{.Id}}' "$1" 2>/dev/null || true; }
_sa_running_image_id() {
  local cid
  cid="$(sa_dc ps -q "$1" 2>/dev/null | head -1 || true)"
  [ -n "$cid" ] && sa_docker inspect -f '{{.Image}}' "$cid" 2>/dev/null || true
}

# Tag what is running now (or, if a service isn't running, its current :latest) as :previous.
sa_tag_previous() {
  local svc img id
  for svc in "${SA_SERVICES[@]}"; do
    img="$(sa_image_of "$svc")"
    id="$(_sa_running_image_id "$svc")"
    [ -n "$id" ] || id="$(_sa_image_id "$img:latest")"
    if [ -n "$id" ]; then
      sa_docker image tag "$id" "$img:previous"
      sa_log "tagged the current $svc image ($(printf '%s' "${id#sha256:}" | cut -c1-12)) as $img:previous"
    else
      sa_log "no existing $svc image (first deploy) — nothing to roll back to"
    fi
  done
}

sa_have_previous() {
  local svc
  for svc in "${SA_SERVICES[@]}"; do [ -n "$(_sa_image_id "$(sa_image_of "$svc"):previous")" ] || return 1; done
}

# Point :latest back at :previous (compose runs :latest).
sa_restore_latest() {
  local svc img
  for svc in "${SA_SERVICES[@]}"; do
    img="$(sa_image_of "$svc")"
    [ -n "$(_sa_image_id "$img:previous")" ] && sa_docker image tag "$img:previous" "$img:latest"
  done
  return 0
}

sa_diagnostics() {
  sa_log "---- diagnostics: compose ps / backend + frontend logs (tail) ----"
  sa_dc ps 2>&1 || true
  sa_dc logs --no-color --tail 60 backend 2>&1 || true
  sa_dc logs --no-color --tail 20 frontend 2>&1 || true
  sa_log "---- end diagnostics ----"
}

# sa_deploy — build, wait for generations, restart, health-gate, roll back on failure.
# Returns: 0 healthy | 10 build failed (nothing changed) | 20 unhealthy, rolled back, previous healthy
#          21 unhealthy and rollback impossible or also unhealthy (site likely DOWN)
sa_deploy() {
  local backend_before backend_after
  sa_tag_previous
  backend_before="$(_sa_running_image_id backend)"

  sa_log "building images (--pull: base images get security updates)..."
  if ! sa_dc build --pull; then
    sa_log "build with --pull failed; retrying once with cached base images (registry hiccup?)..."
    if ! sa_dc build; then
      sa_log "build FAILED — the running containers were not touched"
      sa_restore_latest   # a half-finished build may have re-tagged one service's :latest
      return 10
    fi
  fi

  backend_after="$(_sa_image_id "$(sa_image_of backend):latest")"
  if [ -n "$backend_before" ] && [ "$backend_before" = "$backend_after" ]; then
    sa_log "backend image unchanged — it won't be restarted, no need to wait for generations"
  else
    sa_wait_for_generations
  fi

  sa_log "starting the new release..."
  if sa_dc up -d --no-build && sa_wait_healthy; then
    return 0
  fi

  sa_log "new release is NOT healthy"
  sa_diagnostics
  if ! sa_have_previous; then
    sa_log "no :previous images to roll back to"
    return 21
  fi
  sa_log "rolling back to the :previous images..."
  sa_restore_latest
  if sa_dc up -d --no-build --force-recreate && sa_wait_healthy; then
    sa_log "rollback OK — previous release is serving again"
    return 20
  fi
  sa_log "rollback did NOT become healthy either"
  sa_diagnostics
  return 21
}

# ---------------------------------------------------------------- SQLite snapshot
# Python run INSIDE the backend container: consistent online copy via SQLite's backup API (safe
# while the app writes; WAL readers don't block writers), integrity_check on the copy, then the
# copy is gzip-streamed to stdout. Status goes to stderr. Only the DB file is copied — the visual
# cache under /app/data/cache is regenerable and deliberately excluded.
# shellcheck disable=SC2016
SA_SNAPSHOT_PY='
import gzip, os, shutil, sqlite3, sys, tempfile
src = os.environ.get("SA_DB_FILE", "/app/data/schoolautomaton.db")
if not os.path.isfile(src):
    sys.exit("database not found: " + src)
fd, tmp = tempfile.mkstemp(prefix="sa-snapshot-", suffix=".db")
os.close(fd)
try:
    s = sqlite3.connect(src, timeout=60)
    d = sqlite3.connect(tmp)
    s.backup(d)
    s.close()
    d.execute("PRAGMA journal_mode=DELETE")
    res = [r[0] for r in d.execute("PRAGMA integrity_check").fetchall()]
    if res != ["ok"]:
        sys.exit("integrity_check FAILED on the copy: " + "; ".join(res[:5]))
    tables = d.execute("SELECT count(*) FROM sqlite_master WHERE type = ?", ("table",)).fetchone()[0]
    d.close()
    size = os.path.getsize(tmp)
    with open(tmp, "rb") as f, gzip.GzipFile(fileobj=sys.stdout.buffer, mode="wb", compresslevel=6) as gz:
        shutil.copyfileobj(f, gz, 1 << 20)
    sys.stdout.buffer.flush()
    print("snapshot ok: %d bytes, %d tables, integrity_check ok" % (size, tables), file=sys.stderr)
finally:
    os.unlink(tmp)
'

# sa_snapshot_db OUT_GZ — write a verified gzip snapshot of the live DB to OUT_GZ (host path).
# Uses the running backend container, or a one-off container if the backend is stopped.
sa_snapshot_db() {
  local out="$1" err rc=0
  err="$(mktemp)"
  if [ -n "$(sa_dc ps -q backend 2>/dev/null || true)" ] && \
     [ "$(sa_docker inspect -f '{{.State.Running}}' "$(sa_dc ps -q backend | head -1)" 2>/dev/null)" = true ]; then
    sa_dc exec -T backend python -c "$SA_SNAPSHOT_PY" > "$out" 2> "$err" || rc=$?
  else
    sa_dc run --rm --no-deps -T backend python -c "$SA_SNAPSHOT_PY" > "$out" 2> "$err" || rc=$?
  fi
  while IFS= read -r line; do sa_log "  $line"; done < "$err"
  rm -f "$err"
  [ "$rc" -eq 0 ] || return "$rc"
  gzip -t "$out" 2>/dev/null || { sa_log "snapshot is not a valid gzip stream"; return 1; }
  [ "$(gzip -dc "$out" | head -c 15)" = "SQLite format 3" ] || { sa_log "snapshot is not an SQLite file"; return 1; }
}
