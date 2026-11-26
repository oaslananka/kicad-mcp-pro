#!/usr/bin/env bash
# Exercise the real installer in a disposable owner pseudo-terminal.
# No package installation, network access or actual device connection.
set -euo pipefail
umask 077
export TEST_INSTALLER
TEST_INSTALLER="$(cd -- "$(dirname -- "$0")/../.." && pwd)/scripts/install-cloud.sh"
work="$(mktemp -d)"
trap 'rm -rf -- "$work"' EXIT
export TEST_CLI_TEMPLATE="$work/cli"
cat > "$TEST_CLI_TEMPLATE" <<'CLI'
#!/bin/bash
if [[ "$*" == "cloud --help" && "$TEST_SCENARIO" == late-unhealthy && "$0" == */releases/b/bin/kicad-mcp-pro ]]; then
  if [[ -e "$TEST_LATE_CHECK" ]]; then exit 1; fi
  touch "$TEST_LATE_CHECK"
fi
if [[ "$1" == --version || "$*" == "cloud --help" ]]; then exit 0; fi
if [[ "$*" == "cloud _update-control probe" ]]; then
  [[ -n "${TEST_HANDOFF:-}" && -f "$TEST_HANDOFF/lease" ]] || exit 1
  cat "$TEST_HANDOFF/lease"
  exit 0
fi
if [[ "$1 $2 $3" == "cloud _update-control request" ]]; then
  [[ -n "${TEST_HANDOFF:-}" && -f "$TEST_HANDOFF/lease" ]] || exit 1
  [[ "$(cat "$TEST_HANDOFF/lease")" == "$5 $7" ]] || exit 1
  printf '%s\n' requested >> "$TEST_LOG"
  touch "$TEST_HANDOFF/drain"
  if [[ "$TEST_SCENARIO" == interrupt-handoff ]]; then
    # Kill only the disposable updater which invoked this fixture. It must
    # have durably recorded the intent before issuing the stop request.
    [[ -f "$XDG_DATA_HOME/KiCadMCPPro/pending-release" ]] || exit 98
    parent_command="$(ps -p "$PPID" -o args=)"
    [[ "$parent_command" == *"pending_release()"* ]] || exit 98
    kill -KILL "$PPID"
  fi
  exit 0
fi
[[ "$*" == cloud && -t 0 ]] || exit 97
echo connected >> "$TEST_LOG"
if [[ "$TEST_SCENARIO" == policy-rejection ]]; then exit 3; fi
if [[ -n "${TEST_SELECTED_LOG:-}" ]]; then printf "%s\n" "$0" >> "$TEST_SELECTED_LOG"; fi
if [[ "$TEST_SCENARIO" == live-handoff ]]; then
  if [[ "$KICAD_CLOUD_UPDATE_SLOT" == a ]]; then
    printf '%s a\n' "$KICAD_CLOUD_UPDATE_GENERATION" > "$TEST_HANDOFF/lease"
    while [[ ! -f "$TEST_HANDOFF/drain" ]]; do sleep .05; done
    rm "$TEST_HANDOFF/lease"
    printf '%s\n' drained >> "$TEST_LOG"
  fi
fi
if [[ "$TEST_SCENARIO" == live-child ]]; then
  printf '%s\n' "$$" > "$TEST_CHILD_PID"
  while [[ ! -f "$TEST_RELEASE" ]]; do sleep .05; done
fi
CLI
mkdir "$work/bin"
cat > "$work/bin/uv" <<'UV'
#!/bin/bash
if [[ "$1" == --version ]]; then exit 0; fi
if [[ "$1" == run ]]; then
  if [[ -n "${TEST_REAL_UV:-}" ]]; then exec "$TEST_REAL_UV" "$@"; fi
  while [[ "$1" != python ]]; do shift; done
  shift
  exec python3 "$@"
