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
CLI
mkdir "$work/bin"
cat > "$work/bin/uv" <<'UV'
#!/bin/bash
if [[ "$1" == --version ]]; then exit 0; fi
echo "$*" >> "$TEST_LOG"
if [[ "$TEST_SCENARIO" == offline ]]; then exit 1; fi
mkdir -p "$UV_TOOL_BIN_DIR"
cp "$TEST_CLI_TEMPLATE" "$UV_TOOL_BIN_DIR/kicad-mcp-pro"
chmod 700 "$UV_TOOL_BIN_DIR/kicad-mcp-pro"
UV
chmod 700 "$work/bin/uv"
export PATH="$work/bin:$PATH"
for TEST_SCENARIO in install repeat offline running; do
  export TEST_SCENARIO
  export HOME="$work/$TEST_SCENARIO/home"
  export XDG_DATA_HOME="$HOME/data"
  export TEST_LOG="$work/$TEST_SCENARIO/events"
  app="$XDG_DATA_HOME/KiCadMCPPro"
  mkdir -p "$app/bin"
  if [[ "$TEST_SCENARIO" != install ]]; then
    install -m 700 "$TEST_CLI_TEMPLATE" "$app/bin/kicad-mcp-pro"
  fi
  if [[ "$TEST_SCENARIO" == running ]]; then
    mkdir "$app/installer.lock"
    if timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null; then
      echo "Duplicate installer was not blocked" >&2
      exit 1
    fi
    [[ ! -e "$TEST_LOG" && -d "$app/installer.lock" ]]
  else
    timeout 20s script -qec "cat \"\$TEST_INSTALLER\" | bash" /dev/null
    printf 'tool install --upgrade kicad-mcp-pro\nconnected\n' > "$work/expected"
    diff -u "$work/expected" "$TEST_LOG"
    [[ ! -e "$app/installer.lock" ]]
  fi
  printf 'PASS: %s\n' "$TEST_SCENARIO"
done
