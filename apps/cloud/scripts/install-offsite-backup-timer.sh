#!/usr/bin/env bash
# Installs only this repo's user-level backup timer on the approved source VPS.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
[[ -z "$(git -C "$root" status --porcelain)" ]] || { echo 'Release worktree must be clean' >&2; exit 2; }
# A single Doppler configuration supplies both manual and scheduled backups.
# Refuse to install a timer until an approved destination and age key are
# available. Neither the destination nor secrets are printed or persisted.
bash "$root/scripts/doppler-runtime.sh" bash -c '
  set -euo pipefail
  [[ "${OFFSITE_REMOTE_SSH:-}" =~ ^[a-z_][a-z0-9_-]*@[0-9.]+$ ]] &&
  [[ "${OFFSITE_REMOTE_DIR:-}" =~ ^/[a-zA-Z0-9_./-]+$ ]] &&
  [[ "$OFFSITE_REMOTE_DIR" != *..* ]] &&
  [[ -n "${KICAD_BACKUP_AGE_IDENTITY:-}" ]] &&
  [[ -n "${KICAD_BACKUP_AGE_RECIPIENT:-}" ]]
' || { echo 'Doppler offsite destination or age configuration is missing/invalid' >&2; exit 2; }
unit="$HOME/.config/systemd/user"
mkdir -p "$unit"
cat > "$unit/kicad-cloud-offsite.service" <<UNIT
[Unit]
Description=KiCad Cloud encrypted offsite backup with independent restore
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
WorkingDirectory=$root
ExecStart=/usr/bin/bash $root/scripts/doppler-runtime.sh /usr/bin/bash $root/scripts/offsite-backup-push.sh
TimeoutStartSec=420
UNIT
cat > "$unit/kicad-cloud-offsite.timer" <<'UNIT'
[Unit]
Description=Daily owner-controlled KiCad Cloud encrypted backup and restore
[Timer]
OnCalendar=daily
Persistent=true
AccuracySec=20m
[Install]
WantedBy=timers.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now kicad-cloud-offsite.timer
systemctl --user list-timers kicad-cloud-offsite.timer --no-pager