fi
[[ "$UV_NO_CONFIG" == 1 ]] || exit 96
echo "$*" >> "$TEST_LOG"
if [[ "$TEST_SCENARIO" == offline ]]; then exit 1; fi
if [[ "$TEST_SCENARIO" == destructive-update || "$TEST_SCENARIO" == unhealthy-update ]]; then
  mkdir -p "$UV_TOOL_BIN_DIR"
  printf 'broken update\n' > "$UV_TOOL_BIN_DIR/kicad-mcp-pro"
  if [[ "$TEST_SCENARIO" == unhealthy-update ]]; then exit 0; fi
  exit 1
fi
mkdir -p "$UV_TOOL_BIN_DIR"
cp "$TEST_CLI_TEMPLATE" "$UV_TOOL_BIN_DIR/kicad-mcp-pro"
chmod 700 "$UV_TOOL_BIN_DIR/kicad-mcp-pro"
UV
chmod 700 "$work/bin/uv"
export PATH="$work/bin:$PATH"
for TEST_SCENARIO in install repeat offline destructive-update running kernel-running stale-kernel; do
  export TEST_SCENARIO
  export HOME="$work/$TEST_SCENARIO/home"
  export XDG_DATA_HOME="$HOME/data"
  export TEST_LOG="$work/$TEST_SCENARIO/events"
  app="$XDG_DATA_HOME/KiCadMCPPro"
  mkdir -p "$app/bin"
  if [[ "$TEST_SCENARIO" != install ]]; then
    install -m 700 "$TEST_CLI_TEMPLATE" "$app/bin/kicad-mcp-pro"
  fi
  if [[ "$TEST_SCENARIO" == kernel-running ]]; then
    # Real kernel lock owned by a different process, not a PID-file fixture.
    python3 -c 'import fcntl,os,sys,time; f=open(sys.argv[1],"wb");os.chmod(sys.argv[1],0o600);fcntl.flock(f,fcntl.LOCK_EX);open(sys.argv[2],"w").close();time.sleep(30)' "$app/installer-v2.lock" "$work/locked" &
    holder=$!
    for _ in $(seq 1 100); do [[ -f "$work/locked" ]] && break; sleep .02; done
    [[ -f "$work/locked" ]]
    if timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null; then
      kill "$holder"; wait "$holder" || true
      echo "Live kernel lock was ignored" >&2; exit 1
    fi
    kill "$holder"; wait "$holder" || true
    [[ ! -e "$TEST_LOG" ]]
  elif [[ "$TEST_SCENARIO" == running ]]; then
    mkdir "$app/installer.lock"
    if timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null; then
      echo "Duplicate installer was not blocked" >&2
      exit 1
    fi
    [[ ! -e "$TEST_LOG" && -d "$app/installer.lock" ]]
  else
    if [[ "$TEST_SCENARIO" == stale-kernel ]]; then
      touch "$app/installer-v2.lock"
      chmod 600 "$app/installer-v2.lock"
    fi
    timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
    printf 'tool install --upgrade kicad-mcp-pro\nconnected\n' > "$work/expected"
    diff -u "$work/expected" "$TEST_LOG"
    if [[ "$TEST_SCENARIO" == destructive-update ]]; then
      cmp "$TEST_CLI_TEMPLATE" "$app/bin/kicad-mcp-pro"
    fi
    [[ ! -e "$app/installer.lock" ]]
  fi
  printf 'PASS: %s\n' "$TEST_SCENARIO"
done

# A genuine launcher/child owns the lock, including while its foreground
# Connector is active. Kill only the disposable fake Connector, never a
# real application, then prove the same setup recovers without lock cleanup.
export TEST_SCENARIO=live-child
export HOME="$work/live/home"
export XDG_DATA_HOME="$HOME/data"
export TEST_LOG="$work/live/events"
export TEST_CHILD_PID="$work/child.pid"
export TEST_RELEASE="$work/release"
mkdir -p "$HOME"
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null </dev/null &
launcher=$!
for _ in $(seq 1 100); do [[ -s "$TEST_CHILD_PID" ]] && break; sleep .05; done
if [[ ! -s "$TEST_CHILD_PID" ]]; then
  wait "$launcher" || true
  echo "The test Connector did not start" >&2
  exit 1
