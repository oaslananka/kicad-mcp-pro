#!/usr/bin/env bash
# Explicit installation of an approved main release watcher; never run this
# on an unmerged PR acceptance checkout or before a reviewed VPS cutover.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
[[ $(git -C "$root" remote get-url origin) == 'https://github.com/oaslananka/kicad-mcp-pro-cloud.git' ]] || {
  echo 'Unexpected deployment repository' >&2; exit 2
}
[[ -z $(git -C "$root" status --porcelain) ]] || { echo 'Deployment worktree must be clean' >&2; exit 2; }
# The timer updates its own checkout to main: installing while HEAD points to
# an unmerged PR would silently couple an acceptance host to production.
local_head=$(git -C "$root" rev-parse HEAD)
main_head=$(git -C "$root" ls-remote origin refs/heads/main | awk '{print $1}')
[[ "$main_head" =~ ^[a-f0-9]{40}$ && "$local_head" == "$main_head" ]] || {
  echo 'Release watcher requires exact current remote main; PR acceptance is never eligible' >&2
  exit 2
}
[[ "$root" != *[[:space:]]* ]] || { echo 'Worktree path must not contain whitespace for systemd unit' >&2; exit 2; }
case "${KICAD_DOPPLER_SCOPED:-false}" in
  true)
    # A separate owner-approved cutover must stop and verify the old watcher.
    # Do not silently enable two VPS watchers for a single main branch.
    [[ "${KICAD_WATCHER_CUTOVER_CONFIRMED:-}" == "old-watcher-disabled-and-destination-verified" ]] || {
      echo 'New VPS release watcher requires explicit old-watcher cutover confirmation' >&2; exit 2
    }
    [[ $(loginctl show-user "$(id -un)" --property=Linger --value) == yes ]] || {
      echo 'Enable systemd user lingering on the new VPS before watcher setup' >&2; exit 2
    }
    [[ $(systemctl --user is-active default.target) == active ]] || {
      echo 'systemd user manager is unavailable' >&2; exit 2
    }
    ;;
  false) ;;
  *) echo 'KICAD_DOPPLER_SCOPED must be true or false' >&2; exit 2 ;;
esac
units="$HOME/.config/systemd/user"
mkdir -p "$units"
cat > "$units/kicad-cloud-production.service" <<UNIT
[Unit]
Description=KiCad Cloud deploy verified main revision
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
WorkingDirectory=$root
ExecStart=/usr/bin/bash $root/scripts/production-deploy-if-ready.sh
Environment=KICAD_DOPPLER_SCOPED=${KICAD_DOPPLER_SCOPED:-false}
TimeoutStartSec=480
UNIT
cat > "$units/kicad-cloud-production.timer" <<'UNIT'
[Unit]
Description=Check approved KiCad Cloud releases every two minutes
[Timer]
OnBootSec=40s
OnUnitInactiveSec=120s
AccuracySec=10s
[Install]
WantedBy=timers.target
UNIT
systemctl --user daemon-reload
systemctl --user enable --now kicad-cloud-production.timer
systemctl --user list-timers kicad-cloud-production.timer --no-pager
