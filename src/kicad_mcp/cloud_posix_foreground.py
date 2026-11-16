"""Owner-supervised POSIX Cloud Connector, without a service or stored enable marker.

This uses the already-enrolled private signing key and read-only transport.
Every tool call must still pass a fresh local identity/key check, signed WSS
handshake, and the Cloud owner/client/project grant. It never starts systemd.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from websockets.exceptions import ConnectionClosed, WebSocketException

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
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_posix_native_picker import (
    choose_project_folder,
    native_picker_available,
)
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.cloud_reconnect_policy import reconnect_delay_seconds
from kicad_mcp.cloud_registered_pilot import _single_registered_identity

_MAX_READS = 16
_SESSION_LIFETIME_MS = 280_000
_DENIED = "Foreground Cloud Connector requires a valid owner-approved local registration."


def _public_key(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def _owner_authorization(
    *,
    root: Path,
    record: dict[str, str],
    project: LocalRegisteredRead,
    expected_public_key: bytes,
    stop: asyncio.Event,
    identity_loader: Callable[[Path], dict[str, str]],
    project_resolver: Callable[..., LocalRegisteredRead],
    key_loader: Callable[..., Ed25519PrivateKey],
) -> bool:
    """Recheck current, private on-disk authority before every read/delivery."""
    if stop.is_set():
        return False
    try:
        current = identity_loader(root)
        if current != record:
            return False
        selected = project_resolver(
            owner_sub=record["ownerSub"],
            origin=record["cloudOrigin"],
            device_id=record["deviceId"],
            project_id=record["projectId"],
            registry_root=root,
        )
        return (
            selected == project
            and _public_key(
                key_loader(selected.key_file, record["cloudOrigin"], record["deviceId"])
            )
            == expected_public_key
        )
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return False


async def _session_or_stop(
    runner: Callable[..., Awaitable[HandshakeReceipt]],
    settings: dict[str, object],
    stop: asyncio.Event,
) -> None:
    async def execute() -> HandshakeReceipt:
        return await runner(**settings)

    task = asyncio.create_task(execute())
    stopping = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait((task, stopping), return_when=asyncio.FIRST_COMPLETED)
        if stopping in done:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        else:
            await task
    finally:
        stopping.cancel()
        await asyncio.gather(stopping, return_exceptions=True)


def _policy_close(error: BaseException) -> bool:
    current: BaseException | None = error
    for _ in range(4):
        if current is None:
            break
        if isinstance(current, ConnectionClosed):
            return current.rcvd is not None and current.rcvd.code == 1008
        current = current.__cause__
    return False


def _load_foreground_binding(
    root: Path,
    identity_loader: Callable[[Path], dict[str, str]],
    project_resolver: Callable[..., LocalRegisteredRead],
    key_loader: Callable[..., Ed25519PrivateKey],
) -> tuple[dict[str, str], LocalRegisteredRead, Ed25519PrivateKey, bytes]:
    """Revalidate registration and signer before opening each signed session."""
    record = identity_loader(root)
    try:
        project = project_resolver(
            owner_sub=record["ownerSub"],
            origin=record["cloudOrigin"],
            device_id=record["deviceId"],
            project_id=record["projectId"],
            registry_root=root,
        )
        signer = key_loader(project.key_file, record["cloudOrigin"], record["deviceId"])
        return record, project, signer, _public_key(signer)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc


def _foreground_settings(
    *,
    root: Path,
    stop: asyncio.Event,
    record: dict[str, str],
    project: LocalRegisteredRead,
    signer: Ed25519PrivateKey,
    signer_public: bytes,
    identity_loader: Callable[[Path], dict[str, str]],
    project_resolver: Callable[..., LocalRegisteredRead],
    key_loader: Callable[..., Ed25519PrivateKey],
    status_callback: Callable[[str], None] | None,
    native_picker: Callable[[], Path | None] | None,
    bindings_file: Path | None,
) -> dict[str, object]:
    """Bind the immutable session identity to a fresh owner-checking dispatcher."""

    def authorized() -> bool:
        return _owner_authorization(
            root=root,
            record=record,
            project=project,
            expected_public_key=signer_public,
            stop=stop,
            identity_loader=identity_loader,
            project_resolver=project_resolver,
            key_loader=key_loader,
        )

    def dispatcher(receipt: HandshakeReceipt) -> LocalReadDispatch:
        if receipt.device_id != record["deviceId"] or not authorized():
            raise LocalApprovalDeniedError(_DENIED)
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
            current_authorization=authorized,
            max_reads=_MAX_READS,
            native_drc=False,
        )

    settings: dict[str, object] = {
        "origin": record["cloudOrigin"],
        "trusted_origin": record["cloudOrigin"],
        "owner_sub": record["ownerSub"],
        "device_id": record["deviceId"],
        "signing_key": signer,
        "dispatcher_factory": dispatcher,
        "max_reads": _MAX_READS,
        "on_ready": lambda _receipt: status_callback("Connected") if status_callback else None,
        "on_activity": status_callback,
    }
    if native_picker is not None:
        from kicad_mcp.cloud_folder_browse_receiver import (
            LocalFolderBrowseService,
            device_folder_service,
        )

        def owner_picker() -> Path | None:
            _notify(status_callback, "Local project folder picker opened")
            try:
                return native_picker()
            finally:
                _notify(status_callback, "Local project folder picker closed")

        def folder_factory(receipt: HandshakeReceipt) -> LocalFolderBrowseService:
            if receipt.device_id != record["deviceId"] or not authorized():
                raise LocalApprovalDeniedError(_DENIED)
            return device_folder_service(
                project.project_directory,
                bindings_file=bindings_file,
                native_picker=owner_picker,
                authorization=authorized,
            )

        settings["folder_service_factory"] = folder_factory
    return settings


def _notify(callback: Callable[[str], None] | None, message: str) -> None:
    if callback is not None:
        callback(message)


async def _run_signed_foreground_session(
    runner: Callable[..., Awaitable[HandshakeReceipt]],
    settings: dict[str, object],
    stop: asyncio.Event,
    status_callback: Callable[[str], None] | None,
) -> bool:
    """Run once: return False only for reconnectable network failures."""
    try:
        await _session_or_stop(runner, settings, stop)
        return True
    except CloudHandshakeDeniedError:
        _notify(status_callback, "Cloud refused this session; review owner approval in Devices")
        raise
    except (OSError, WebSocketException) as exc:
        if _policy_close(exc):
            _notify(status_callback, "Owner reapproval required; no automatic re-pairing")
            raise CloudHandshakeDeniedError("Owner reapproval required") from exc
        return False


def _remaining_reconnect_delay(failures: int, elapsed_seconds: float) -> float:
    """Throttle attempts from their start, not after an already healthy lease.

    A four-minute signed session has already exhausted the minimum handshake
    interval; a short close or repeated failures still honor exponential backoff.
    """
    budget = reconnect_delay_seconds(failures, secrets.randbelow(1001) / 1000)
    return max(0.0, budget - max(0.0, elapsed_seconds))


async def _wait_for_foreground_retry(
    stop: asyncio.Event,
    failures: int,
    *,
    elapsed_seconds: float,
) -> None:
    delay = _remaining_reconnect_delay(failures, elapsed_seconds)
    if delay == 0:
        return
    try:
        await asyncio.wait_for(stop.wait(), timeout=delay)
    except TimeoutError:
        pass


async def run_foreground(
    *,
    registry: Path | None = None,
    stop_event: asyncio.Event | None = None,
    status_callback: Callable[[str], None] | None = None,
    identity_loader: Callable[[Path], dict[str, str]] = _single_registered_identity,
    project_resolver: Callable[..., LocalRegisteredRead] = resolve_registered_read,
    key_loader: Callable[..., Ed25519PrivateKey] = _load_bound_owner_key,
    session_runner: Callable[..., Awaitable[HandshakeReceipt]] = execute_owner_managed_read_session,
    native_picker: Callable[[], Path | None] | None = None,
    bindings_file: Path | None = None,
) -> None:
    """Run signed read-only WSS in this terminal; stop instantly revokes local authority."""
    root = default_registry_root() if registry is None else registry
    stop = asyncio.Event() if stop_event is None else stop_event
    picker = native_picker
    if picker is None and native_picker_available():
        picker = choose_project_folder
    failures = 0
    while not stop.is_set():
        record, project, signer, signer_public = _load_foreground_binding(
            root, identity_loader, project_resolver, key_loader
        )
        settings = _foreground_settings(
            root=root,
            stop=stop,
            record=record,
            project=project,
            signer=signer,
            signer_public=signer_public,
            identity_loader=identity_loader,
            project_resolver=project_resolver,
            key_loader=key_loader,
            status_callback=status_callback,
            native_picker=picker,
            bindings_file=bindings_file,
        )
        _notify(status_callback, "Connecting" if failures == 0 else "Reconnecting")
        attempt_started_at = time.monotonic()
        success = await _run_signed_foreground_session(
            session_runner, settings, stop, status_callback
        )
        elapsed_seconds = max(0.0, time.monotonic() - attempt_started_at)
        failures = 0 if success else failures + 1
        if stop.is_set():
            return
        _notify(status_callback, "Disconnected - reconnecting")
        await _wait_for_foreground_retry(stop, failures, elapsed_seconds=elapsed_seconds)