fi
child="$(cat "$TEST_CHILD_PID")"
if timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null; then
  touch "$TEST_RELEASE"
  wait "$launcher" || true
  echo "The running Connector did not retain the installer lock" >&2
  exit 1
fi
printf 'tool install --upgrade kicad-mcp-pro\nconnected\n' > "$work/expected"
diff -u "$work/expected" "$TEST_LOG"
kill -KILL "$child"
wait "$launcher" || true
touch "$TEST_RELEASE"
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
cat "$work/expected" "$work/expected" > "$work/expected-twice"
diff -u "$work/expected-twice" "$TEST_LOG"
printf 'PASS: live-child crash recovery\n'

# Preserve the already selected release across both resolver failure and a
# successful resolver exit with an unusable candidate, then switch A -> B -> A.
export HOME="$work/rotation/home"
export XDG_DATA_HOME="$HOME/data"
export TEST_LOG="$work/rotation/events"
export TEST_SELECTED_LOG="$work/rotation/selected"
mkdir -p "$HOME"
app="$XDG_DATA_HOME/KiCadMCPPro"
a="$app/releases/a/bin/kicad-mcp-pro"
b="$app/releases/b/bin/kicad-mcp-pro"
export TEST_SCENARIO=install
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
[[ "$(cat "$app/active-release")" == a ]]
for TEST_SCENARIO in destructive-update unhealthy-update; do
  export TEST_SCENARIO
  timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
  [[ "$(cat "$app/active-release")" == a ]]
  cmp "$TEST_CLI_TEMPLATE" "$a"
  [[ "$(tail -1 "$TEST_SELECTED_LOG")" == "$a" ]]
done
export TEST_SCENARIO=repeat
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
[[ "$(cat "$app/active-release")" == b ]]
[[ "$(tail -1 "$TEST_SELECTED_LOG")" == "$b" ]]
cmp "$TEST_CLI_TEMPLATE" "$a"
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
[[ "$(cat "$app/active-release")" == a ]]
cmp "$TEST_CLI_TEMPLATE" "$b"
printf 'PASS: staged release rotation and rollback\n'

# Same setup command while the new-style fixture is still running.
export HOME="$work/handoff/home"
export XDG_DATA_HOME="$HOME/data"
export TEST_LOG="$work/handoff/events"
export TEST_SELECTED_LOG="$work/handoff/selected"
export TEST_HANDOFF="$work/handoff/control"
mkdir -p "$HOME" "$TEST_HANDOFF"
export TEST_SCENARIO=live-handoff
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null </dev/null &
launcher=$!
for _ in $(seq 1 100); do [[ -s "$TEST_HANDOFF/lease" ]] && break; sleep .05; done
if [[ ! -s "$TEST_HANDOFF/lease" ]]; then
  touch "$TEST_HANDOFF/drain"
  wait "$launcher" || true
  echo "Update-aware fixture did not publish a lease" >&2
  exit 1
fi
app="$XDG_DATA_HOME/KiCadMCPPro"
a="$app/releases/a/bin/kicad-mcp-pro"
b="$app/releases/b/bin/kicad-mcp-pro"
# A broken candidate must not drain A or publish B.
export TEST_SCENARIO=destructive-update
if timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null; then
  echo "Broken live candidate reported success" >&2; exit 1
