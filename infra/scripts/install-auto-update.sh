#!/usr/bin/env bash
# SchoolAutomaton — schedule automatic updates AND nightly database backups.
#   update: git pull + health-gated rebuild/restart ONLY when there are new commits (update.sh)
#   backup: consistent SQLite snapshot into ./backups with daily/weekly rotation (backup.sh)
# Installs systemd timers (preferred) or falls back to cron. Idempotent: re-run any time
# (e.g. after pulling this version, to add the backup schedule).
#
#   sudo ./infra/scripts/install-auto-update.sh            # updates every 15 min, backup 03:30
#   sudo ./infra/scripts/install-auto-update.sh 30         # updates every 30 minutes
#   sudo SA_BACKUP_TIME=02:15 ./infra/scripts/install-auto-update.sh
#   sudo ./infra/scripts/install-auto-update.sh --uninstall
#
# Logs: <repo>/logs/update.log and <repo>/logs/backup.log (size-rotated by the scripts);
#       under systemd also: journalctl -u schoolautomaton-update -u schoolautomaton-backup
set -euo pipefail
cd "$(dirname "$0")/../.."
REPO="$(pwd)"

c_ok()  { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
c_say() { printf '\n\033[1;36m==>\033[0m %s\n' "$*"; }
c_die() { printf '\033[1;31m  ✗ %s\033[0m\n' "$*" >&2; exit 1; }
have()  { command -v "$1" >/dev/null 2>&1; }

SUDO=""
if [ "$(id -u)" -ne 0 ]; then have sudo && SUDO="sudo" || c_die "Run as root or install sudo."; fi
RUN_USER="${SUDO_USER:-$(id -un)}"

UNIT="schoolautomaton-update"
BUNIT="schoolautomaton-backup"
UDIR="${SA_SYSTEMD_DIR:-/etc/systemd/system}"   # override only for testing

# ---------- uninstall ----------
if [ "${1:-}" = "--uninstall" ]; then
  if have systemctl; then
    for u in "$UNIT" "$BUNIT"; do
      $SUDO systemctl disable --now "${u}.timer" >/dev/null 2>&1 || true
      $SUDO rm -f "$UDIR/${u}.service" "$UDIR/${u}.timer"
    done
    $SUDO systemctl daemon-reload || true
    c_ok "Removed systemd timers."
  fi
  if have crontab; then
    ( crontab -l 2>/dev/null | grep -vF "# ${UNIT}" | grep -vF "# ${BUNIT}" || true ) | crontab - || true
    c_ok "Removed cron entries (if any)."
  fi
  exit 0
fi

MINUTES="${1:-15}"
case "$MINUTES" in *[!0-9]* | "") c_die "Interval must be a whole number of minutes (e.g. 15).";; esac
BACKUP_TIME="${SA_BACKUP_TIME:-03:30}"
case "$BACKUP_TIME" in [0-2][0-9]:[0-5][0-9]) ;; *) c_die "SA_BACKUP_TIME must be HH:MM (e.g. 03:30).";; esac
mkdir -p "$REPO/logs"
[ -n "$SUDO" ] || chown "$RUN_USER" "$REPO/logs" 2>/dev/null || true

# ---------- systemd (preferred) ----------
if have systemctl; then
  c_say "Installing systemd timers (update every ${MINUTES} min, backup daily at ${BACKUP_TIME}, as user '${RUN_USER}')..."
  $SUDO tee "$UDIR/${UNIT}.service" >/dev/null <<EOF
[Unit]
Description=SchoolAutomaton auto-update (git pull + health-gated rebuild/restart on change)
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${RUN_USER}
WorkingDirectory=${REPO}
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=${REPO}/infra/scripts/update.sh
# Safety net against a hung build; a normal run is seconds (no-op) to ~15 min (build + waiting
# for lesson generations + health gate).
TimeoutStartSec=90min
EOF

  $SUDO tee "$UDIR/${UNIT}.timer" >/dev/null <<EOF
[Unit]
Description=Run SchoolAutomaton auto-update every ${MINUTES} minutes

[Timer]
OnBootSec=3min
OnCalendar=*:0/${MINUTES}
Persistent=true
RandomizedDelaySec=30

[Install]
WantedBy=timers.target
EOF

  $SUDO tee "$UDIR/${BUNIT}.service" >/dev/null <<EOF
[Unit]
Description=SchoolAutomaton nightly database backup
After=docker.service

[Service]
Type=oneshot
User=${RUN_USER}
WorkingDirectory=${REPO}
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=${REPO}/infra/scripts/backup.sh
TimeoutStartSec=90min
EOF

  $SUDO tee "$UDIR/${BUNIT}.timer" >/dev/null <<EOF
[Unit]
Description=Run SchoolAutomaton database backup daily at ${BACKUP_TIME}

[Timer]
OnCalendar=*-*-* ${BACKUP_TIME}:00
Persistent=true
RandomizedDelaySec=10min

[Install]
WantedBy=timers.target
EOF

  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --now "${UNIT}.timer" "${BUNIT}.timer"
  c_ok "Timers installed and started."
  echo
  echo "  Next runs:    systemctl list-timers '${UNIT}.timer' '${BUNIT}.timer'"
  echo "  Logs:         tail -f ${REPO}/logs/update.log   (backup: logs/backup.log)"
  echo "  Run now:      sudo systemctl start ${UNIT}.service   |   sudo systemctl start ${BUNIT}.service"
  echo "  Remove:       sudo $0 --uninstall"
  exit 0
fi

# ---------- cron fallback ----------
if have crontab; then
  c_say "systemd not found — installing cron jobs (update every ${MINUTES} min, backup daily at ${BACKUP_TIME})..."
  # The scripts write their own logs under logs/; cron output only catches early failures.
  LINE="*/${MINUTES} * * * * cd ${REPO} && ./infra/scripts/update.sh >/dev/null 2>>${REPO}/logs/cron-errors.log # ${UNIT}"
  BLINE="${BACKUP_TIME#*:} ${BACKUP_TIME%:*} * * * cd ${REPO} && ./infra/scripts/backup.sh >/dev/null 2>>${REPO}/logs/cron-errors.log # ${BUNIT}"
  ( crontab -l 2>/dev/null | grep -vF "# ${UNIT}" | grep -vF "# ${BUNIT}" || true; echo "$LINE"; echo "$BLINE" ) | crontab -
  c_ok "Cron jobs installed for user '$(id -un)'."
  echo "  Logs:    tail -f ${REPO}/logs/update.log   (backup: logs/backup.log)"
  echo "  Remove:  $0 --uninstall"
  exit 0
fi

c_die "Neither systemd nor cron is available — cannot schedule auto-updates/backups."
