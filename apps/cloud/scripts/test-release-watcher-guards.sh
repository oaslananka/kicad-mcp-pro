#!/usr/bin/env bash
# Safe offline tests: mock git/loginctl/systemctl, and isolate HOME.
# Never install or enable a real systemd timer.
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$root"
# Regression: releases must come from the unified repo and its scoped Cloud CI.
grep -Fq 'https://github.com/oaslananka/kicad-mcp-pro.git' scripts/production-deploy-if-ready.sh
grep -Fq 'kicad-mcp-pro/actions/workflows/cloud-ci.yml/runs' scripts/production-deploy-if-ready.sh
sandbox=$(mktemp -d "${TMPDIR:-/tmp}/kicad-watcher-fixture.XXXXXXXX")
chmod 700 "$sandbox"
trap 'rm -rf -- "$sandbox"' EXIT
mkdir -m 700 "$sandbox/bin" "$sandbox/home"
cat > "$sandbox/bin/git" <<'MOCK'
#!/usr/bin/env bash
set -eu
case "$*" in
  *' remote get-url origin') echo 'https://github.com/oaslananka/kicad-mcp-pro.git';;
  *' status --porcelain') ;;
  *' rev-parse HEAD') echo "$MOCK_HEAD";;
  *' ls-remote origin refs/heads/main') echo "$MOCK_MAIN refs/heads/main";;
  *) exit 97;;
esac
MOCK
cat > "$sandbox/bin/loginctl" <<'MOCK'
#!/usr/bin/env bash
set -eu
[[ "$*" == 'show-user '*' --property=Linger --value' ]] || exit 97
echo "$MOCK_LINGER"
MOCK
cat > "$sandbox/bin/systemctl" <<'MOCK'
#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$MOCK_LOG"
case "$*" in
  '--user is-active default.target') echo active;;
  '--user is-active kicad-cloud-production.timer') echo "${MOCK_TIMER_ACTIVE:-inactive}";;
  '--user daemon-reload'|'--user enable --now kicad-cloud-production.timer'|'--user list-timers kicad-cloud-production.timer --no-pager') ;;
  *) exit 97;;
esac
MOCK
chmod 700 "$sandbox/bin/"*
export PATH="$sandbox/bin:$PATH" HOME="$sandbox/home" MOCK_LOG="$sandbox/calls.log"
export MOCK_HEAD='1697bf37f689aac3f16eca2dc0b5827f055e9795'
export MOCK_MAIN="$MOCK_HEAD" MOCK_LINGER=yes KICAD_DOPPLER_SCOPED=true
check_blocked() {
  : > "$MOCK_LOG"
  if out=$(bash scripts/install-production-deploy-timer.sh 2>&1); then
    echo 'FAIL: watcher installer accepted unsafe preflight' >&2
    exit 1
  fi
  [[ "$out" == *"$1"* ]] || { echo "FAIL: unexpected refusal: $out" >&2; exit 1; }
  [[ ! -e "$HOME/.config/systemd/user/kicad-cloud-production.timer" ]] || {
    echo 'FAIL: blocked watcher wrote unit files' >&2; exit 1
  }
  # Read-only systemctl checks are allowed; an unsafe installer may not
  # reload, enable or start a unit while any guard is rejecting it.
  ! grep -Eq 'daemon-reload|enable --now|start ' "$MOCK_LOG" || {
    echo 'FAIL: blocked watcher mutated systemd' >&2; exit 1
  }
}
MOCK_HEAD='b189aeaadef23f226e6438d00655922484c46143' check_blocked 'requires exact current remote main'
echo 'PASS: unmerged PR acceptance checkout cannot install a release timer'
unset KICAD_WATCHER_CUTOVER_CONFIRMED || true
check_blocked 'explicit old-watcher cutover confirmation'
echo 'PASS: new VPS watcher requires old watcher cutover confirmation'
export KICAD_WATCHER_CUTOVER_CONFIRMED=old-watcher-disabled-and-destination-verified
MOCK_LINGER=no check_blocked 'Enable systemd user lingering'
echo 'PASS: watcher rejects VPS without restart-surviving user manager'
export MOCK_TIMER_ACTIVE=active
export MOCK_LINGER=yes
check_blocked 'Existing release timer is still active'
echo 'PASS: watcher refuses to overwrite a running legacy timer'
export MOCK_TIMER_ACTIVE=inactive
: > "$MOCK_LOG"
bash scripts/install-production-deploy-timer.sh >/dev/null
[[ -f "$HOME/.config/systemd/user/kicad-cloud-production.timer" ]]
grep -q 'Environment=KICAD_DOPPLER_SCOPED=true' "$HOME/.config/systemd/user/kicad-cloud-production.service"
grep -q 'WantedBy=timers.target' "$HOME/.config/systemd/user/kicad-cloud-production.timer"
grep -q '^--user enable --now kicad-cloud-production.timer$' "$MOCK_LOG"
echo 'PASS: approved main watcher prepares restart-surviving user units only in isolated fake HOME'