fi
[[ ! -e "$TEST_HANDOFF/drain" && "$(cat "$app/active-release")" == a ]]
cmp "$TEST_CLI_TEMPLATE" "$a"
export TEST_SCENARIO=live-handoff
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
wait "$launcher"
[[ "$(cat "$app/active-release")" == b ]]
[[ "$(tail -1 "$TEST_SELECTED_LOG")" == "$b" ]]
printf 'tool install --upgrade kicad-mcp-pro\nconnected\ntool install --upgrade kicad-mcp-pro\ntool install --upgrade kicad-mcp-pro\nrequested\ndrained\nconnected\n' > "$work/handoff-expected"
diff -u "$work/handoff-expected" "$TEST_LOG"
printf 'PASS: live staging, failed candidate keeps A, graceful A-to-B handoff\n'

# A previously healthy installed slot may become unusable after selection
# (disk corruption, interrupted environment, missing interpreter). Do not
# write over the remaining known-good slot merely to attempt an update.
unset TEST_HANDOFF
export HOME="$work/runtime/home"
export XDG_DATA_HOME="$HOME/data"
export TEST_LOG="$work/runtime/events"
export TEST_SELECTED_LOG="$work/runtime/selected"
export TEST_LATE_CHECK="$work/runtime/late-check"
mkdir -p "$HOME"
app="$XDG_DATA_HOME/KiCadMCPPro"
a="$app/releases/a/bin/kicad-mcp-pro"
b="$app/releases/b/bin/kicad-mcp-pro"
export TEST_SCENARIO=install
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
[[ "$(cat "$app/active-release")" == a ]]
export TEST_SCENARIO=late-unhealthy
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
[[ "$(cat "$app/active-release")" == a ]]
[[ "$(tail -1 "$TEST_SELECTED_LOG")" == "$a" ]]
cmp "$TEST_CLI_TEMPLATE" "$a"
export TEST_SCENARIO=repeat
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
[[ "$(cat "$app/active-release")" == b ]]
printf 'corrupt selected fixture\n' > "$b"
export TEST_SCENARIO=destructive-update
before="$(grep -c '^tool install' "$TEST_LOG")"
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
[[ "$(cat "$app/active-release")" == a ]]
[[ "$(tail -1 "$TEST_SELECTED_LOG")" == "$a" ]]
[[ "$(grep -c '^tool install' "$TEST_LOG")" == "$before" ]]
cmp "$TEST_CLI_TEMPLATE" "$a"
printf 'PASS: late startup check and broken active release recover without overwriting backup\n'
export TEST_SCENARIO=policy-rejection
if timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null; then
  echo "Policy failure incorrectly reported success" >&2; exit 1
fi
[[ "$(cat "$app/active-release")" == b ]]
printf 'PASS: runtime policy failure is not an automatic downgrade\n'

# A final startup failure after the old session was drained must restart
# the old release in this same setup command, without publishing the candidate.
export HOME="$work/late-live/home"
export XDG_DATA_HOME="$HOME/data"
export TEST_LOG="$work/late-live/events"
export TEST_SELECTED_LOG="$work/late-live/selected"
export TEST_LATE_CHECK="$work/late-live/late-check"
export TEST_HANDOFF="$work/late-live/control"
mkdir -p "$HOME" "$TEST_HANDOFF"
export TEST_SCENARIO=live-handoff
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null </dev/null &
launcher=$!
for _ in $(seq 1 100); do [[ -s "$TEST_HANDOFF/lease" ]] && break; sleep .05; done
if [[ ! -s "$TEST_HANDOFF/lease" ]]; then
  touch "$TEST_HANDOFF/drain"
  wait "$launcher" || true
  exit 1
fi
app="$XDG_DATA_HOME/KiCadMCPPro"
a="$app/releases/a/bin/kicad-mcp-pro"
export TEST_SCENARIO=late-unhealthy
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
wait "$launcher"
[[ "$(cat "$app/active-release")" == a ]]
[[ "$(tail -1 "$TEST_SELECTED_LOG")" == "$a" ]]
[[ "$(tail -3 "$TEST_LOG")" == "$(printf 'requested\ndrained\nconnected')" ]]
cmp "$TEST_CLI_TEMPLATE" "$a"
printf 'PASS: final candidate failure after drain restarts previous release\n'

