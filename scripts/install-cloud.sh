#!/usr/bin/env bash
# KiCad MCP Pro Cloud: one owner-terminal entry point on macOS and Linux.
# Keeps the Cloud tool separate from the user's other Python installations.
set -euo pipefail
main() {
umask 077
die() { printf 'KiCad MCP Pro: %s\n' "$*" >&2; exit 1; }
case "$(uname -s)" in
  Darwin) root="$HOME/Library/Application Support/KiCadMCPPro"; os=apple-darwin ;;
  Linux) root="${XDG_DATA_HOME:-$HOME/.local/share}/KiCadMCPPro"; os=unknown-linux-gnu ;;
  *) die "Use the Windows setup command in Cloud Devices on Windows." ;;
esac
case "$(uname -m)" in
  x86_64|amd64) arch=x86_64 ;;
  arm64|aarch64) arch=aarch64 ;;
  *) die "This processor is not supported by the Cloud installer." ;;
esac
[[ -t 0 && -t 1 ]] || die "Open a local interactive terminal to connect this computer."
[[ "$root" = /* && ! -L "$root" ]] || die "Invalid local application directory."
mkdir -p "$root"
# A dedicated lock spans the update AND foreground session. Never upgrade a
# running dedicated environment or start a duplicate from this entry point.
lock="$root/installer.lock"
if ! mkdir "$lock" 2>/dev/null; then
  die "Another setup or Connector may already be running. Its installation has not been changed."
fi
tmp=""
cleanup() {
  if [[ -n "$tmp" ]]; then rm -rf -- "$tmp"; fi
  rmdir "$lock" || true
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export UV_TOOL_DIR="$root/uv-tools"
export UV_TOOL_BIN_DIR="$root/bin"
export PATH="$UV_TOOL_BIN_DIR:$PATH"
healthy() { [[ -x "$1" ]] && "$1" --version >/dev/null 2>&1; }
uv_path="$(command -v uv || true)"
if [[ -z "$uv_path" ]] || ! healthy "$uv_path"; then
  uv_path="$root/installer/uv"
fi
if ! healthy "$uv_path"; then
  release=0.13.9
  artifact="uv-$arch-$os.tar.gz"
  case "$artifact" in
    uv-aarch64-apple-darwin.tar.gz) pin=5aeca67f2283f75235de40d0bd9c0a5bbc5fce23b6d48b3bf9fa1b2db08382ca ;;
    uv-x86_64-apple-darwin.tar.gz) pin=617a3211261b0fc739562f0071aa34e9739797c510208ede8e2977c30903d041 ;;
    uv-aarch64-unknown-linux-gnu.tar.gz) pin=0797542018e541a9288855df555c8077eed06f7a47d206362030480e8ecc9f3d ;;
    uv-x86_64-unknown-linux-gnu.tar.gz) pin=a7fbaff2b9a271d85c1bdb540941090fd1ce011797b4abeb48e4dcd39c2471d5 ;;
    *) die "Unsupported installer platform." ;;
  esac
  tmp="$(mktemp -d)"
  printf 'KiCad MCP Pro: Preparing the installer...\n'
  curl --proto '=https' --tlsv1.2 --fail --silent --show-error --location \
    --max-time 90 "https://github.com/astral-sh/uv/releases/download/$release/$artifact" \
    -o "$tmp/uv.tar.gz"
  if command -v sha256sum >/dev/null; then
    actual="$(sha256sum "$tmp/uv.tar.gz")"
  else
    actual="$(shasum -a 256 "$tmp/uv.tar.gz")"
  fi
  [[ "${actual%% *}" == "$pin" ]] || die "Installer download failed integrity verification."
  tar -xzf "$tmp/uv.tar.gz" -C "$tmp" "uv-$arch-$os/uv"
  mkdir -p "$root/installer"
  install -m 700 "$tmp/uv-$arch-$os/uv" "$uv_path"
  healthy "$uv_path" || die "The verified installer could not start."
fi
cli="$UV_TOOL_BIN_DIR/kicad-mcp-pro"
existing=false
if healthy "$cli"; then existing=true; fi
printf 'KiCad MCP Pro: Checking the installed version...\n'
if ! "$uv_path" tool install --upgrade kicad-mcp-pro; then
  if [[ "$existing" == true ]] && healthy "$cli"; then
    printf 'KiCad MCP Pro: Update unavailable; using the existing version.\n' >&2
  else
    "$uv_path" tool install --force --reinstall kicad-mcp-pro || die "Installation could not be repaired."
  fi
fi
if ! healthy "$cli"; then
  "$uv_path" tool install --force --reinstall kicad-mcp-pro || die "Installation could not be repaired."
  healthy "$cli" || die "Installation verification failed."
fi
printf 'KiCad MCP Pro: Opening Cloud Connector...\n'
# The POSIX connector currently supports read-only remote access.
# Do not claim native edit support before its platform implementation exists.
"$cli" cloud
}
# A curl | bash invocation reads code from the pipe; prompts use the owner TTY.
main </dev/tty
