#!/usr/bin/env bash
# SchoolAutomaton — consistent online backup of the SQLite database. Scheduled nightly by
# install-auto-update.sh; safe to run by hand at any time (also with the backend stopped).
#
#  1. SQLite's backup API inside the backend container: a consistent copy while the app keeps
#     writing (copying the live WAL database files with tar/cp is NOT consistent).
#  2. PRAGMA integrity_check on the copy, gzip, stream it to the host.
#  3. Store it OUTSIDE the Docker volume, in SA_BACKUP_DIR (default ./backups, chmod 700):
#       daily/schoolautomaton-YYYY-MM-DD.db.gz   newest SA_BACKUP_KEEP_DAILY (14) kept
#       weekly/schoolautomaton-YYYY-Www.db.gz    first backup of each ISO week, newest
#                                                SA_BACKUP_KEEP_WEEKLY (8) kept
#  4. Any failure -> alert via SA_ALERT_WEBHOOK_URL; old backups are only pruned after a success.
#
# The visual cache (/app/data/cache) is NOT backed up — it is regenerated on demand.
# Provider keys stored from the admin Settings page are encrypted with APP_SECRET: keep a copy of
# .env somewhere safe too, or a restored DB can't decrypt them.
# Restore: ./infra/scripts/restore.sh <backup.db.gz>  (see DEPLOY.md). Log: logs/backup.log
set -Eeuo pipefail
umask 077
cd "$(dirname "$0")/../.."
REPO="$(pwd)"
SA_LOG_TAG=backup
# shellcheck source=lib/ops-common.sh
. infra/scripts/lib/ops-common.sh

TMP=""
fail() {
  [ -n "$TMP" ] && rm -f "$TMP"
  sa_alert backup-failed "database backup FAILED: $1. Log: $REPO/$SA_LOG_DIR/backup.log"
  exit 1
}

prune() {  # prune DIR KEEP — delete all but the newest KEEP backups (names sort chronologically)
  local d="$1" keep="$2" files i
  shopt -s nullglob; files=("$d"/schoolautomaton-*.db.gz); shopt -u nullglob
  for ((i = 0; i < ${#files[@]} - keep; i++)); do
    rm -f -- "${files[$i]}" && sa_log "pruned ${files[$i]#"$REPO"/}"
  done
}

main() {
  local dir keep_d keep_w today final weekly
  dir="$(sa_env SA_BACKUP_DIR backups)"
  case "$dir" in /*) ;; *) dir="$REPO/$dir" ;; esac
  keep_d="$(sa_env SA_BACKUP_KEEP_DAILY 14)"; keep_w="$(sa_env SA_BACKUP_KEEP_WEEKLY 8)"
  case "$keep_d" in ""|*[!0-9]*|0) keep_d=14 ;; esac
  case "$keep_w" in ""|*[!0-9]*|0) keep_w=8 ;; esac

  # Same lock as update.sh/deploy.sh: never snapshot while a deploy is restarting the backend.
  if command -v flock >/dev/null 2>&1; then
    exec 9>"$SA_LOCK_FILE"
    flock -w 2700 9 || fail "could not get the deploy lock within 45 min (is an update stuck?)"
  fi

  mkdir -p "$dir/daily" "$dir/weekly" || fail "cannot create $dir"
  chmod 700 "$dir" 2>/dev/null || true
  find "$dir" -maxdepth 1 -name '.incoming-*' -mmin +120 -delete 2>/dev/null || true

  today="$(date +%F)"
  TMP="$dir/.incoming-$today-$$.db.gz"
  final="$dir/daily/schoolautomaton-$today.db.gz"
  sa_log "snapshotting the database ..."
  sa_snapshot_db "$TMP" || fail "snapshot or integrity check failed (details above)"
  mv -f "$TMP" "$final"; TMP=""
  sa_log "saved $final ($(du -h "$final" | cut -f1))"

  weekly="$dir/weekly/schoolautomaton-$(date +%G-W%V).db.gz"
  if [ ! -e "$weekly" ]; then
    ln -f "$final" "$weekly" 2>/dev/null || cp -p "$final" "$weekly"
    sa_log "weekly copy: $weekly"
  fi

  prune "$dir/daily" "$keep_d"
  prune "$dir/weekly" "$keep_w"
  sa_log "backup OK — kept $(find "$dir/daily" -name '*.db.gz' | wc -l) daily / $(find "$dir/weekly" -name '*.db.gz' | wc -l) weekly in $dir"
}

mkdir -p "$SA_LOG_DIR"
sa_rotate_log "$SA_LOG_DIR/backup.log"
set +e
main "$@" 2>&1 | tee -a "$SA_LOG_DIR/backup.log"
exit "${PIPESTATUS[0]}"
