"""Persistent, default-off owner-managed Cloud Connector for one local project.

Cloud remains authoritative for OAuth client/project grants and the Devices-page
On/Off switch. Local disable closes the signed socket and fences pending reads.
Only project-presence booleans are supported.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
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
    HandshakeReceipt,
    execute_owner_managed_read_session,
)
from kicad_mcp.cloud_pair_keys import (
    LocalApprovalDeniedError,
    _current_uid,
    _open_owner_private_dir,
    _read_private_json,
    _write_private_json,
)
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.cloud_reconnect_policy import reconnect_delay_seconds
from kicad_mcp.cloud_registered_pilot import _single_registered_identity

_SERVICE_NAME = "kicad-mcp-cloud-connector.service"
_ENABLED_FILE = "connector-enabled.json"
_FOREGROUND_FILE = "connector-foreground.json"
_STATUS_FILE = "connector-status.json"
_SESSION_LOCK_FILE = "connector-session.lock"
_ENABLED_FIELDS = frozenset({"enabled", "ownerSub", "cloudOrigin", "deviceId", "projectId"})
_FOREGROUND_FIELDS = _ENABLED_FIELDS | {"keySlot", "directory", "filenameStem"}
_STATUS_FIELDS = frozenset({"state", "updatedAtUnixMs", "pid"})
_STATUS_VALUES = frozenset({"connecting", "connected", "unavailable"})
_MAX_READS = 16
_LOCAL_AUTHORITY_POLL_SECONDS = 1.0
_FOREGROUND_SHUTDOWN_TIMEOUT = 5.0
_SESSION_LIFETIME_MS = 280_000
_CONNECTED_STATUS_MAX_AGE_MS = 305_000
_CONNECTING_STATUS_MAX_AGE_MS = 45_000
_DENIED = "Registered Cloud Connector unavailable; check its local enable state and registration."


class ProjectSelectionMissingError(LocalApprovalDeniedError):
    """Cloud confirmed the selected transport anchor no longer exists."""


class ConnectorAlreadyRunningError(RuntimeError):
    """A different local process owns the Connector session."""


@contextmanager
def _connector_session_lock(
    root: Path, *, create: bool = True, name: str = _SESSION_LOCK_FILE
) -> Iterator[None]:
    """Hold one private, nonblocking POSIX process lock for the whole session loop."""
    if sys.platform == "win32":
        raise LocalApprovalDeniedError(_DENIED)
    import fcntl

    folder_fd = _open_owner_private_dir(root / name)
    try:
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        if create:
            flags |= os.O_CREAT
        fd = os.open(
            name,
            flags,
            0o600,
            dir_fd=folder_fd,
        )
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != _current_uid()
                or info.st_nlink != 1
                or info.st_mode & 0o077
                or info.st_size != 0
            ):
                raise LocalApprovalDeniedError(_DENIED)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ConnectorAlreadyRunningError(
                    "A local Cloud Connector is already running. Stop it before reconnecting."
                ) from exc
            yield
        finally:
            # Keep the lock inode: unlinking would let competing processes lock
            # different files. The kernel releases ownership on close or exit.
            os.close(fd)
    finally:
        os.close(folder_fd)


def _session_lock_held(root: Path, *, name: str = _SESSION_LOCK_FILE) -> bool:
    """Do not report cached connection state without a live lock owner."""
    try:
        with _connector_session_lock(root, create=False, name=name):
            return False
    except ConnectorAlreadyRunningError:
        return True
    except (OSError, ValueError):
        return False


def _remove_private_file(root: Path, name: str) -> None:
    if os.name == "nt":
        try:
            (root / name).unlink(missing_ok=True)
        except OSError:
            pass
        return
    folder_fd = _open_owner_private_dir(root / name)
    try:
        try:
            os.unlink(name, dir_fd=folder_fd)
            os.fsync(folder_fd)
        except FileNotFoundError:
            pass
    finally:
        os.close(folder_fd)


def _identity_state(record: dict[str, str], marker: str = _ENABLED_FILE) -> dict[str, Any]:
    state: dict[str, Any] = {
        "enabled": True,
        "ownerSub": record["ownerSub"],
        "cloudOrigin": record["cloudOrigin"],
        "deviceId": record["deviceId"],
        "projectId": record["projectId"],
    }
    if marker == _FOREGROUND_FILE:
        state.update({field: record[field] for field in _FOREGROUND_FIELDS - _ENABLED_FIELDS})
    return state


def _enabled_record(root: Path, marker: str = _ENABLED_FILE) -> dict[str, Any] | None:
    try:
        value = _read_private_json(root, marker)
    except LocalApprovalDeniedError:
        return None
    fields = _FOREGROUND_FIELDS if marker == _FOREGROUND_FILE else _ENABLED_FIELDS
    if (
        value.keys() != fields
        or value.get("enabled") is not True
        or any(
            not isinstance(value.get(key), str) or not value[key] for key in fields - {"enabled"}
        )
    ):
        return None
    return value


def _is_enabled(root: Path, record: dict[str, str], marker: str = _ENABLED_FILE) -> bool:
    if marker == _FOREGROUND_FILE and os.path.lexists(root / _ENABLED_FILE):
        return False
    enabled = _enabled_record(root, marker)
    if enabled is None or enabled != _identity_state(record, marker):
        return False
    try:
        current = _single_registered_identity(root)
    except (OSError, ValueError):
        return False
    return enabled == _identity_state(current, marker)


@contextmanager
def _local_session_authority(
    root: Path,
    foreground: bool,
    identity_loader: Callable[[Path], dict[str, str]],
    expected_identity: dict[str, str] | None = None,
) -> Iterator[str]:
    """Only an explicitly started foreground runner can create temporary authority."""
    # Called with exclusive session ownership. A crashed foreground marker
    # never grants the managed runner authority and can safely be discarded.
    if not foreground:
        _remove_private_file(root, _FOREGROUND_FILE)
        yield _ENABLED_FILE
        return
    if os.path.lexists(root / _ENABLED_FILE):
        raise ConnectorAlreadyRunningError(
            "A background Cloud Connector is enabled. Disable it before foreground connect."
        )
    record = identity_loader(root)
    if expected_identity is not None and record != expected_identity:
        raise LocalApprovalDeniedError("Cloud registration changed; review it before reconnecting.")
    _write_status(root, "unavailable")
    _write_private_json(root, _FOREGROUND_FILE, _identity_state(record, _FOREGROUND_FILE))
    try:
        yield _FOREGROUND_FILE
    finally:
        _remove_private_file(root, _FOREGROUND_FILE)


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
    # The CLI-owned Connector lifecycle below is systemd-only. Do not write
    # an enabled marker on Windows/macOS and then fail to spawn a service.
    if os.name != "posix" or sys.platform == "darwin":
        raise RuntimeError("Cloud Connector background service is unsupported on this platform.")
    root = default_registry_root()
    # Publish persistent authority only when no other runner owns the session.
    # Release the lock before starting systemd: its child must acquire it.
    with _connector_session_lock(root):
        record = _single_registered_identity(root)
        _write_private_json(root, _ENABLED_FILE, _identity_state(record))
    try:
        _install_user_service()
        result = _systemctl("enable", "--now", _SERVICE_NAME)
        if result.returncode != 0:
            raise RuntimeError("systemd user manager could not start the Connector")
        if not _is_enabled(root, record):
            raise LocalApprovalDeniedError("Connector authorization changed during startup.")
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


def _revoke_local_authority(root: Path) -> bool:
    removed = True
    for marker in (_ENABLED_FILE, _FOREGROUND_FILE):
        try:
            _remove_private_file(root, marker)
        except (LocalApprovalDeniedError, OSError):
            removed = False
    return removed


def _wait_for_foreground_shutdown(root: Path) -> bool:
    deadline = time.monotonic() + _FOREGROUND_SHUTDOWN_TIMEOUT
    while True:
        try:
            with _connector_session_lock(root, create=False):
                return True
        except FileNotFoundError:
            return True
        except ConnectorAlreadyRunningError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.05)
        except (OSError, ValueError):
            return False


def _systemd_service_stopped() -> bool:
    """Confirm systemd stopped even if disable itself failed."""
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
    return stopped


def _disable_foreground_session(root: Path, marker_removed: bool) -> int:
    """Report Off only after local revocation and foreground lock release."""
    if marker_removed and _wait_for_foreground_shutdown(root):
        print("Local Cloud Connector is Off.")
        return 0
    print("Connector shutdown requested; local stop is unverified.", file=sys.stderr)
    return 1


def _disable() -> int:
    root = default_registry_root()
    foreground_only = os.path.lexists(root / _FOREGROUND_FILE) and not os.path.lexists(
        root / _ENABLED_FILE
    )
    # Remove local authority before stopping the process/socket. Even if the
    # registry is damaged, still stop an installed service to close its socket.
    marker_removed = _revoke_local_authority(root)
    if sys.platform == "darwin" or foreground_only:
        return _disable_foreground_session(root, marker_removed)
    stopped = _systemd_service_stopped()
    if not stopped or not marker_removed or not _wait_for_foreground_shutdown(root):
        print(
            "Connector shutdown requested; local marker or service stop is unverified.",
            file=sys.stderr,
        )
        return 1
    print("Local Cloud Connector is Off.")
    return 0


def _foreground_connection_status(root: Path) -> str:
    """Trust a cached foreground status only with its current owner and lock."""
    if _enabled_record(root, _FOREGROUND_FILE) is None or not _session_lock_held(root):
        return "Off"
    try:
        record = _single_registered_identity(root)
    except (OSError, ValueError):
        return "Unavailable"
    if not _is_enabled(root, record, _FOREGROUND_FILE):
        return "Unavailable"
    return _cached_connection_status(root)


def _status() -> str:
    root = default_registry_root()
    marker = root / _ENABLED_FILE
    if os.name != "posix":
        return "Unavailable" if marker.exists() else "Off"
    if not os.path.lexists(marker):
        return _foreground_connection_status(root)
    if sys.platform == "darwin":
        return "Unavailable"
    if _enabled_record(root) is None or not _session_lock_held(root):
        return "Unavailable"
    active = _systemctl("is-active", _SERVICE_NAME)
    if active.returncode != 0 or active.stdout.strip() != "active":
        return "Unavailable"
    return _cached_connection_status(root)


def _cached_connection_status(root: Path) -> str:
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


def _report_foreground(marker: str, message: str) -> None:
    if marker == _FOREGROUND_FILE:
        try:
            print(message, flush=True)
        except OSError:
            pass  # Terminal diagnostics must not invalidate a signed response.


def _dispatcher_factory(
    root: Path, record: dict[str, str], project: LocalRegisteredRead, marker: str = _ENABLED_FILE
) -> Callable[[HandshakeReceipt], LocalReadDispatch]:
    def create(receipt: HandshakeReceipt) -> LocalReadDispatch:
        if not _is_enabled(root, record, marker):
            raise LocalApprovalDeniedError(_DENIED)

        def resolve_bound_project(project_id: str) -> OperatorProject | None:
            """Read only an owner-selected, current local Cloud project mapping."""
            if not _is_enabled(root, record, marker):
                return None
            if marker == _FOREGROUND_FILE:
                from kicad_mcp.cloud_posix_project_bindings import resolve_secondary

                return resolve_secondary(root, record, project_id)
            from kicad_mcp.cloud_folder_browse_receiver import default_bindings_file
            from kicad_mcp.cloud_local_folder_browser import LocalFolderBrowser

            browser = LocalFolderBrowser(
                [project.project_directory.parent], default_bindings_file()
            )
            selected_path = browser.get_project_path(project_id)
            if selected_path is None:
                return None
            file = Path(selected_path)
            return OperatorProject(
                device_id=record["deviceId"],
                project_id=project_id,
                directory=file.parent,
                filename_stem=file.stem,
            )

        # This callback runs only after the authenticated device/session
        # handshake has reached connector.ready.
        dispatcher = LocalReadDispatch(
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
            current_authorization=lambda: _is_enabled(root, record, marker),
            project_resolver=resolve_bound_project,
            max_reads=_MAX_READS,
            native_drc=False,
        )
        _write_status(root, "connected")
        _report_foreground(marker, "Connected")
        return dispatcher

    return create


def _posix_mcp_settings(
    root: Path,
    record: dict[str, str],
    project: LocalRegisteredRead,
    marker: str,
) -> dict[str, Any]:
    """Owner foreground only; use the same signed worker as Windows."""
    if marker != _FOREGROUND_FILE:
        return {}
    from kicad_mcp.cloud_generic_mcp_transport import GenericProjectMcpService
    from kicad_mcp.cloud_outbound_handshake import ManagedNativeWriteConfig
    from kicad_mcp.cloud_windows_write_issuer import (
        _KICAD_CLOUD_ORIGIN,
        load_bundled_cloud_issuer,
    )
    from kicad_mcp.cloud_write_marker import LocalWriteMarker

    def authorized() -> bool:
        return _is_enabled(root, record, marker)

    if not authorized():
        raise LocalApprovalDeniedError(_DENIED)
    official = record["cloudOrigin"] == _KICAD_CLOUD_ORIGIN
    issuer = load_bundled_cloud_issuer(record["cloudOrigin"]) if official else None
    replay = None
    if issuer is not None:
        root_fd = _open_owner_private_dir(root / _SESSION_LOCK_FILE)
        try:
            try:
                os.mkdir("write-markers", mode=0o700, dir_fd=root_fd)
            except FileExistsError:
                pass
        finally:
            os.close(root_fd)
        directory = root / "write-markers"
        fd = _open_owner_private_dir(directory / "probe")
        os.close(fd)
        replay = LocalWriteMarker(directory)

    def resolve(project_id: str) -> OperatorProject | None:
        if not authorized():
            return None
        if project_id != record["projectId"]:
            from kicad_mcp.cloud_posix_project_bindings import resolve_secondary

            return resolve_secondary(root, record, project_id)
        return OperatorProject(
            record["deviceId"], project_id, project.project_directory, project.filename_stem
        )

    def factory(receipt: HandshakeReceipt) -> GenericProjectMcpService:
        if receipt.device_id != record["deviceId"] or not authorized():
            raise LocalApprovalDeniedError(_DENIED)
        return GenericProjectMcpService(
            receipt=receipt,
            local_project=resolve,
            current_authorization=authorized,
            allow_native_write=issuer is not None,
            trusted_issuer_key=issuer,
            consume_once=replay.consume_once if replay is not None else None,
        )

    # The legacy native offer and generic write worker share the same pin,
    # project, replay fence and live local authorization.
    options: dict[str, Any] = {"mcp_bridge_factory": factory}
    if issuer is not None and replay is not None:
        from kicad_mcp.cloud_native_write_dispatch import (
            execute_verified_signed_pcb_move,
            prepare_native_write_revisions,
        )
        from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

        receipts: list[HandshakeReceipt] = []

        def with_receipt(receipt: HandshakeReceipt) -> GenericProjectMcpService:
            service = factory(receipt)
            receipts[:] = [receipt]
            return service

        def target(project_id: str) -> OperatorProject:
            resolved = resolve(project_id)
            if resolved is None:
                raise LocalWriteDeniedError(_DENIED)
            return resolved

        def prepare(project_id: str) -> dict[str, str]:
            selected = target(project_id)

            def current() -> bool:
                return authorized() and resolve(project_id) == selected

            return prepare_native_write_revisions(
                selected, authorized=current, cancelled=lambda: not current()
            )

        def execute(project_id: str, proof: bytes, persist: bool) -> dict[str, object]:
            if not receipts:
                raise LocalWriteDeniedError(_DENIED)
            selected = target(project_id)

            def current() -> bool:
                return authorized() and resolve(project_id) == selected

            return execute_verified_signed_pcb_move(
                proof,
                issuer_key=issuer,
                verified=VerifiedLocalBinding(
                    device_id=record["deviceId"],
                    project_id=project_id,
                    operations=frozenset({"pcb_move_footprint"}),
                    session_id=receipts[0].session_id,
                    session_expires_unix_ms=time.time_ns() // 1_000_000 + _SESSION_LIFETIME_MS,
                ),
                operator_project=selected,
                consume_once=replay.consume_once,
                authorized=current,
                cancelled=lambda: not current(),
                persist_to_disk=persist,
            )

        options.update(
            mcp_bridge_factory=with_receipt,
            native_write=ManagedNativeWriteConfig(
                revisions_preparer=prepare, write_executor=execute
            ),
        )
    return options


async def _wait_for_local_stop(
    stop: asyncio.Event, root: Path, record: dict[str, str], marker: str
) -> None:
    """Close idle as well as active sessions when local authority is removed."""
    while not stop.is_set():
        if not _is_enabled(root, record, marker):
            stop.set()
            return
        try:
            await asyncio.wait_for(stop.wait(), timeout=_LOCAL_AUTHORITY_POLL_SECONDS)
        except TimeoutError:
            continue


async def _session_until_stopped(
    *,
    stop_event: asyncio.Event,
    root: Path,
    record: dict[str, str],
    project: LocalRegisteredRead,
    signing_key: Ed25519PrivateKey,
    session_runner: Callable[..., Awaitable[HandshakeReceipt]],
    marker: str,
    drain: asyncio.Event | None = None,
) -> None:
    async def run_session() -> HandshakeReceipt:
        options = {
            "origin": record["cloudOrigin"],
            "trusted_origin": record["cloudOrigin"],
            "owner_sub": record["ownerSub"],
            "device_id": record["deviceId"],
            "signing_key": signing_key,
            "dispatcher_factory": _dispatcher_factory(root, record, project, marker),
            "max_reads": _MAX_READS,
        }
        if session_runner is execute_owner_managed_read_session:
            from kicad_mcp.cloud_folder_browse_receiver import (
                LocalFolderBrowseService,
                device_folder_service,
            )

            def folder_factory(receipt: HandshakeReceipt) -> LocalFolderBrowseService:
                if receipt.device_id != record["deviceId"] or not _is_enabled(root, record, marker):
                    raise LocalApprovalDeniedError(_DENIED)
                if marker == _FOREGROUND_FILE:
                    from kicad_mcp.cloud_posix_project_bindings import folder_service

                    return folder_service(
                        root, record, project, lambda: _is_enabled(root, record, marker)
                    )
                return device_folder_service(
                    project.project_directory,
                    authorization=lambda: _is_enabled(root, record, marker),
                )

            options["folder_service_factory"] = folder_factory
            if marker == _FOREGROUND_FILE:
                options["on_activity"] = lambda message: _report_foreground(marker, message)
                options.update(_posix_mcp_settings(root, record, project, marker))
                if drain is not None:
                    options["drain"] = drain
        return await session_runner(**options)

    session_task = asyncio.create_task(run_session())
    stop_task = asyncio.create_task(_wait_for_local_stop(stop_event, root, record, marker))
    try:
        done, _ = await asyncio.wait({session_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
        if stop_task in done:
            return
        await session_task
    finally:
        # A cancelled caller must also close its transport before releasing
        # session ownership. This covers stop signals and task cancellation.
        for task in (session_task, stop_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(session_task, stop_task, return_exceptions=True)


async def _run_registered_session(
    *,
    registry: Path,
    stop: asyncio.Event,
    identity_loader: Callable[[Path], dict[str, str]],
    project_resolver: Callable[..., LocalRegisteredRead],
    key_loader: Callable[..., Ed25519PrivateKey],
    session_runner: Callable[..., Awaitable[HandshakeReceipt]],
    marker: str,
    drain: asyncio.Event | None = None,
) -> bool:
    # Revalidate the unique registration and key binding before each reconnect.
    record = identity_loader(registry)
    if not _is_enabled(registry, record, marker):
        return False
    project = project_resolver(
        owner_sub=record["ownerSub"],
        origin=record["cloudOrigin"],
        device_id=record["deviceId"],
        project_id=record["projectId"],
        registry_root=registry,
    )
    signing_key = key_loader(project.key_file, record["cloudOrigin"], record["deviceId"])
    # A local disable racing registration/key loading must prevent a new
    # outbound handshake after the owner removes the enable marker.
    if (
        stop.is_set()
        or (drain is not None and drain.is_set())
        or not _is_enabled(registry, record, marker)
    ):
        return False
    if marker == _FOREGROUND_FILE and session_runner is execute_owner_managed_read_session:
        from kicad_mcp.cloud_device_inventory_status import inspect_inventory
        from kicad_mcp.cloud_windows_write_issuer import _KICAD_CLOUD_ORIGIN

        if record["cloudOrigin"] == _KICAD_CLOUD_ORIGIN:
            inventory_state = await asyncio.to_thread(
                inspect_inventory,
                record["cloudOrigin"],
                record["ownerSub"],
                record["deviceId"],
                record["projectId"],
                signing_key,
            )
            if (
                stop.is_set()
                or (drain is not None and drain.is_set())
                or not _is_enabled(registry, record, marker)
            ):
                return False
            if inventory_state == "project_missing":
                raise ProjectSelectionMissingError(_DENIED)
            if inventory_state in {"active", "project_disabled"}:
                from kicad_mcp.cloud_posix_project_bindings import migrate_legacy

                await asyncio.to_thread(
                    migrate_legacy,
                    registry,
                    record,
                    signing_key,
                    lambda: not stop.is_set() and _is_enabled(registry, record, marker),
                )
                if (
                    stop.is_set()
                    or (drain is not None and drain.is_set())
                    or not _is_enabled(registry, record, marker)
                ):
                    return False
    _write_status(registry, "connecting")
    _report_foreground(marker, "Connecting")
    await _session_until_stopped(
        stop_event=stop,
        root=registry,
        record=record,
        project=project,
        signing_key=signing_key,
        session_runner=session_runner,
        marker=marker,
        drain=drain,
    )
    return True


async def _wait_before_reconnect(
    stop: asyncio.Event,
    registry: Path,
    failures: int,
    marker: str,
    drain: asyncio.Event | None = None,
) -> None:
    if (
        stop.is_set()
        or (drain is not None and drain.is_set())
        or not _enabled_record(registry, marker)
    ):
        return
    delay = reconnect_delay_seconds(failures, secrets.randbelow(1001) / 1000)
    _write_status(registry, "unavailable")
    deadline = asyncio.get_running_loop().time() + delay
    while (
        not stop.is_set()
        and (drain is None or not drain.is_set())
        and _enabled_record(registry, marker)
    ):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return
        try:
            await asyncio.wait_for(
                stop.wait(), timeout=min(remaining, _LOCAL_AUTHORITY_POLL_SECONDS)
            )
        except TimeoutError:
            continue


async def _run_connector(
    *,
    root: Path | None = None,
    stop_event: asyncio.Event | None = None,
    foreground: bool = False,
    drain: asyncio.Event | None = None,
    expected_identity: dict[str, str] | None = None,
    identity_loader: Callable[[Path], dict[str, str]] = _single_registered_identity,
    project_resolver: Callable[..., LocalRegisteredRead] = resolve_registered_read,
    key_loader: Callable[..., Ed25519PrivateKey] = _load_bound_owner_key,
    session_runner: Callable[..., Awaitable[HandshakeReceipt]] = execute_owner_managed_read_session,
) -> int:
    registry = default_registry_root() if root is None else root
    stop = stop_event if stop_event is not None else asyncio.Event()
    if drain is not None and not foreground:
        raise LocalApprovalDeniedError(_DENIED)
    if not foreground and not _enabled_record(registry):
        return 0

    with (
        _connector_session_lock(registry),
        _local_session_authority(
            registry, foreground, identity_loader, expected_identity
        ) as marker,
    ):
        from contextlib import nullcontext

        from kicad_mcp.cloud_posix_update_control import watch

        control = (
            watch(registry, expected_identity["cloudOrigin"])
            if foreground and expected_identity is not None and drain is None
            else nullcontext(drain)
        )
        async with control as session_drain:
            # Invalidate the previous process's cached status before loading keys.
            _write_status(registry, "unavailable")
            failures = 0
            while (
                not stop.is_set()
                and (session_drain is None or not session_drain.is_set())
                and _enabled_record(registry, marker)
            ):
                try:
                    connected = await _run_registered_session(
                        registry=registry,
                        stop=stop,
                        identity_loader=identity_loader,
                        project_resolver=project_resolver,
                        key_loader=key_loader,
                        session_runner=session_runner,
                        marker=marker,
                        drain=session_drain,
                    )
                    if not connected:
                        break
                    failures = 0
                except asyncio.CancelledError:
                    raise
                except (OSError, ValueError, WebSocketException) as exc:
                    _write_status(registry, "unavailable")
                    if session_drain is not None and session_drain.is_set():
                        break
                    if foreground:
                        from kicad_mcp.cloud_windows_connector import _is_remote_policy_rejection

                        if isinstance(
                            exc, ProjectSelectionMissingError
                        ) or _is_remote_policy_rejection(exc):
                            return 3
                    failures += 1
                if session_drain is not None and session_drain.is_set():
                    break
                _report_foreground(marker, "Disconnected")
                await _wait_before_reconnect(stop, registry, failures, marker, session_drain)

    return 0


async def _run_service(
    *, foreground: bool = False, expected_identity: dict[str, str] | None = None
) -> int:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        return await _run_connector(
            stop_event=stop, foreground=foreground, expected_identity=expected_identity
        )
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)


def run_foreground(expected_identity: dict[str, str]) -> int:
    """Run the owner-approved terminal connection, not the managed service."""
    try:
        return asyncio.run(_run_service(foreground=True, expected_identity=expected_identity))
    except ConnectorAlreadyRunningError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        print(_DENIED, file=sys.stderr)
        return 1


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
    except ConnectorAlreadyRunningError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError):
        print(_DENIED, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
