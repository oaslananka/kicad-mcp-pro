#!/usr/bin/env bash
# KiCad MCP Pro Cloud: one owner-terminal entry point on macOS and Linux.
# Keeps the Cloud tool separate from the user's other Python installations.
set -euo pipefail
die() { printf 'KiCad MCP Pro: %s\n' "$*" >&2; exit 1; }
healthy() { [[ -x "$1" ]] && "$1" --version >/dev/null 2>&1; }
private_slot() {
  local dir="$1"
  [[ ! -L "$dir" ]] || die "Invalid local installation directory."
  if [[ -e "$dir" ]]; then
    [[ -d "$dir" && -O "$dir" ]] || die "Invalid local installation directory."
  fi
}
connector_healthy() { healthy "$1" && "$1" cloud --help >/dev/null 2>&1; }
select_slot() {
  local slot="$1"
  if [[ "$slot" == legacy ]]; then
    export UV_TOOL_DIR="$root/uv-tools"
    export UV_TOOL_BIN_DIR="$root/bin"
  else
    export UV_TOOL_DIR="$root/releases/$slot/uv-tools"
    export UV_TOOL_BIN_DIR="$root/releases/$slot/bin"
  fi
  private_slot "$UV_TOOL_DIR"
  private_slot "$UV_TOOL_BIN_DIR"
  export PATH="$UV_TOOL_BIN_DIR:$base_path"
  cli="$UV_TOOL_BIN_DIR/kicad-mcp-pro"
}
prepare_release() {
  local active="$1" candidate="$2" old_healthy=false
  private_slot "$root/releases"
  private_slot "$root/releases/a"
  private_slot "$root/releases/b"
  select_slot "$active"
  if connector_healthy "$cli"; then old_healthy=true; fi
  select_slot "$candidate"
  printf 'KiCad MCP Pro: Preparing a separate update...\n'
  if "$uv_path" tool install --upgrade kicad-mcp-pro && connector_healthy "$cli"; then
    return 0
  fi
  if [[ "$old_healthy" == false ]]; then
    printf 'KiCad MCP Pro: Installation needs repair. Retrying once...\n'
    if "$uv_path" tool install --force --reinstall kicad-mcp-pro && connector_healthy "$cli"; then
      return 0
    fi
    return 2
  fi
  return 1
}
verify_release() {
  private_slot "$root/releases"
  if [[ "$1" != legacy ]]; then private_slot "$root/releases/$1"; fi
  select_slot "$1"
  connector_healthy "$cli"
}
launch_release() {
  select_slot "$1"
  connector_healthy "$cli" || die "Existing installation is no longer healthy."
  printf 'KiCad MCP Pro: Opening Cloud Connector...\n'
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
export base_path="$PATH"
export PATH="$UV_TOOL_BIN_DIR:$base_path"
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
export -f die healthy private_slot connector_healthy select_slot prepare_release verify_release launch_release
export root uv_path
# Embedded Python passes literal Bash positional parameters.
# shellcheck disable=SC2016
"$uv_path" run --no-project --no-config --no-env-file --python '>=3.13' -- python -I -c '
import fcntl
import os
import re
import stat
import subprocess
import sys
import time
import uuid

def fail(message):
    raise SystemExit("KiCad MCP Pro: " + message)

root = sys.argv[1]
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
except OSError:
    fail("Cannot verify the local application directory.")

def lock_file(name):
    fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=folder)
    metadata = os.fstat(fd)
    if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid()
            or metadata.st_nlink != 1 or metadata.st_mode & 0o077 or metadata.st_size != 0):
        fail("Invalid installer lock.")
    return fd

def acquire(fd):
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False

def active_slot():
    try:
        fd = os.open("active-release", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
    except FileNotFoundError:
        return "legacy"
    with os.fdopen(fd, "rb") as stream:
        meta = os.fstat(stream.fileno())
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid()
                or meta.st_nlink != 1 or meta.st_mode & 0o077 or meta.st_size > 3):
            fail("Invalid release selection.")
        value = stream.read(4)
    if value not in (b"a", b"a\n", b"b", b"b\n"):
        fail("Invalid release selection.")
    return value.decode().strip()

def control(slot, *args):
    if slot not in ("a", "b"):
        return None
    path = os.path.join(root, "releases", slot, "bin", "kicad-mcp-pro")
    try:
        for directory in (os.path.join(root, "releases"), os.path.join(root, "releases", slot),
                          os.path.dirname(path)):
            meta = os.lstat(directory)
            if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != os.getuid() or meta.st_mode & 0o022:
                return None
        result = subprocess.run([path, "cloud", "_update-control", *args],
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=8)
        if result.returncode == 0:
            return result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired, UnicodeError):
        pass
    return None

