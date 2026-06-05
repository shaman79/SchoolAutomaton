#!/usr/bin/env bash
# SchoolAutomaton — schedule automatic updates (git pull + rebuild/restart ONLY when there are new
# commits). Installs a systemd timer (preferred) or falls back to a cron job.
#
#   sudo ./infra/scripts/install-auto-update.sh            # every 15 minutes (default)
#   sudo ./infra/scripts/install-auto-update.sh 30         # every 30 minutes
#   sudo ./infra/scripts/install-auto-update.sh --uninstall
#
# Logs:  systemd -> journalctl -u schoolautomaton-update.service
#        cron    -> <repo>/.sa-update.log
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
SVC="/etc/systemd/system/${UNIT}.service"
TMR="/etc/systemd/system/${UNIT}.timer"

# ---------- uninstall ----------
if [ "${1:-}" = "--uninstall" ]; then
  if have systemctl; then
    $SUDO systemctl disable --now "${UNIT}.timer" >/dev/null 2>&1 || true
    $SUDO rm -f "$SVC" "$TMR"; $SUDO systemctl daemon-reload || true
    c_ok "Removed systemd timer."
  fi
  if have crontab; then
    ( crontab -l 2>/dev/null | grep -vF "# ${UNIT}" || true ) | crontab - || true
    c_ok "Removed cron entry (if any)."
  fi
  exit 0
fi

MINUTES="${1:-15}"
case "$MINUTES" in *[!0-9]* | "") c_die "Interval must be a whole number of minutes (e.g. 15).";; esac

# ---------- systemd (preferred) ----------
if have systemctl; then
  c_say "Installing systemd timer (every ${MINUTES} min, as user '${RUN_USER}')..."
  $SUDO tee "$SVC" >/dev/null <<EOF
[Unit]
Description=SchoolAutomaton auto-update (git pull + rebuild/restart on change)
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=${RUN_USER}
WorkingDirectory=${REPO}
Environment=PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ExecStart=${REPO}/infra/scripts/update.sh
EOF

  $SUDO tee "$TMR" >/dev/null <<EOF
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

  $SUDO systemctl daemon-reload
  $SUDO systemctl enable --now "${UNIT}.timer"
  c_ok "Timer installed and started."
  echo
  echo "  Next runs:   systemctl list-timers ${UNIT}.timer"
  echo "  Logs:        journalctl -u ${UNIT}.service -f"
  echo "  Run now:     sudo systemctl start ${UNIT}.service"
  echo "  Remove:      sudo $0 --uninstall"
  exit 0
fi

# ---------- cron fallback ----------
if have crontab; then
  c_say "systemd not found — installing a cron job (every ${MINUTES} min)..."
  LINE="*/${MINUTES} * * * * cd ${REPO} && ./infra/scripts/update.sh >> ${REPO}/.sa-update.log 2>&1 # ${UNIT}"
  ( crontab -l 2>/dev/null | grep -vF "# ${UNIT}" || true; echo "$LINE" ) | crontab -
  c_ok "Cron job installed for user '$(id -un)'."
  echo "  Logs:    tail -f ${REPO}/.sa-update.log"
  echo "  Remove:  $0 --uninstall"
  exit 0
fi

c_die "Neither systemd nor cron is available — cannot schedule auto-updates."
