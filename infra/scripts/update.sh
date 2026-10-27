#!/usr/bin/env bash
# SchoolAutomaton — update an existing deployment. Runs every 15 min (install-auto-update.sh).
#
#   git pull; if HEAD is not the last successfully deployed commit:
#     tag the running images :previous -> build --pull -> wait (bounded) for lesson generations in
#     flight -> up -d -> health gate through nginx (/api/v1/health + the SPA) for ~2 min.
#     Unhealthy -> roll back to :previous, verify, remember the commit as bad (not rebuilt again
#     until a newer commit lands) and alert via SA_ALERT_WEBHOOK_URL.
#   Nothing new -> fast no-op. Overlapping runs (and backups/restores) are serialized by one lock.
#
#   ./infra/scripts/update.sh            normal run
#   ./infra/scripts/update.sh --force    rebuild + redeploy the current commit (also retries a bad one)
#
# State: .sa-deploy/ (deployed-commit, bad-commit). Log: logs/update.log (+ stdout/journald).
set -Eeuo pipefail
cd "$(dirname "$0")/../.."
REPO="$(pwd)"
SA_LOG_TAG=update
# shellcheck source=lib/ops-common.sh
. infra/scripts/lib/ops-common.sh

FORCE=0
case "${1:-}" in
  --force) FORCE=1 ;;
  "") ;;
  *) echo "usage: $0 [--force]" >&2; exit 2 ;;
esac

mark_bad() {  # mark_bad COMMIT REASON
  printf '%s %s %s\n' "$1" "$(date +%s)" "$2" > "$SA_STATE_DIR/bad-commit"
}

main() {
  if command -v flock >/dev/null 2>&1; then
    exec 9>"$SA_LOCK_FILE"
    if ! flock -n 9; then sa_log "another update/deploy/backup is running — skipping."; return 0; fi
  fi
  mkdir -p "$SA_STATE_DIR"

  local before="none" head="none" out n deployed bad subject rc=0
  if git rev-parse --git-dir >/dev/null 2>&1; then
    before="$(git rev-parse HEAD)"
    if ! out="$(git pull --ff-only -q 2>&1)"; then
      printf '%s\n' "$out"
      n=$(( $(cat "$SA_STATE_DIR/pull-failures" 2>/dev/null || echo 0) + 1 ))
      echo "$n" > "$SA_STATE_DIR/pull-failures"
      sa_log "git pull failed ($n run(s) in a row)"
      # One failed pull is usually a network blip; four in a row (~1 h) means updates are stuck.
      if [ "$n" -ge 4 ]; then
        sa_alert pull-failed "auto-update cannot 'git pull' (failing for 1 h+): $(printf '%s' "$out" | tail -2 | tr '\n' ' ') — check: cd $REPO && git status"
      fi
      return 1
    fi
    rm -f "$SA_STATE_DIR/pull-failures"
    head="$(git rev-parse HEAD)"
  fi

  deployed="$(cat "$SA_STATE_DIR/deployed-commit" 2>/dev/null || true)"
  bad="$(cut -d' ' -f1 "$SA_STATE_DIR/bad-commit" 2>/dev/null || true)"
  subject="$(git log -1 --format='%h "%s"' "$head" 2>/dev/null | cut -c1-90 || echo "$head")"

  if [ "$FORCE" -ne 1 ]; then
    if [ -z "$deployed" ] && [ "$before" = "$head" ]; then
      # First run of this script version: adopt what is running as the deployed commit.
      echo "$head" > "$SA_STATE_DIR/deployed-commit"
      sa_log "no deploy record yet — recording the running commit $subject as deployed"
      return 0
    fi
    if [ "$head" = "$deployed" ]; then
      sa_log "up to date ($subject)"
      return 0
    fi
    if [ "$head" = "$bad" ]; then
      sa_log "skipping $subject: it already failed to deploy (see earlier in this log). Push a fix, or retry with: $0 --force"
      return 0
    fi
  fi

  local last="${deployed:0:7}"; [ "$FORCE" -eq 1 ] && last="${last:-none}, --force"
  sa_log "deploying $subject (last deployed: ${last:-none})"
  sa_deploy || rc=$?
  case "$rc" in
    0)
      echo "$head" > "$SA_STATE_DIR/deployed-commit"
      if [ -f "$SA_STATE_DIR/bad-commit" ]; then
        rm -f "$SA_STATE_DIR/bad-commit"
        sa_alert recovered "deployed $subject — healthy again." default
      fi
      # Dangling images only; :previous stays tagged for the next rollback.
      sa_docker image prune -f >/dev/null 2>&1 || true
      sa_log "deploy OK: $subject is live on $(sa_base_url) (served publicly via the Cloudflare tunnel)"
      ;;
    10)
      mark_bad "$head" build
      sa_alert "build-$head" "build of $subject FAILED — the previous release keeps running. Auto-update skips this commit until a newer one lands (or: update.sh --force). Log: $REPO/$SA_LOG_DIR/update.log"
      return 1
      ;;
    20)
      mark_bad "$head" unhealthy
      sa_alert "unhealthy-$head" "$subject did not become healthy — ROLLED BACK to the previous release (site is up). Auto-update skips this commit until a newer one lands. Log: $REPO/$SA_LOG_DIR/update.log"
      return 1
      ;;
    *)
      mark_bad "$head" unhealthy-no-rollback
      sa_alert "down-$head" "$subject did not become healthy and there is no healthy previous release to roll back to — SITE MAY BE DOWN. Check: cd $REPO && docker compose ps && docker compose logs backend" urgent
      return 1
      ;;
  esac
}

mkdir -p "$SA_LOG_DIR"
sa_rotate_log "$SA_LOG_DIR/update.log"
set +e
main "$@" 2>&1 | tee -a "$SA_LOG_DIR/update.log"
exit "${PIPESTATUS[0]}"