# Recovery can also preserve a working legacy installation if both slots
# became unusable. Do not fetch packages or change either damaged slot.
unset TEST_HANDOFF
mkdir -p "$app/bin"
install -m 700 "$TEST_CLI_TEMPLATE" "$app/bin/kicad-mcp-pro"
printf 'broken A\n' > "$a"
printf 'broken B\n' > "$app/releases/b/bin/kicad-mcp-pro"
before="$(grep -c '^tool install' "$TEST_LOG")"
export TEST_SCENARIO=destructive-update
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
[[ ! -e "$app/active-release" ]]
[[ "$(tail -1 "$TEST_SELECTED_LOG")" == "$app/bin/kicad-mcp-pro" ]]
[[ "$(grep -c '^tool install' "$TEST_LOG")" == "$before" ]]
cmp "$TEST_CLI_TEMPLATE" "$app/bin/kicad-mcp-pro"
printf 'PASS: legacy working installation recovered without reinstall\n'

# Recreate the durable checkpoint immediately after successful preparation
# and an interrupted updater. Recovery must not contact the package index
# or overwrite the prepared candidate, even when the network is unavailable.
export HOME="$work/interrupted/home"
export XDG_DATA_HOME="$HOME/data"
export TEST_LOG="$work/interrupted/events"
export TEST_SELECTED_LOG="$work/interrupted/selected"
mkdir -p "$HOME"
app="$XDG_DATA_HOME/KiCadMCPPro"
export TEST_SCENARIO=install
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
a="$app/releases/a/bin/kicad-mcp-pro"
b="$app/releases/b/bin/kicad-mcp-pro"
mkdir -p "$(dirname "$b")"
install -m 700 "$TEST_CLI_TEMPLATE" "$b"
generation="$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
printf 'a b %s\n' "$generation" > "$app/pending-release"
before="$(grep -c '^tool install' "$TEST_LOG")"
export TEST_SCENARIO=offline
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
[[ "$(cat "$app/active-release")" == b ]]
[[ "$(tail -1 "$TEST_SELECTED_LOG")" == "$b" ]]
[[ ! -e "$app/pending-release" ]]
[[ "$(grep -c '^tool install' "$TEST_LOG")" == "$before" ]]
cmp "$TEST_CLI_TEMPLATE" "$a"
cmp "$TEST_CLI_TEMPLATE" "$b"
printf 'PASS: interrupted handoff resumes prepared release offline\n'

# Interruption immediately after selector publication is idempotent.
printf 'a b %s\n' "$generation" > "$app/pending-release"
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
[[ "$(cat "$app/active-release")" == b && ! -e "$app/pending-release" ]]
[[ "$(grep -c '^tool install' "$TEST_LOG")" == "$before" ]]
printf 'PASS: interrupted selector publication reconciles without reinstall\n'

# Malformed journal is not permission to replace either environment.
printf 'a a %s\n' "$generation" > "$app/pending-release"
if timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null; then
  echo 'Malformed pending release was accepted' >&2; exit 1
fi
[[ "$(cat "$app/active-release")" == b ]]
[[ "$(grep -c '^tool install' "$TEST_LOG")" == "$before" ]]
cmp "$TEST_CLI_TEMPLATE" "$a"
cmp "$TEST_CLI_TEMPLATE" "$b"
printf 'PASS: malformed update journal fails closed\n'

# Real process interruption after the fixture receives the drain request.
export HOME="$work/crash-handoff/home"
export XDG_DATA_HOME="$HOME/data"
export TEST_LOG="$work/crash-handoff/events"
export TEST_SELECTED_LOG="$work/crash-handoff/selected"
export TEST_HANDOFF="$work/crash-handoff/control"
mkdir -p "$HOME" "$TEST_HANDOFF"
export TEST_SCENARIO=live-handoff
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null </dev/null &
launcher=$!
for _ in $(seq 1 100); do [[ -s "$TEST_HANDOFF/lease" ]] && break; sleep .05; done
if [[ ! -s "$TEST_HANDOFF/lease" ]]; then
  touch "$TEST_HANDOFF/drain"
  wait "$launcher" || true
  exit 1
