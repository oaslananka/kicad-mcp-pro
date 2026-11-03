"""Persistent, default-off owner-managed Cloud Connector for one local project.

Cloud remains authoritative for OAuth client/project grants and the Devices-page
On/Off switch. Local disable closes the signed socket and fences pending reads.
Only project-presence booleans are supported.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from websockets.exceptions import WebSocketException

from kicad_mcp.cloud_local_registry import (
    LocalRegisteredRead,
    default_registry_root,
    resolve_registered_read,
)
from kicad_mcp.cloud_once import _load_bound_owner_key
from kicad_mcp.cloud_outbound_handshake import (
    CloudHandshakeDeniedError,
    HandshakeReceipt,
    execute_owner_managed_read_session,
)
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError, _open_owner_private_dir
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.cloud_reconnect_policy import reconnect_delay_seconds
from kicad_mcp.cloud_registered_pilot import _single_registered_identity

_SERVICE_NAME = "kicad-mcp-cloud-connector.service"
_ENABLED_FILE = "connector-enabled.json"
_STATUS_FILE = "connector-status.json"
_ENABLED_FIELDS = frozenset({"enabled", "ownerSub", "cloudOrigin", "deviceId", "projectId"})
_STATUS_FIELDS = frozenset({"state", "updatedAtUnixMs", "pid"})
_STATUS_VALUES = frozenset({"connecting", "connected", "unavailable"})
_MAX_STATE_BYTES = 2048
_MAX_READS = 16
_SESSION_LIFETIME_MS = 280_000
_CONNECTED_STATUS_MAX_AGE_MS = 305_000
_CONNECTING_STATUS_MAX_AGE_MS = 45_000
_DENIED = "Registered Cloud Connector unavailable; check its local enable state and registration."


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len({key for key, _ in pairs}) != len(pairs):
        raise LocalApprovalDeniedError(_DENIED)
    return dict(pairs)


def _current_uid() -> int:
    getuid = getattr(os, "getuid", None)
    if not callable(getuid):
        raise LocalApprovalDeniedError(_DENIED)
    uid = getuid()
    if type(uid) is not int:
        raise LocalApprovalDeniedError(_DENIED)
    return uid


def _read_private_json(root: Path, name: str) -> dict[str, Any]:
    folder_fd = _open_owner_private_dir(root / name)
    owner_uid = _current_uid()
    fd = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        fd = os.open(name, flags | getattr(os, "O_CLOEXEC", 0), dir_fd=folder_fd)
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != owner_uid
            or info.st_nlink != 1
            or info.st_mode & 0o077
            or not 1 <= info.st_size <= _MAX_STATE_BYTES
        ):
            raise LocalApprovalDeniedError(_DENIED)
        raw = os.read(fd, _MAX_STATE_BYTES + 1)
        if len(raw) > _MAX_STATE_BYTES:
            raise LocalApprovalDeniedError(_DENIED)
        value = json.loads(raw, object_pairs_hook=_unique)
        if not isinstance(value, dict):
            raise LocalApprovalDeniedError(_DENIED)
        return value
    except (OSError, ValueError, TypeError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc
    finally:
        if fd >= 0:
            os.close(fd)
        os.close(folder_fd)


def _write_private_json(root: Path, name: str, value: dict[str, Any]) -> None:
    folder_fd = _open_owner_private_dir(root / name)
    temp_name = f".{name}.{uuid.uuid4().hex}.tmp"
    fd = -1
    try:
        payload = json.dumps(value, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        if not 1 <= len(payload) <= _MAX_STATE_BYTES:
            raise LocalApprovalDeniedError(_DENIED)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(temp_name, flags, 0o600, dir_fd=folder_fd)
        with os.fdopen(fd, "wb", closefd=True) as stream:
            fd = -1
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, name, src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
        os.fsync(folder_fd)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temp_name, dir_fd=folder_fd)
        except FileNotFoundError:
            pass
        os.close(folder_fd)


def _remove_private_file(root: Path, name: str) -> None:
    folder_fd = _open_owner_private_dir(root / name)
    try:
        try:
            os.unlink(name, dir_fd=folder_fd)
            os.fsync(folder_fd)
        except FileNotFoundError:
            pass
    finally:
        os.close(folder_fd)


def _identity_state(record: dict[str, str]) -> dict[str, Any]:
    return {
        "enabled": True,
        "ownerSub": record["ownerSub"],
        "cloudOrigin": record["cloudOrigin"],
        "deviceId": record["deviceId"],
        "projectId": record["projectId"],
    }


def _enabled_record(root: Path) -> dict[str, Any] | None:
    try:
        value = _read_private_json(root, _ENABLED_FILE)
    except LocalApprovalDeniedError:
        return None
    if (
        value.keys() != _ENABLED_FIELDS
        or value.get("enabled") is not True
        or any(
            not isinstance(value.get(key), str) or not value[key]
            for key in _ENABLED_FIELDS - {"enabled"}
        )
    ):
        return None
    return value


def _is_enabled(root: Path, record: dict[str, str]) -> bool:
    enabled = _enabled_record(root)
    if enabled is None or enabled != _identity_state(record):
        return False
    try:
        current = _single_registered_identity(root)
    except (LocalApprovalDeniedError, OSError, ValueError):
        return False
    return all(
        current.get(key) == record.get(key)
        for key in ("ownerSub", "cloudOrigin", "deviceId", "projectId")
    )


def _write_status(root: Path, state: str) -> None:
    if state not in _STATUS_VALUES:
        raise ValueError("invalid connector status")
    _write_private_json(
        root,
        _STATUS_FILE,
        {
            "state": state,
            "updatedAtUnixMs": time.time_ns() // 1_000_000,
            "pid": os.getpid(),
        },
    )


def _systemctl(*arguments: str) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("systemctl")
    if executable is None:
        raise FileNotFoundError("systemctl is unavailable")
    return subprocess.run(
        [executable, "--user", *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=8,
    )


def _service_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / _SERVICE_NAME


def _systemd_quote(value: str) -> str:
    if not value or any(ord(char) < 32 for char in value):
        raise ValueError("unsupported interpreter path")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def _install_user_service() -> None:
    root = default_registry_root()
    target = _service_path()
    service_dir = target.parent
    service_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    info = service_dir.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != _current_uid() or info.st_mode & 0o022:
        raise LocalApprovalDeniedError(_DENIED)
    unit = (
        "[Unit]\n"
        "Description=KiCad MCP Pro owner-managed Cloud Connector\n"
        f"ConditionPathExists={root / _ENABLED_FILE}\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={_systemd_quote(sys.executable)} -m kicad_mcp.cloud_managed_connector run\n"
        "Restart=on-failure\n"
        "RestartSec=30s\n"
        "TimeoutStopSec=10s\n"
        "KillSignal=SIGTERM\n"
        "UMask=0077\n"
        "NoNewPrivileges=true\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )
    if target.exists() or target.is_symlink():
        if target.is_symlink() or not target.is_file() or target.read_text() != unit:
            raise LocalApprovalDeniedError(_DENIED)
    else:
        temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(unit)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, target)
    if _systemctl("daemon-reload").returncode != 0:
        raise RuntimeError("systemd user manager could not reload the Connector unit")


def _enable() -> int:
    root = default_registry_root()
    record = _single_registered_identity(root)
    # This explicit local enable records only existing selectors. It does not
    # read or sign with the private key; the service does that after activation.
    _write_private_json(root, _ENABLED_FILE, _identity_state(record))
    try:
        _install_user_service()
        result = _systemctl("enable", "--now", _SERVICE_NAME)
        if result.returncode != 0:
            raise RuntimeError("systemd user manager could not start the Connector")
    except Exception:
        _remove_private_file(root, _ENABLED_FILE)
        try:
            _systemctl("disable", "--now", _SERVICE_NAME)
        except OSError:
            pass
        raise
    print("Local Cloud Connector enabled for the single registered project.")
    print("Cloud reads still require the existing Devices-page On switch and OAuth grant.")
    return 0


def _disable() -> int:
    root = default_registry_root()
    marker_removed = True
    # Remove local authority before stopping the process/socket. Even if the
    # private registry is damaged, still stop the service to close its socket.
    try:
        _remove_private_file(root, _ENABLED_FILE)
    except (LocalApprovalDeniedError, OSError):
        marker_removed = False
    try:
        result = _systemctl("disable", "--now", _SERVICE_NAME)
    except (OSError, subprocess.SubprocessError):
        result = None
    stopped = result is not None and result.returncode == 0
    if not stopped:
        try:
            active = _systemctl("is-active", _SERVICE_NAME)
            stopped = active.returncode != 0 and active.stdout.strip() in {
                "inactive",
                "failed",
                "unknown",
            }
        except (OSError, subprocess.SubprocessError):
            stopped = False
    if not stopped or not marker_removed:
        print(
            "Connector shutdown requested; local marker or service stop is unverified.",
            file=sys.stderr,
        )
        return 1
    print("Local Cloud Connector is Off.")
    return 0


def _status() -> str:
    root = default_registry_root()
    marker = root / _ENABLED_FILE
    try:
        marker.lstat()
    except FileNotFoundError:
        return "Off"
    if _enabled_record(root) is None:
        return "Unavailable"
    active = _systemctl("is-active", _SERVICE_NAME)
    if active.returncode != 0 or active.stdout.strip() != "active":
        return "Unavailable"
    try:
        value = _read_private_json(root, _STATUS_FILE)
        state, updated = value.get("state"), value.get("updatedAtUnixMs")
        if (
            value.keys() != _STATUS_FIELDS
            or state not in _STATUS_VALUES
            or type(updated) is not int
            or type(value.get("pid")) is not int
        ):
            return "Unavailable"
        age = time.time_ns() // 1_000_000 - updated
        if state == "connected" and 0 <= age <= _CONNECTED_STATUS_MAX_AGE_MS:
            return "Connected"
        if state == "connecting" and 0 <= age <= _CONNECTING_STATUS_MAX_AGE_MS:
            return "Connecting"
    except LocalApprovalDeniedError:
        return "Unavailable"
    return "Unavailable"


def _dispatcher_factory(
    root: Path, record: dict[str, str], project: LocalRegisteredRead
) -> Callable[[HandshakeReceipt], LocalReadDispatch]:
    def create(receipt: HandshakeReceipt) -> LocalReadDispatch:
        if not _is_enabled(root, record):
            raise LocalApprovalDeniedError(_DENIED)
        # This callback runs only after the authenticated device/session
        # handshake has reached connector.ready.
        _write_status(root, "connected")
        return LocalReadDispatch(
            verified=VerifiedLocalBinding(
                device_id=receipt.device_id,
                project_id=record["projectId"],
                operations=frozenset({"project_summary"}),
                session_id=receipt.session_id,
                session_expires_unix_ms=time.time_ns() // 1_000_000 + _SESSION_LIFETIME_MS,
            ),
            operator_project=OperatorProject(
                device_id=record["deviceId"],
                project_id=record["projectId"],
                directory=project.project_directory,
                filename_stem=project.filename_stem,
            ),
            current_authorization=lambda: _is_enabled(root, record),
            max_reads=_MAX_READS,
            native_drc=False,
        )

    return create


async def _session_until_stopped(
    *,
    stop_event: asyncio.Event,
    root: Path,
    record: dict[str, str],
    project: LocalRegisteredRead,
    signing_key: Ed25519PrivateKey,
    session_runner: Callable[..., Awaitable[HandshakeReceipt]],
) -> None:
    async def run_session() -> HandshakeReceipt:
        return await session_runner(
            origin=record["cloudOrigin"],
            trusted_origin=record["cloudOrigin"],
            owner_sub=record["ownerSub"],
            device_id=record["deviceId"],
            signing_key=signing_key,
            dispatcher_factory=_dispatcher_factory(root, record, project),
            max_reads=_MAX_READS,
        )

    session_task = asyncio.create_task(run_session())
    stop_task = asyncio.create_task(stop_event.wait())
    try:
        done, _ = await asyncio.wait({session_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if stop_task in done:
            session_task.cancel()
            await asyncio.gather(session_task, return_exceptions=True)
            return
        await session_task
    finally:
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)


async def _run_connector(
    *,
    root: Path | None = None,
    stop_event: asyncio.Event | None = None,
    identity_loader: Callable[[Path], dict[str, str]] = _single_registered_identity,
    project_resolver: Callable[..., LocalRegisteredRead] = resolve_registered_read,
    key_loader: Callable[..., Ed25519PrivateKey] = _load_bound_owner_key,
    session_runner: Callable[..., Awaitable[HandshakeReceipt]] = execute_owner_managed_read_session,
) -> int:
    registry = default_registry_root() if root is None else root
    stop = stop_event if stop_event is not None else asyncio.Event()
    if not _enabled_record(registry):
        return 0

    failures = 0
    while not stop.is_set() and _enabled_record(registry):
        try:
            # Revalidate the unique registration and key binding before each
            # reconnect. The key is loaded only after the local enable marker.
            record = identity_loader(registry)
            if not _is_enabled(registry, record):
                break
            project = project_resolver(
                owner_sub=record["ownerSub"],
                origin=record["cloudOrigin"],
                device_id=record["deviceId"],
                project_id=record["projectId"],
                registry_root=registry,
            )
            signing_key = key_loader(project.key_file, record["cloudOrigin"], record["deviceId"])
            # A local disable racing registration/key loading must prevent a
            # new outbound handshake after the owner removes the enable marker.
            if stop.is_set() or not _is_enabled(registry, record):
                break
            _write_status(registry, "connecting")
            await _session_until_stopped(
                stop_event=stop,
                root=registry,
                record=record,
                project=project,
                signing_key=signing_key,
                session_runner=session_runner,
            )
            failures = 0
        except asyncio.CancelledError:
            raise
        except (
            CloudHandshakeDeniedError,
            LocalApprovalDeniedError,
            OSError,
            ValueError,
            WebSocketException,
            TimeoutError,
        ):
            _write_status(registry, "unavailable")
            failures += 1

        if stop.is_set() or not _enabled_record(registry):
            break
        delay = reconnect_delay_seconds(failures, secrets.randbelow(1001) / 1000)
        _write_status(registry, "unavailable")
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            pass

    return 0


async def _run_service() -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        return await _run_connector(stop_event=stop)
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Owner-managed read-only KiCad Cloud Connector")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "enable", help="Enable the registered project and install/start its user service"
    )
    commands.add_parser("disable", help="Fence local reads and stop/disable the user service")
    commands.add_parser("status", help="Show Off, Connecting, Connected, or Unavailable")
    commands.add_parser("run", help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    try:
        if options.command == "enable":
            return _enable()
        if options.command == "disable":
            return _disable()
        if options.command == "status":
            print(_status())
            return 0
        return asyncio.run(_run_service())
    except (
        CloudHandshakeDeniedError,
        LocalApprovalDeniedError,
        OSError,
        RuntimeError,
        ValueError,
        subprocess.SubprocessError,
    ):
        print(_DENIED, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