def write_marker(destination, value):
    name = "." + destination + "." + uuid.uuid4().hex
    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write((value + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, destination, src_dir_fd=folder, dst_dir_fd=folder)
        os.fsync(folder)
    finally:
        try:
            os.unlink(name, dir_fd=folder)
        except FileNotFoundError:
            pass

def publish(slot):
    write_marker("active-release", slot)

def pending_release():
    try:
        fd = os.open("pending-release", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "rb") as stream:
        meta = os.fstat(stream.fileno())
        if (not stat.S_ISREG(meta.st_mode) or meta.st_uid != os.getuid()
                or meta.st_nlink != 1 or meta.st_mode & 0o077 or meta.st_size != 37):
            fail("Invalid saved update. Existing releases unchanged.")
        value = stream.read(38)
    match = re.fullmatch(rb"([ab]) ([ab]) ([0-9a-f]{32})\n", value)
    if match is None or match[1] == match[2]:
        fail("Invalid saved update. Existing releases unchanged.")
    return tuple(part.decode() for part in match.groups())

def clear_pending():
    os.unlink("pending-release", dir_fd=folder)
    os.fsync(folder)

def finish_handoff(old, candidate, generation):
    if not acquire(session):
        current = control(old, "probe")
        expected = generation + " " + old
        if current is not None and current != expected:
            fail("A different Connector session is running. Saved update preserved.")
        if current == expected:
            accepted = control(old, "request", "--generation", generation, "--slot", old)
            if accepted is None and not acquire(session):
                # The old process may be between lease removal and lock release.
                current = control(old, "probe")
                if current is not None:
                    fail("The running Connector did not accept the saved update request.")
        print("KiCad MCP Pro: Finishing the current Cloud operation before updating...", flush=True)
        deadline = time.monotonic() + 300
        while not acquire(session):
            if time.monotonic() >= deadline:
                fail("The previous Connector is still finishing. Retry the same setup; no process was killed.")
            time.sleep(0.2)
    if active_slot() not in (old, candidate):
        fail("The active release changed. Saved update preserved.")
    if verify(candidate):
        publish(candidate)
        selected = candidate
    elif verify(old):
        print("KiCad MCP Pro: Candidate failed its final startup check; using the previous version.", file=sys.stderr)
        publish(old)
        selected = old
    else:
        fail("Neither installation passed the final startup check. Saved update preserved.")
    clear_pending()
    return selected


def verify(slot):
    return subprocess.run(
        ["/bin/bash", "-c", "set -euo pipefail; verify_release \"$1\"", "verify-release", slot],
        pass_fds=(prepare, session)
    ).returncode == 0

def restore_previous(slot):
    # An absent selector is the legacy layout. Do not overwrite a working
    # backup just because the selected environment is damaged.
    if slot == "legacy":
        os.unlink("active-release", dir_fd=folder)
        os.fsync(folder)
    else:
        publish(slot)


try:
    # One process may prepare a release, while the existing launcher retains
    # the separate session lock. Older launchers without a live lease fail closed.
    prepare = lock_file("installer-prepare.lock")
    if not acquire(prepare):
        fail("Another setup is preparing an update. Existing installation unchanged.")
    session = lock_file("installer-v2.lock")
    owned = acquire(session)
    active = active_slot()
    pending = pending_release()
    if pending is not None:
        old, candidate, generation = pending
        if active not in (old, candidate) or (active == candidate and not owned):
            fail("Saved update conflicts with the active session. Existing releases unchanged.")
        print("KiCad MCP Pro: Resuming the prepared update without reinstalling...", flush=True)
        if not owned and not verify(candidate):
            fail("Saved candidate is no longer healthy. No new stop request was sent.")
        selected = finish_handoff(old, candidate, generation)
    else:
        lease = None
        if not owned:
            lease = control(active, "probe")
            if lease is None or re.fullmatch(r"[0-9a-f]{32} " + active, lease) is None:
                fail("Another setup or Connector is running. Its installation has not been changed.")
        candidate = "b" if active == "a" else "a"
        recovery = None
        if owned and active != "legacy" and not verify(active):
            if verify(candidate):
                recovery = candidate
            elif verify("legacy"):
                recovery = "legacy"
        if recovery is not None:
            restore_previous(recovery)
            print("KiCad MCP Pro: Restored the previous working installation without upgrading it.", file=sys.stderr)
            selected = recovery
        else:
            rc = subprocess.run(["/bin/bash", "-c", "set -euo pipefail; prepare_release \"$1\" \"$2\"",
                                 "prepare-release", active, candidate], pass_fds=(prepare, session)).returncode
            if rc != 0:
                if not owned:
                    fail("Update unavailable; the existing Connector was not asked to stop.")
                if rc != 1:
                    fail("Installation could not be repaired. Existing files were preserved.")
                print("KiCad MCP Pro: Update unavailable; using the existing version.", file=sys.stderr)
                selected = active
            else:
                if not owned:
                    if active_slot() != active:
                        fail("The active release changed during preparation. Retry the same setup.")
                    if not acquire(session) and control(active, "probe") != lease:
                        fail("The running session changed. Retry the same setup.")
                    assert lease is not None
                    generation, slot = lease.split()
                    if slot != active:
                        fail("Invalid update lease.")
                    # Durable intent must precede the first drain request.
                    write_marker("pending-release", active + " " + candidate + " " + generation)
                    selected = finish_handoff(active, candidate, generation)
                else:
                    if active_slot() != active:
                        fail("The active release changed. Retry the same setup.")
                    # Revalidate after the old process has released its lock, before
                    # committing selection. Never interpret a Cloud operation error
                    # as a package startup failure or retry an ambiguous operation.
                    if verify(candidate):
                        publish(candidate)
                        selected = candidate
                    elif verify(active):
                        print("KiCad MCP Pro: Candidate failed its final startup check; using the previous version.", file=sys.stderr)
                        selected = active
                    else:
                        fail("Neither installation passed the final startup check. Existing files were preserved.")
    # Keep session lock across the new foreground child, release preparation
    # lock so the next setup may safely stage the inactive version.
    os.environ["KICAD_CLOUD_UPDATE_GENERATION"] = uuid.uuid4().hex
    os.environ["KICAD_CLOUD_UPDATE_SLOT"] = selected
    os.set_inheritable(session, True)
    os.close(prepare)
    os.close(folder)
    os.execv("/bin/bash", ["bash", "-c", "set -euo pipefail; launch_release \"$1\"", "launch-release", selected])
except OSError:
    fail("Cannot complete the local update safely. Existing registration was preserved.")

' "$root"
}
# A curl | bash invocation reads code from the pipe; prompts use the owner TTY.
main </dev/tty
