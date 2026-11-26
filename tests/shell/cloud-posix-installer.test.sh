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
if [[ "$1" == --version ]]; then exit 0; fi
[[ "$*" == cloud && -t 0 ]] || exit 97
echo connected >> "$TEST_LOG"
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
mkdir -p "$UV_TOOL_BIN_DIR"
cp "$TEST_CLI_TEMPLATE" "$UV_TOOL_BIN_DIR/kicad-mcp-pro"
chmod 700 "$UV_TOOL_BIN_DIR/kicad-mcp-pro"
UV
chmod 700 "$work/bin/uv"
export PATH="$work/bin:$PATH"
for TEST_SCENARIO in install repeat offline running kernel-running stale-kernel; do
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
