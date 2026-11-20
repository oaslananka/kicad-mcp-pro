"""One owner-approved Windows device identity before any KiCad project is selected.

The Cloud UI can choose a project after the signed device connects. Until then,
only opaque folder selection messages are permitted on its signed socket.
No implicit file reads, project grants, native writes, or background services.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import uuid
from collections.abc import Callable
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
)

from kicad_mcp.cloud_folder_browse_receiver import (
    BrowserFolderService,
    default_bindings_file,
)
from kicad_mcp.cloud_local_folder_browser import LocalFolderBrowser
from kicad_mcp.cloud_local_registry import _STEM, _UUID
from kicad_mcp.cloud_outbound_handshake import (
    execute_owner_folder_only_session,
)
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_windows_binding import inspect_local_binding
from kicad_mcp.cloud_windows_credentials import create_credential, read_credential
from kicad_mcp.cloud_windows_enrollment import (
    WindowsEnrolledDevice,
    WindowsRegisteredProject,
)
from kicad_mcp.cloud_windows_local_selection import bind_owner_selected_project
from kicad_mcp.cloud_windows_project_path import read_windows_project_presence
from kicad_mcp.cloud_windows_project_record import inspect_project_reference
from kicad_mcp.cloud_windows_single_instance import owner_connector_instance

_DEVICE_SELECTION_SLOT = "2" * 32
_MARKER_FIELDS = frozenset({"recordId", "origin", "ownerSub", "deviceId", "fingerprint"})
_DENIED = "Saved Cloud device identity is unavailable."


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len({key for key, _ in pairs}) != len(pairs):
        raise LocalApprovalDeniedError(_DENIED)
    return dict(pairs)


def selected_device() -> WindowsEnrolledDevice | None:
    """Inspect the current-user vault and independently verify the saved key binding."""
    if os.name != "nt":
        raise LocalApprovalDeniedError(_DENIED)
    raw = read_credential(_DEVICE_SELECTION_SLOT, "selected")
    if raw is None:
        return None
    if len(raw) > 1024:
        raise LocalApprovalDeniedError(_DENIED)
    try:
        marker = json.loads(raw, object_pairs_hook=_unique)
        if (
            not isinstance(marker, dict)
            or set(marker) != _MARKER_FIELDS
            or not all(isinstance(value, str) for value in marker.values())
        ):
            raise LocalApprovalDeniedError(_DENIED)
        identity = WindowsEnrolledDevice(
            record_id=marker["recordId"],
            origin=marker["origin"],
            owner_sub=marker["ownerSub"],
            device_id=marker["deviceId"],
            fingerprint=marker["fingerprint"],
        )
        verified = inspect_local_binding(
            record_id=identity.record_id,
            expected_origin=identity.origin,
            expected_owner_sub=identity.owner_sub,
            expected_device_id=identity.device_id,
        )
        if verified.fingerprint != identity.fingerprint:
            raise LocalApprovalDeniedError(_DENIED)
        return identity
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc


def remember_device(device: WindowsEnrolledDevice) -> None:
    """Create-only marker; re-running the same command cannot invent another device."""
    if os.name != "nt" or not isinstance(device, WindowsEnrolledDevice):
        raise LocalApprovalDeniedError(_DENIED)
    document = {
        "recordId": device.record_id,
        "origin": device.origin,
        "ownerSub": device.owner_sub,
        "deviceId": device.device_id,
        "fingerprint": device.fingerprint,
    }
    blob = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    previous = selected_device()
    if previous is not None:
        if previous != device:
            raise LocalApprovalDeniedError("A different device is already paired on this computer.")
        return
    create_credential(_DEVICE_SELECTION_SLOT, "selected", blob)
    if selected_device() != device:
        raise LocalApprovalDeniedError(_DENIED)


def _device_marker_payload(device: WindowsEnrolledDevice) -> bytes:
    return json.dumps(
        {
            "recordId": device.record_id,
            "origin": device.origin,
            "ownerSub": device.owner_sub,
            "deviceId": device.device_id,
            "fingerprint": device.fingerprint,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _reconcile_browser_repaired_device(
    project: WindowsRegisteredProject,
    previous: WindowsEnrolledDevice,
    replacement: WindowsEnrolledDevice,
) -> None:
    """Switch a stale device-only marker only with proof of the owner's prior repair."""
    from kicad_mcp.cloud_windows_connector import (
        _load_project_from_marker,
        selected_project,
    )
    from kicad_mcp.cloud_windows_credentials import delete_credential
    from kicad_mcp.cloud_windows_local_selection import inspect_owner_selected_project

    archived = read_credential(project.registration_id, "archived_selected")
    if not isinstance(archived, bytes) or not 1 <= len(archived) <= 1024:
        raise LocalApprovalDeniedError(_DENIED)
    try:
        marker = json.loads(archived, object_pairs_hook=_unique)
        if not isinstance(marker, dict) or set(marker) != {
            "registrationId",
            "recordId",
            "deviceId",
            "projectId",
        }:
            raise LocalApprovalDeniedError(_DENIED)
        old_project = _load_project_from_marker(marker)
    except (ValueError, TypeError, KeyError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc
    if (
        old_project.record_id != previous.record_id
        or old_project.device_id != previous.device_id
        or old_project.fingerprint != previous.fingerprint
        or old_project.origin != replacement.origin
        or old_project.owner_sub != replacement.owner_sub
        or old_project.project_id == project.project_id
        or old_project.device_id == replacement.device_id
        or selected_project() != project
    ):
        raise LocalApprovalDeniedError(_DENIED)
    old_binding = inspect_owner_selected_project(old_project)
    new_binding = inspect_owner_selected_project(project)
    if (
        old_binding.directory != new_binding.directory
        or old_binding.filename_stem != new_binding.filename_stem
    ):
        raise LocalApprovalDeniedError(_DENIED)

    old_bytes = _device_marker_payload(previous)
    new_bytes = _device_marker_payload(replacement)
    with owner_connector_instance():
        if (
            selected_project() != project
            or selected_device() != previous
            or read_credential(_DEVICE_SELECTION_SLOT, "selected") != old_bytes
        ):
            raise LocalApprovalDeniedError(_DENIED)
        archived_device = read_credential(project.registration_id, "archived_device_selected")
        if archived_device is None:
            create_credential(project.registration_id, "archived_device_selected", old_bytes)
            if read_credential(project.registration_id, "archived_device_selected") != old_bytes:
                raise LocalApprovalDeniedError(_DENIED)
        elif archived_device != old_bytes:
            raise LocalApprovalDeniedError(_DENIED)
        if not delete_credential(_DEVICE_SELECTION_SLOT, "selected"):
            raise LocalApprovalDeniedError(_DENIED)
        try:
            create_credential(_DEVICE_SELECTION_SLOT, "selected", new_bytes)
            if selected_device() != replacement:
                raise LocalApprovalDeniedError(_DENIED)
        except Exception:
            current = read_credential(_DEVICE_SELECTION_SLOT, "selected")
            if current == new_bytes:
                if not delete_credential(_DEVICE_SELECTION_SLOT, "selected"):
                    raise LocalApprovalDeniedError(_DENIED) from None
            elif current is not None:
                # Another owner's selection is never ours to undo.
                raise LocalApprovalDeniedError(_DENIED) from None
            create_credential(_DEVICE_SELECTION_SLOT, "selected", old_bytes)
            raise LocalApprovalDeniedError(_DENIED) from None


def remember_existing_project_device(
    project: WindowsRegisteredProject, *, allow_repair_migration: bool = False
) -> None:
    """Reuse a verified project; reconcile only an owner-approved repaired identity."""
    from kicad_mcp.cloud_windows_connector import selected_project

    if not isinstance(project, WindowsRegisteredProject) or selected_project() != project:
        raise LocalApprovalDeniedError(_DENIED)
    device = WindowsEnrolledDevice(
        record_id=project.record_id,
        origin=project.origin,
        owner_sub=project.owner_sub,
        device_id=project.device_id,
        fingerprint=project.fingerprint,
    )
    previous = selected_device()
    if previous is None or previous == device:
        remember_device(device)
    elif allow_repair_migration:
        _reconcile_browser_repaired_device(project, previous, device)
    else:
        raise LocalApprovalDeniedError(_DENIED)


def verified_device_key(device: WindowsEnrolledDevice) -> Ed25519PrivateKey:
    """Re-check the actual current-user key before any outgoing signed connection."""
    if selected_device() != device:
        raise LocalApprovalDeniedError(_DENIED)
    raw = read_credential(device.record_id, "key")
    if raw is None:
        raise LocalApprovalDeniedError(_DENIED)
    key = load_pem_private_key(raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise LocalApprovalDeniedError(_DENIED)
    public = key.public_key().public_bytes(Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    if hashlib.sha256(public).hexdigest() != device.fingerprint:
        raise LocalApprovalDeniedError(_DENIED)
    return key


def adopt_browser_project(
    device: WindowsEnrolledDevice, project_id: str, selected_file: Path
) -> bool:
    """Adopt ONLY an explicitly owner-picked Cloud project UUID and native file.

    The Cloud app must have already verified owner session, CSRF and the
    signed folder binding request. A device-only identity never grants writes.
    """
    from kicad_mcp.cloud_windows_connector import (
        activate,
        remember_selected_project,
        selected_project,
    )

    if (
        selected_device() != device
        or selected_project() is not None
        or not isinstance(project_id, str)
        or _UUID.fullmatch(project_id) is None
        or not isinstance(selected_file, Path)
        or not selected_file.is_absolute()
        or selected_file.is_symlink()
        or selected_file.is_junction()
        or selected_file.suffix.lower() != ".kicad_pro"
        or _STEM.fullmatch(selected_file.stem) is None
        or not any(read_windows_project_presence(selected_file.parent, selected_file.stem).values())
    ):
        raise LocalApprovalDeniedError(_DENIED)
    registration_id = uuid.uuid4().hex
    project = WindowsRegisteredProject(
        registration_id=registration_id,
        record_id=device.record_id,
        origin=device.origin,
        owner_sub=device.owner_sub,
        device_id=device.device_id,
        fingerprint=device.fingerprint,
        project_id=project_id,
        filename_stem=selected_file.stem,
    )
    document = {
        "registrationId": project.registration_id,
        "recordId": project.record_id,
        "origin": project.origin,
        "ownerSub": project.owner_sub,
        "deviceId": project.device_id,
        "fingerprint": project.fingerprint,
        "projectId": project.project_id,
        "filenameStem": project.filename_stem,
    }
    create_credential(
        registration_id, "registration", json.dumps(document, sort_keys=True).encode()
    )
    inspect_project_reference(
        registration_id=registration_id,
        record_id=device.record_id,
        expected_origin=device.origin,
        expected_owner_sub=device.owner_sub,
        expected_device_id=device.device_id,
        expected_project_id=project_id,
        expected_filename_stem=selected_file.stem,
    )
    bind_owner_selected_project(project, selected_file.parent, owner_confirm=lambda _path: True)
    remember_selected_project(project)
    activate(project, owner_confirm=lambda _project: True)
    return True


def _folder_service(device: WindowsEnrolledDevice) -> BrowserFolderService:
    from kicad_mcp.cloud_windows_connector import selected_project

    return BrowserFolderService(
        LocalFolderBrowser([], default_bindings_file()),
        authorization=lambda: selected_device() == device and selected_project() is None,
        on_bound=lambda project_id, chosen: adopt_browser_project(device, project_id, chosen),
    )


async def run_device_only(
    device: WindowsEnrolledDevice,
    *,
    status_callback: Callable[[str], None],
) -> None:
    """Reuse the owner key; retry signed network sessions until a folder is bound."""
    from kicad_mcp.cloud_windows_connector import (
        CloudOwnerReapprovalRequiredError,
        _is_remote_policy_rejection,
        selected_project,
    )

    with owner_connector_instance():
        failures = 0
        while selected_project() is None:
            if selected_device() != device:
                raise LocalApprovalDeniedError(_DENIED)
            status_callback("Connecting")
            try:
                await execute_owner_folder_only_session(
                    origin=device.origin,
                    trusted_origin=device.origin,
                    owner_sub=device.owner_sub,
                    device_id=device.device_id,
                    signing_key=verified_device_key(device),
                    folder_service_factory=lambda _receipt: _folder_service(device),
                    on_ready=lambda _receipt: status_callback(
                        "Cloud acknowledged this device's signed session"
                    ),
                    on_activity=status_callback,
                )
                failures = 0
            except (OSError, ValueError) as exc:
                if _is_remote_policy_rejection(exc):
                    raise CloudOwnerReapprovalRequiredError(
                        "Cloud denied the signed device session."
                    ) from exc
                failures += 1
                status_callback("Connection interrupted; retrying")
            if selected_project() is None:
                await asyncio.sleep(min(20, 1 + failures * 2))
    status_callback("Project selected in Cloud; switching to local KiCad MCP tools")
