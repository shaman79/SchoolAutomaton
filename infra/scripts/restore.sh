#!/usr/bin/env bash
# SchoolAutomaton — restore the database from a backup made by backup.sh.
#
#   ./infra/scripts/restore.sh backups/daily/schoolautomaton-2026-10-27.db.gz
#   ./infra/scripts/restore.sh --yes <file>                 (no confirmation prompt)
#   ./infra/scripts/restore.sh --skip-safety-copy <file>    (when the current DB is too broken to copy)
#
# 1. checks the backup is a gzip'd SQLite file
# 2. safety snapshot of the CURRENT database -> backups/pre-restore/
# 3. stops the backend (nginx keeps serving the app shell; API calls fail for those seconds)
# 4. writes the backup into the sa-data volume as the app user, runs integrity_check, removes the
#    stale -wal/-shm files (they belong to the old DB and would corrupt the restored one), swaps it in
# 5. starts the backend and waits for /api/v1/health
# Holds the deploy lock, so auto-update and the nightly backup can't run in the middle of it.
set -Eeuo pipefail
umask 077
cd "$(dirname "$0")/../.."
REPO="$(pwd)"
SA_LOG_TAG=restore
# shellcheck source=lib/ops-common.sh
. infra/scripts/lib/ops-common.sh

YES=0; SAFETY=1; SRC=""
for a in "$@"; do
  case "$a" in
    --yes|-y) YES=1 ;;
    --skip-safety-copy) SAFETY=0 ;;
    -*) echo "unknown option $a" >&2; exit 2 ;;
    *) SRC="$a" ;;
  esac
done
die() { sa_log "ERROR: $*"; exit 1; }
[ -n "$SRC" ] && [ -f "$SRC" ] || { echo "usage: $0 [--yes] [--skip-safety-copy] <backup.db.gz|backup.db>" >&2; exit 2; }

case "$SRC" in
  *.gz) gzip -t "$SRC" || die "$SRC is not a valid gzip file"; READER=(gzip -dc -- "$SRC") ;;
  *)    READER=(cat -- "$SRC") ;;
esac
[ "$("${READER[@]}" | head -c 15)" = "SQLite format 3" ] || die "$SRC is not an SQLite database"

if [ "$YES" -ne 1 ]; then
  [ -t 0 ] || die "refusing to restore without --yes when not interactive"
  read -r -p "Replace the LIVE database with $SRC? Learners' progress since then is lost. [y/N] " ans
  case "$ans" in [Yy]*) ;; *) echo "aborted."; exit 1 ;; esac
fi

if command -v flock >/dev/null 2>&1; then
  exec 9>"$SA_LOCK_FILE"
  flock -n 9 || { sa_log "waiting for a running update/backup to finish..."; flock -w 1800 9 || die "lock timeout"; }
fi

if [ "$SAFETY" -eq 1 ]; then
  dir="$(sa_env SA_BACKUP_DIR backups)"; case "$dir" in /*) ;; *) dir="$REPO/$dir" ;; esac
  mkdir -p "$dir/pre-restore"; chmod 700 "$dir" 2>/dev/null || true
  safety="$dir/pre-restore/schoolautomaton-$(date +%Y%m%d-%H%M%S).db.gz"
  sa_log "safety snapshot of the current database -> $safety"
  sa_snapshot_db "$safety" || { rm -f "$safety"; die "could not snapshot the current DB (re-run with --skip-safety-copy to restore anyway)"; }
fi

# Runs inside a one-off backend container (as the app user, so file ownership stays right).
# shellcheck disable=SC2016
RESTORE_PY='
import os, shutil, sqlite3, sys
db = os.environ.get("SA_DB_FILE", "/app/data/schoolautomaton.db")
tmp = db + ".restore-tmp"
with open(tmp, "wb") as f:
    shutil.copyfileobj(sys.stdin.buffer, f, 1 << 20)
c = sqlite3.connect(tmp)
res = [r[0] for r in c.execute("PRAGMA integrity_check").fetchall()]
c.close()
if res != ["ok"]:
    os.unlink(tmp)
    sys.exit("integrity_check FAILED on the backup: " + "; ".join(res[:5]))
for ext in ("-wal", "-shm", "-journal"):
    try:
        os.unlink(db + ext)
    except FileNotFoundError:
        pass
os.replace(tmp, db)
print("restored %s (%d bytes, integrity_check ok)" % (db, os.path.getsize(db)), file=sys.stderr)
'

sa_log "stopping the backend..."
sa_dc stop backend
sa_log "writing $SRC into the data volume..."
if ! "${READER[@]}" | sa_dc run --rm --no-deps -T backend python -c "$RESTORE_PY"; then
  sa_log "restore FAILED — the previous database is untouched; starting the backend again"
  sa_dc start backend || true
  exit 1
fi
sa_log "starting the backend..."
sa_dc start backend
if sa_wait_healthy 120; then
  sa_log "restore complete."
else
  sa_log "WARNING: backend not healthy after the restore — check: docker compose logs backend"
  exit 1
fi
