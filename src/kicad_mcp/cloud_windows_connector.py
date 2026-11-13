"""Default-OFF Windows user-credential Connector core, without OS service install.

No Cloud device may be paired automatically. The public Windows Cloud CLI
remains disabled until Task Scheduler lifecycle and real owner-browser
acceptance pass. This module has no socket listener and no native write tools.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
)
from websockets.exceptions import ConnectionClosed, WebSocketException

from kicad_mcp.cloud_folder_browse_receiver import LocalFolderBrowseService, device_folder_service
from kicad_mcp.cloud_outbound_handshake import (
    HandshakeReceipt,
    execute_owner_managed_read_session,
)
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding
from kicad_mcp.cloud_reconnect_policy import reconnect_delay_seconds
from kicad_mcp.cloud_windows_credentials import (
    create_credential,
    delete_credential,
    read_credential,
)
from kicad_mcp.cloud_windows_enrollment import WindowsRegisteredProject
from kicad_mcp.cloud_windows_local_selection import (
    WindowsLocalProjectSelection,
    inspect_owner_selected_project,
)
from kicad_mcp.cloud_windows_project_record import inspect_project_reference

_DENIED = "Windows Connector is unavailable; local authorization was not verified."
_ACTIVE_RECORD_ID = "0" * 32  # Reserved only for the current user's app-namespaced vault.
_SELECTED_RECORD_ID = "1" * 32  # Owner-selected identity independent of On/Off.
_ACTIVE_FIELDS = frozenset({"registrationId", "recordId", "deviceId", "projectId"})
_REGISTRATION_FIELDS = frozenset(
    {
        "registrationId",
        "recordId",
        "origin",
        "ownerSub",
        "deviceId",
        "fingerprint",
        "projectId",
        "filenameStem",
    }
)
_MAX_READS = 16
_SESSION_LIFETIME_MS = 280_000


class CloudOwnerReapprovalRequiredError(ValueError):
    """Cloud closed this signed socket for a policy reason, not a network outage."""


def _is_remote_policy_rejection(error: BaseException) -> bool:
    """Inspect only received close codes; never expose untrusted socket reasons."""
    current: BaseException | None = error
    for _ in range(4):
        if current is None:
            return False
        if isinstance(current, ConnectionClosed):
            return current.rcvd is not None and current.rcvd.code == 1008
        current = current.__cause__
    return False


@dataclass(frozen=True, slots=True)
class WindowsActiveConnector:
    """Local-only activation; not proof of a remotely granted connection."""

    project: WindowsRegisteredProject
    selected: WindowsLocalProjectSelection
    signing_key: Ed25519PrivateKey


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len({key for key, _ in pairs}) != len(pairs):
        raise LocalApprovalDeniedError(_DENIED)
    return dict(pairs)


def _active_marker() -> dict[str, str] | None:
    if os.name != "nt":
        raise LocalApprovalDeniedError(_DENIED)
    raw = read_credential(_ACTIVE_RECORD_ID, "active")
    if raw is None:
        return None
    try:
        if len(raw) > 1024:
            raise LocalApprovalDeniedError(_DENIED)
        data = json.loads(raw, object_pairs_hook=_unique)
        if (
            not isinstance(data, dict)
            or set(data) != _ACTIVE_FIELDS
            or any(not isinstance(value, str) for value in data.values())
        ):
            raise LocalApprovalDeniedError(_DENIED)
        return data
    except (ValueError, TypeError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc


def _load_project_from_marker(marker: dict[str, str]) -> WindowsRegisteredProject:
    raw = read_credential(marker["registrationId"], "registration")
    if raw is None or not 1 <= len(raw) <= 2048:
        raise LocalApprovalDeniedError(_DENIED)
    try:
        data = json.loads(raw, object_pairs_hook=_unique)
        if (
            not isinstance(data, dict)
            or set(data) != _REGISTRATION_FIELDS
            or any(not isinstance(value, str) for value in data.values())
            or any(data[key] != marker[key] for key in marker)
        ):
            raise LocalApprovalDeniedError(_DENIED)
        project = WindowsRegisteredProject(
            registration_id=data["registrationId"],
            record_id=data["recordId"],
            origin=data["origin"],
            owner_sub=data["ownerSub"],
            device_id=data["deviceId"],
            fingerprint=data["fingerprint"],
            project_id=data["projectId"],
            filename_stem=data["filenameStem"],
        )
        inspected = inspect_project_reference(
            registration_id=project.registration_id,
            record_id=project.record_id,
            expected_origin=project.origin,
            expected_owner_sub=project.owner_sub,
            expected_device_id=project.device_id,
            expected_project_id=project.project_id,
            expected_filename_stem=project.filename_stem,
        )
        if inspected.fingerprint != project.fingerprint:
            raise LocalApprovalDeniedError(_DENIED)
        return project
    except (ValueError, TypeError, KeyError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc


def selected_project() -> WindowsRegisteredProject | None:
    """Read one remembered owner-approved device/project without enabling it."""
    if os.name != "nt":
        raise LocalApprovalDeniedError(_DENIED)
    raw = read_credential(_SELECTED_RECORD_ID, "selected")
    if raw is None:
        return None
    if len(raw) > 1024:
        raise LocalApprovalDeniedError(_DENIED)
    try:
        marker = json.loads(raw, object_pairs_hook=_unique)
        if (
            not isinstance(marker, dict)
            or set(marker) != _ACTIVE_FIELDS
            or not all(isinstance(value, str) for value in marker.values())
        ):
            raise LocalApprovalDeniedError(_DENIED)
        project = _load_project_from_marker(marker)
        inspect_owner_selected_project(project)
        return project
    except (OSError, ValueError, TypeError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc


def remember_selected_project(project: WindowsRegisteredProject) -> None:
    """Create-only persistent owner selection, not a Cloud grant or enabled marker."""
    if os.name != "nt" or not isinstance(project, WindowsRegisteredProject):
        raise LocalApprovalDeniedError(_DENIED)
    inspect_owner_selected_project(project)
    marker = {
        "registrationId": project.registration_id,
        "recordId": project.record_id,
        "deviceId": project.device_id,
        "projectId": project.project_id,
    }
    payload = json.dumps(marker, sort_keys=True, separators=(",", ":")).encode("utf-8")
    create_credential(_SELECTED_RECORD_ID, "selected", payload)
    if selected_project() != project:
        raise LocalApprovalDeniedError(_DENIED)


def _validate_repair_candidate(
    previous: WindowsRegisteredProject,
    replacement: WindowsRegisteredProject,
) -> None:
    """A repaired identity is new, but the Cloud owner and local folder cannot change."""
    if (
        previous.origin != replacement.origin
        or previous.owner_sub != replacement.owner_sub
        or previous.device_id == replacement.device_id
        or previous.project_id == replacement.project_id
        or previous.record_id == replacement.record_id
        or previous.registration_id == replacement.registration_id
        or previous.fingerprint == replacement.fingerprint
        or previous.filename_stem != replacement.filename_stem
        or selected_project() != previous
    ):
        raise LocalApprovalDeniedError(_DENIED)
    old_selection = inspect_owner_selected_project(previous)
    new_selection = inspect_owner_selected_project(replacement)
    if (
        old_selection.directory != new_selection.directory
        or old_selection.filename_stem != new_selection.filename_stem
    ):
        raise LocalApprovalDeniedError(_DENIED)


def _verify_repair_signing_key(replacement: WindowsRegisteredProject) -> dict[str, str]:
    """Check that the staged registration is backed by its actual new Ed25519 key."""
    import hashlib

    expected_marker = {
        "registrationId": replacement.registration_id,
        "recordId": replacement.record_id,
        "deviceId": replacement.device_id,
        "projectId": replacement.project_id,
    }
    if _load_project_from_marker(expected_marker) != replacement:
        raise LocalApprovalDeniedError(_DENIED)
    key_blob = read_credential(replacement.record_id, "key")
    if not key_blob:
        raise LocalApprovalDeniedError(_DENIED)
    try:
        fresh_key = load_pem_private_key(key_blob, password=None)
        if not isinstance(fresh_key, Ed25519PrivateKey):
            raise LocalApprovalDeniedError(_DENIED)
        public = fresh_key.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo
        )
        if hashlib.sha256(public).hexdigest() != replacement.fingerprint:
            raise LocalApprovalDeniedError(_DENIED)
    except (ValueError, TypeError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc
    return expected_marker


def _archive_repair_marker_state(
    previous: WindowsRegisteredProject,
    replacement: WindowsRegisteredProject,
) -> tuple[bytes, bytes | None]:
    """Archive old selection/activation under the new registration, never overwrite."""
    saved_selected = read_credential(_SELECTED_RECORD_ID, "selected")
    saved_active = read_credential(_ACTIVE_RECORD_ID, "active")
    if saved_selected is None:
        raise LocalApprovalDeniedError(_DENIED)
    if saved_active is not None:
        # A foreign/stale active marker is not ours to replace or repair.
        current = _active()
        if current is None or current.project != previous:
            raise LocalApprovalDeniedError(_DENIED)
    create_credential(replacement.registration_id, "archived_selected", saved_selected)
    if saved_active is not None:
        create_credential(replacement.registration_id, "archived_active", saved_active)
    if read_credential(replacement.registration_id, "archived_selected") != saved_selected or (
        saved_active is not None
        and read_credential(replacement.registration_id, "archived_active") != saved_active
    ):
        raise LocalApprovalDeniedError(_DENIED)
    return saved_selected, saved_active


def _restore_repair_marker_state(
    saved_selected: bytes,
    saved_active: bytes | None,
    expected_marker: dict[str, str],
) -> None:
    """Rollback only our own new marker, without deleting a foreign replacement."""
    selected = read_credential(_SELECTED_RECORD_ID, "selected")
    if selected is not None and selected != saved_selected:
        # Never erase another process's unexpected selection.
        new_marker = json.dumps(expected_marker, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        if selected != new_marker:
            raise LocalApprovalDeniedError(_DENIED)
        delete_credential(_SELECTED_RECORD_ID, "selected")
    if read_credential(_SELECTED_RECORD_ID, "selected") is None:
        create_credential(_SELECTED_RECORD_ID, "selected", saved_selected)
    active = read_credential(_ACTIVE_RECORD_ID, "active")
    if active is not None and active != saved_active:
        raise LocalApprovalDeniedError(_DENIED)
    if saved_active is not None and active is None:
        create_credential(_ACTIVE_RECORD_ID, "active", saved_active)
    if (
        read_credential(_SELECTED_RECORD_ID, "selected") != saved_selected
        or read_credential(_ACTIVE_RECORD_ID, "active") != saved_active
    ):
        raise LocalApprovalDeniedError(_DENIED)


def _switch_repair_marker_state(
    replacement: WindowsRegisteredProject,
    saved_selected: bytes,
    saved_active: bytes | None,
    expected_marker: dict[str, str],
) -> None:
    """Atomic-in-effect, fail-closed switch with original marker rollback."""
    try:
        # Revoke local old authority before selection changes. The old private
        # key and user-approved project binding are NOT deleted.
        if read_credential(_SELECTED_RECORD_ID, "selected") != saved_selected:
            raise LocalApprovalDeniedError(_DENIED)
        if read_credential(_ACTIVE_RECORD_ID, "active") != saved_active:
            raise LocalApprovalDeniedError(_DENIED)
        if saved_active is not None and not delete_credential(_ACTIVE_RECORD_ID, "active"):
            raise LocalApprovalDeniedError(_DENIED)
        if not delete_credential(_SELECTED_RECORD_ID, "selected"):
            raise LocalApprovalDeniedError(_DENIED)
        remember_selected_project(replacement)
        if selected_project() != replacement or _active_marker() is not None:
            raise LocalApprovalDeniedError(_DENIED)
    except Exception:
        _restore_repair_marker_state(saved_selected, saved_active, expected_marker)
        raise


def repair_selected_project(
    previous: WindowsRegisteredProject,
    replacement: WindowsRegisteredProject,
    *,
    owner_confirm: Callable[[WindowsRegisteredProject, WindowsRegisteredProject], bool],
) -> None:
    """Switch only after new browser-approved enrollment; preserve old keys/folder.

    Old markers are archived under the new registration before any current
    marker changes. The caller must stop the old scheduled/foreground session.
    """
    if (
        os.name != "nt"
        or not isinstance(previous, WindowsRegisteredProject)
        or not isinstance(replacement, WindowsRegisteredProject)
    ):
        raise LocalApprovalDeniedError(_DENIED)
    if not callable(owner_confirm) or owner_confirm(previous, replacement) is not True:
        raise LocalApprovalDeniedError("The owner declined Cloud device repair.")
    _validate_repair_candidate(previous, replacement)
    expected_marker = _verify_repair_signing_key(replacement)
    saved_selected, saved_active = _archive_repair_marker_state(previous, replacement)
    _switch_repair_marker_state(replacement, saved_selected, saved_active, expected_marker)


def _active() -> WindowsActiveConnector | None:
    """Reverify every vault identity and selected local project on each use."""
    marker = _active_marker()
    if marker is None:
        return None
    project = _load_project_from_marker(marker)
    selected = inspect_owner_selected_project(project)
    key_blob = read_credential(project.record_id, "key")
    if not key_blob:
        raise LocalApprovalDeniedError(_DENIED)
    signing_key = load_pem_private_key(key_blob, password=None)
    if not isinstance(signing_key, Ed25519PrivateKey):
        raise LocalApprovalDeniedError(_DENIED)
    public = signing_key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    import hashlib

    if hashlib.sha256(public).hexdigest() != project.fingerprint:
        raise LocalApprovalDeniedError(_DENIED)
    return WindowsActiveConnector(project=project, selected=selected, signing_key=signing_key)


def _current_authorization(project: WindowsRegisteredProject) -> bool:
    """Local enable may be revoked during in-flight reads or reconnects."""
    try:
        active = _active()
        return active is not None and active.project == project
    except (ValueError, TypeError, OSError):
        return False


def activate(
    project: WindowsRegisteredProject,
    *,
    owner_confirm: Callable[[WindowsRegisteredProject], bool],
) -> None:
    """Prepare local default-OFF identity for supervised start; never open socket."""
    if os.name != "nt" or not isinstance(project, WindowsRegisteredProject):
        raise LocalApprovalDeniedError(_DENIED)
    inspected = inspect_owner_selected_project(project)
    if inspected.project_id != project.project_id:
        raise LocalApprovalDeniedError(_DENIED)
    if owner_confirm(project) is not True:
        raise LocalApprovalDeniedError("The owner declined local Connector activation.")
    marker = {
        "registrationId": project.registration_id,
        "recordId": project.record_id,
        "deviceId": project.device_id,
        "projectId": project.project_id,
    }
    blob = json.dumps(marker, sort_keys=True, separators=(",", ":")).encode("utf-8")
    create_credential(_ACTIVE_RECORD_ID, "active", blob)
    # Do not report Connected: no service has been started and Cloud grants
    # are still independently controlled by the owner.


def deactivate() -> bool:
    """Fence new reads locally; remote Cloud grant revocation is separate."""
    if os.name != "nt":
        raise LocalApprovalDeniedError(_DENIED)
    return delete_credential(_ACTIVE_RECORD_ID, "active")


def local_state() -> str:
    """Status never equates a vault marker to an active Cloud socket."""
    try:
        marker = _active_marker()
        if marker is None:
            return "Off"
        return "Configured (not connected)" if _active() else "Unavailable"
    except (OSError, ValueError, TypeError):
        return "Unavailable"


def _dispatcher(
    project: WindowsRegisteredProject,
    selected: WindowsLocalProjectSelection,
    receipt: HandshakeReceipt,
    allow_native_drc: bool = False,
) -> LocalReadDispatch:
    if receipt.device_id != project.device_id or not _current_authorization(project):
        raise LocalApprovalDeniedError(_DENIED)
    return LocalReadDispatch(
        verified=VerifiedLocalBinding(
            device_id=receipt.device_id,
            project_id=project.project_id,
            operations=frozenset(
                {"project_summary", "run_drc"} if allow_native_drc else {"project_summary"}
            ),
            session_id=receipt.session_id,
            session_expires_unix_ms=time.time_ns() // 1_000_000 + _SESSION_LIFETIME_MS,
        ),
        operator_project=OperatorProject(
            device_id=project.device_id,
            project_id=project.project_id,
            directory=selected.directory,
            filename_stem=selected.filename_stem,
        ),
        current_authorization=lambda: _current_authorization(project),
        max_reads=_MAX_READS,
        native_drc=allow_native_drc,
        managed_native_drc=allow_native_drc,
    )


async def _run_owner_session(
    project: WindowsRegisteredProject,
    selected: WindowsLocalProjectSelection,
    key: Ed25519PrivateKey,
    runner: Callable[..., Awaitable[HandshakeReceipt]],
    allow_native_drc: bool = False,
) -> HandshakeReceipt:
    """Bind one immutable identity and key to this particular socket session."""
    settings = {
        "origin": project.origin,
        "trusted_origin": project.origin,
        "owner_sub": project.owner_sub,
        "device_id": project.device_id,
        "signing_key": key,
        "dispatcher_factory": lambda receipt: _dispatcher(
            project, selected, receipt, allow_native_drc=allow_native_drc
        ),
        "max_reads": _MAX_READS,
    }
    if allow_native_drc:
        settings["allow_native_drc"] = True
    if runner is execute_owner_managed_read_session or getattr(
        runner, "_kicad_supports_folder_browse", False
    ):

        def folder_factory(receipt: HandshakeReceipt) -> LocalFolderBrowseService:
            if receipt.device_id != project.device_id or not _current_authorization(project):
                raise LocalApprovalDeniedError(_DENIED)
            return device_folder_service(
                selected.directory,
                authorization=lambda: _current_authorization(project),
            )

        settings["folder_service_factory"] = folder_factory
    return await runner(**settings)


async def _await_authorized_session(
    project: WindowsRegisteredProject,
    task: asyncio.Task[HandshakeReceipt],
    revoked: asyncio.Task[bool],
) -> bool:
    """Terminate a socket when owner authorization or the local stop marker is lost."""
    while not task.done() and not revoked.done():
        await asyncio.wait((task, revoked), timeout=1)
        if not _current_authorization(project):
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            return False
    if revoked.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return False
    return True


def _session_runner_with_status(
    session_runner: Callable[..., Awaitable[HandshakeReceipt]],
    status_callback: Callable[[str], None] | None,
) -> Callable[..., Awaitable[HandshakeReceipt]]:
    if status_callback is None or session_runner is not execute_owner_managed_read_session:
        return session_runner

    def report_ready(_receipt: HandshakeReceipt) -> None:
        status_callback("Connected")

    async def signed_ready_runner(
        *,
        origin: str,
        trusted_origin: str,
        owner_sub: str,
        device_id: str,
        signing_key: Ed25519PrivateKey,
        dispatcher_factory: Callable[[HandshakeReceipt], LocalReadDispatch],
        max_reads: int,
        on_ready: Callable[[HandshakeReceipt], None] = report_ready,
        folder_service_factory: Callable[[HandshakeReceipt], LocalFolderBrowseService]
        | None = None,
        allow_native_drc: bool = False,
    ) -> HandshakeReceipt:
        return await execute_owner_managed_read_session(
            origin=origin,
            trusted_origin=trusted_origin,
            owner_sub=owner_sub,
            device_id=device_id,
            signing_key=signing_key,
            dispatcher_factory=dispatcher_factory,
            max_reads=max_reads,
            on_ready=on_ready,
            folder_service_factory=folder_service_factory,
            allow_native_drc=allow_native_drc,
        )

    signed_ready_runner._kicad_supports_folder_browse = True  # type: ignore[attr-defined]
    return signed_ready_runner


async def _attempt_authorized_session(
    project: WindowsRegisteredProject,
    selected: WindowsLocalProjectSelection,
    key: Ed25519PrivateKey,
    runner: Callable[..., Awaitable[HandshakeReceipt]],
    stop: asyncio.Event,
    allow_native_drc: bool = False,
) -> bool | None:
    """One signed session: True completed, False network failure, None revoked."""
    task = asyncio.create_task(
        _run_owner_session(
            project,
            selected,
            key,
            runner,
            **({"allow_native_drc": True} if allow_native_drc else {}),
        )
    )
    revoked = asyncio.create_task(stop.wait())
    try:
        if not await _await_authorized_session(project, task, revoked):
            return None
        await task
        return True
    except asyncio.CancelledError:
        raise
    except (OSError, ValueError, WebSocketException) as exc:
        if _is_remote_policy_rejection(exc):
            raise CloudOwnerReapprovalRequiredError(
                "Cloud refused this signed device session (policy 1008)."
            ) from exc
        return False
    finally:
        revoked.cancel()
        await asyncio.gather(revoked, return_exceptions=True)


def _notify_connection_attempt(
    status_callback: Callable[[str], None] | None, failures: int
) -> None:
    """Report connection progress without claiming that Cloud accepted the socket."""
    if status_callback is not None:
        status_callback("Connecting" if failures == 0 else "Reconnecting")


def _next_failure_count(
    session_succeeded: bool,
    failures: int,
    status_callback: Callable[[str], None] | None,
) -> int:
    """A clean session resets backoff; network failures request a retry."""
    if session_succeeded:
        return 0
    if status_callback is not None:
        status_callback("Disconnected — reconnecting")
    return failures + 1


def _notify_owner_reapproval(
    status_callback: Callable[[str], None] | None,
    project: WindowsRegisteredProject,
) -> None:
    """Give an actionable policy 1008 recovery without leaking Cloud reasons."""
    if status_callback is not None:
        status_callback(
            "Cloud rejected this device session (policy 1008). "
            f"Review pairing and access at {project.origin}/devices. "
            "If this device is missing, run: kicad-mcp-pro cloud remote --repair-device "
            "and approve the new pairing in your browser. "
            "The local project and saved credentials were not changed."
        )


async def run_connector(
    *,
    stop: asyncio.Event,
    session_runner: Callable[..., Awaitable[HandshakeReceipt]] = execute_owner_managed_read_session,
    status_callback: Callable[[str], None] | None = None,
    allow_native_drc: bool = False,
) -> None:
    """Local-only execution core; supervisor controls process startup/shutdown.

    No incoming listener; only an authenticated outbound device session.
    Session restarts are rate-limited, even after clean Cloud disconnects.
    """
    if os.name != "nt" or type(allow_native_drc) is not bool:
        raise LocalApprovalDeniedError(_DENIED)
    failures = 0
    while not stop.is_set():
        active = _active()
        if active is None:
            return
        project, selected, key = active.project, active.selected, active.signing_key

        _notify_connection_attempt(status_callback, failures)
        runner_for_session = _session_runner_with_status(session_runner, status_callback)

        try:
            result = await _attempt_authorized_session(
                project,
                selected,
                key,
                runner_for_session,
                stop,
                **({"allow_native_drc": True} if allow_native_drc else {}),
            )
        except CloudOwnerReapprovalRequiredError:
            _notify_owner_reapproval(status_callback, project)
            raise
        if result is None:
            return
        failures = _next_failure_count(result, failures, status_callback)
        delay = reconnect_delay_seconds(failures, secrets.randbelow(1001) / 1000)
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            pass


def main(argv: list[str] | None = None) -> int:
    """Task Scheduler entrypoint; never enrolls/grants or starts without marker."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="Owner-approved Windows read-only KiCad Cloud Connector"
    )
    parser.add_argument("command", choices=("run",))
    parser.parse_args(argv)
    try:
        if _active() is None:
            print("Cloud Connector is Off.", file=sys.stderr)
            return 2
        asyncio.run(run_connector(stop=asyncio.Event()))
        return 0
    except KeyboardInterrupt:
        return 0
    except CloudOwnerReapprovalRequiredError:
        print(
            "Cloud refused the signed device session (policy 1008). "
            "Review the Cloud Devices page. If this device is missing, use an "
            "interactive terminal: kicad-mcp-pro cloud remote --repair-device. "
            "Local credentials are unchanged.",
            file=sys.stderr,
        )
        return 3
    except (OSError, ValueError, TypeError):
        print("Windows Connector unavailable; check local owner registration.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
