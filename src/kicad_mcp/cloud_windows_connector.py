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
from websockets.exceptions import WebSocketException

from kicad_mcp.cloud_outbound_handshake import HandshakeReceipt, execute_owner_managed_read_session
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
) -> LocalReadDispatch:
    if receipt.device_id != project.device_id or not _current_authorization(project):
        raise LocalApprovalDeniedError(_DENIED)
    return LocalReadDispatch(
        verified=VerifiedLocalBinding(
            device_id=receipt.device_id,
            project_id=project.project_id,
            operations=frozenset({"project_summary"}),
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
        native_drc=False,
    )


async def _run_owner_session(
    project: WindowsRegisteredProject,
    selected: WindowsLocalProjectSelection,
    key: Ed25519PrivateKey,
    runner: Callable[..., Awaitable[HandshakeReceipt]],
) -> HandshakeReceipt:
    """Bind one immutable identity and key to this particular socket session."""
    return await runner(
        origin=project.origin,
        trusted_origin=project.origin,
        owner_sub=project.owner_sub,
        device_id=project.device_id,
        signing_key=key,
        dispatcher_factory=lambda receipt: _dispatcher(project, selected, receipt),
        max_reads=_MAX_READS,
    )


async def run_connector(
    *,
    stop: asyncio.Event,
    session_runner: Callable[..., Awaitable[HandshakeReceipt]] = execute_owner_managed_read_session,
) -> None:
    """Local-only execution core; supervisor controls process startup/shutdown.

    No incoming listener; only an authenticated outbound device session.
    Session restarts are rate-limited, even after clean Cloud disconnects.
    """
    if os.name != "nt":
        raise LocalApprovalDeniedError(_DENIED)
    failures = 0
    while not stop.is_set():
        active = _active()
        if active is None:
            return
        project, selected, key = active.project, active.selected, active.signing_key

        task = asyncio.create_task(_run_owner_session(project, selected, key, session_runner))
        revoked = asyncio.create_task(stop.wait())
        try:
            while not task.done() and not revoked.done():
                await asyncio.wait((task, revoked), timeout=1)
                if not _current_authorization(project):
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                    return
            if revoked.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                return
            await task
            failures = 0
        except asyncio.CancelledError:
            raise
        except (OSError, ValueError, WebSocketException):
            failures += 1
        finally:
            revoked.cancel()
            await asyncio.gather(revoked, return_exceptions=True)
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
    except (OSError, ValueError, TypeError):
        print("Windows Connector unavailable; check local owner registration.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
