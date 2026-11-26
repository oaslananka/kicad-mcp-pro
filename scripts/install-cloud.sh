#!/usr/bin/env bash
# KiCad MCP Pro Cloud: one owner-terminal entry point on macOS and Linux.
# Keeps the Cloud tool separate from the user's other Python installations.
set -euo pipefail
die() { printf 'KiCad MCP Pro: %s\n' "$*" >&2; exit 1; }
healthy() { [[ -x "$1" ]] && "$1" --version >/dev/null 2>&1; }
install_and_connect() {
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
# The installed version determines supported signed-session capabilities.
"$cli" cloud
}
main() {
umask 077
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
[[ -O "$root" && ! -L "$root" ]] || die "Invalid local application directory."
# An older launcher uses a directory with no verifiable ownership token.
# Do not remove it or update an installation it might still be using.
[[ ! -e "$root/installer.lock" && ! -L "$root/installer.lock" ]] ||
  die "An older setup or Connector may still be running. No installation files were changed."
tmp=""
cleanup() {
  if [[ -n "$tmp" ]]; then rm -rf -- "$tmp"; fi
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
export UV_NO_CONFIG=1
export UV_TOOL_DIR="$root/uv-tools"
export UV_TOOL_BIN_DIR="$root/bin"
export PATH="$UV_TOOL_BIN_DIR:$PATH"
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
  [[ -O "$root/installer" && ! -L "$root/installer" ]] || die "Invalid installer directory."
  # The same verified bytes may be prepared by two first-run processes.
  # Publish atomically, rather than truncating a potentially running uv.
  staged_uv="$(mktemp "$root/installer/.uv.XXXXXXXX")"
  install -m 700 "$tmp/uv-$arch-$os/uv" "$staged_uv"
  mv -f -- "$staged_uv" "$uv_path"
  healthy "$uv_path" || die "The verified installer could not start."
fi

# uv can supply Python on macOS as well as Linux without Xcode or a separate
# prerequisite command. Keep an inherited kernel lock over both uv's package
# update and the foreground child; never unlink the lock inode.
export -f die healthy install_and_connect
export root uv_path
"$uv_path" run --no-project --no-config --no-env-file --python '>=3.13' -- python -I -c '
import fcntl
import os
import stat
import sys

def fail(message):
    raise SystemExit("KiCad MCP Pro: " + message)

root = sys.argv[1]
try:
    # Pin every ancestor without following symlinks. Require the dedicated
    # application directory and lock file to belong only to this user.
    folder = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in root.split("/")[1:]:
            if not part or part in (".", ".."):
                fail("Invalid local application directory.")
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=folder)
            os.close(folder)
            folder = child
        info = os.fstat(folder)
        if info.st_uid != os.getuid() or info.st_mode & 0o077:
            fail("The local application directory is not private.")
        fd = os.open("installer-v2.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,
                     0o600, dir_fd=folder)
        metadata = os.fstat(fd)
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
                or metadata.st_nlink != 1 or metadata.st_mode & 0o077 or metadata.st_size != 0):
            fail("Invalid installer lock.")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        os.close(folder)
except BlockingIOError:
    fail("Another setup or Connector is running. Its installation has not been changed.")
except OSError:
    fail("Cannot verify the local installer lock. No package files were changed.")
os.set_inheritable(fd, True)
os.execv("/bin/bash", ["bash", "-c", "set -euo pipefail; install_and_connect"])
' "$root"
}
# A curl | bash invocation reads code from the pipe; prompts use the owner TTY.
main </dev/tty