fi
app="$XDG_DATA_HOME/KiCadMCPPro"
a="$app/releases/a/bin/kicad-mcp-pro"
b="$app/releases/b/bin/kicad-mcp-pro"
export TEST_SCENARIO=interrupt-handoff
if timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null; then
  echo "Interrupted updater unexpectedly succeeded" >&2; exit 1
fi
wait "$launcher"
[[ "$(cat "$app/active-release")" == a && -f "$app/pending-release" ]]
before="$(grep -c '^tool install' "$TEST_LOG")"
export TEST_SCENARIO=offline
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
[[ "$(cat "$app/active-release")" == b && ! -e "$app/pending-release" ]]
[[ "$(tail -1 "$TEST_SELECTED_LOG")" == "$b" ]]
[[ "$(grep -c '^tool install' "$TEST_LOG")" == "$before" ]]
printf 'PASS: actual updater crash after drain resumes offline\n'

# A journal may belong to an earlier process. Do not drain a new generation
# or a healthy running Connector merely because a saved candidate exists.
export HOME="$work/stale-handoff/home"
export XDG_DATA_HOME="$HOME/data"
export TEST_LOG="$work/stale-handoff/events"
export TEST_SELECTED_LOG="$work/stale-handoff/selected"
export TEST_HANDOFF="$work/stale-handoff/control"
mkdir -p "$HOME" "$TEST_HANDOFF"
export TEST_SCENARIO=live-handoff
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null </dev/null &
launcher=$!
for _ in $(seq 1 100); do [[ -s "$TEST_HANDOFF/lease" ]] && break; sleep .05; done
if [[ ! -s "$TEST_HANDOFF/lease" ]]; then
  touch "$TEST_HANDOFF/drain"
  wait "$launcher" || true
  exit 1
fi
app="$XDG_DATA_HOME/KiCadMCPPro"
b="$app/releases/b/bin/kicad-mcp-pro"
mkdir -p "$(dirname "$b")"
install -m 700 "$TEST_CLI_TEMPLATE" "$b"
printf 'a b %s\n' "$(python3 -c 'import uuid; print(uuid.uuid4().hex)')" > "$app/pending-release"
before="$(grep -c '^tool install' "$TEST_LOG")"
export TEST_SCENARIO=offline
if timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null; then
  touch "$TEST_HANDOFF/drain"; wait "$launcher" || true
  echo "Stale generation was accepted" >&2; exit 1
fi
[[ ! -e "$TEST_HANDOFF/drain" && "$(cat "$app/active-release")" == a ]]
[[ -f "$app/pending-release" ]]
printf 'a b %s\n' "$(cut -d' ' -f1 "$TEST_HANDOFF/lease")" > "$app/pending-release"
printf 'broken candidate\n' > "$b"
if timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null; then
  touch "$TEST_HANDOFF/drain"; wait "$launcher" || true
  echo "Unhealthy saved candidate was accepted" >&2; exit 1
fi
[[ ! -e "$TEST_HANDOFF/drain" && "$(cat "$app/active-release")" == a ]]
[[ "$(grep -c '^tool install' "$TEST_LOG")" == "$before" ]]
touch "$TEST_HANDOFF/drain"
wait "$launcher"
# With no running process, recover the still-healthy old release.
timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
[[ "$(cat "$app/active-release")" == a && ! -e "$app/pending-release" ]]
[[ "$(grep -c '^tool install' "$TEST_LOG")" == "$before" ]]
printf 'PASS: stale generation and unhealthy saved candidate never drain live Connector\n'
