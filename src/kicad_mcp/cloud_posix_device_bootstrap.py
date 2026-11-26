"""Owner-terminal device-only onboarding for macOS and Linux."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path
from uuid import uuid4

from websockets.exceptions import WebSocketException

from kicad_mcp import cloud_pair, cloud_pair_keys, cloud_posix_recovery
from kicad_mcp.cloud_folder_browse_receiver import (
    BrowserFolderService,
    _posix_owner_native_picker,
    default_bindings_file,
)
from kicad_mcp.cloud_local_folder_browser import LocalFolderBrowser
from kicad_mcp.cloud_local_registry import _STEM, _UUID
from kicad_mcp.cloud_managed_connector import _connector_session_lock
from kicad_mcp.cloud_once import _load_bound_owner_key
from kicad_mcp.cloud_outbound_handshake import execute_owner_folder_only_session
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_registered_pilot import _single_registered_identity
from kicad_mcp.cloud_windows_connector import _is_remote_policy_rejection

Identity = tuple[Path, dict[str, str]]
_DENIED = "Saved Cloud registration cannot be verified. Existing files and keys were kept."


class DeviceSessionRejectedError(LocalApprovalDeniedError):
    """Received policy close; not evidence of device deletion by itself."""


def ensure_device(
    root: Path, origin: str, alias: str, approval: Callable[[str, str, str], None]
) -> Identity:
    """Caller owns the session lock. Never create a project here."""
    if cloud_posix_recovery._private_names(root / "projects"):
        raise LocalApprovalDeniedError(_DENIED)
    existing = cloud_posix_recovery.inspect_unbound_device(root, origin)
    if existing is not None:
        return existing
    keys = root / "keys"
    keys.mkdir(mode=0o700, exist_ok=True)
    keyfile = keys / f"{uuid4()}.pem"
    device, fingerprint = cloud_pair.enroll(
        origin, alias, keyfile, approval, connect_on_approval=True
    )
    verified = cloud_posix_recovery.inspect_unbound_device(root, origin)
    if (
        verified is None
        or verified[0] != keyfile
        or verified[1]["deviceId"] != device
        or verified[1]["fingerprint"] != fingerprint
    ):
        raise LocalApprovalDeniedError(_DENIED)
    return verified


def read_project(root: Path, identity: Identity) -> dict[str, str] | None:
    if not cloud_posix_recovery._private_names(root / "projects"):
        return None
    record = _single_registered_identity(root)
    keyfile, binding = identity
    if (
        any(
            record[key] != binding[source]
            for key, source in (
                ("ownerSub", "ownerSub"),
                ("cloudOrigin", "origin"),
                ("deviceId", "deviceId"),
            )
        )
        or record["keySlot"] != keyfile.stem
    ):
        raise LocalApprovalDeniedError(_DENIED)
    return record


def recover_missing_project(root: Path, record: dict[str, str]) -> bool:
    """Archive a deleted Cloud project selection while retaining the device key."""
    from kicad_mcp.cloud_device_inventory_status import inspect_inventory
    from kicad_mcp.cloud_managed_connector import _ENABLED_FILE, _FOREGROUND_FILE

    with _connector_session_lock(root):
        if os.path.lexists(root / _ENABLED_FILE) or os.path.lexists(root / _FOREGROUND_FILE):
            raise LocalApprovalDeniedError(_DENIED)
        identity = cloud_posix_recovery.inspect_unbound_device(root, record["cloudOrigin"])
        if identity is None or read_project(root, identity) != record:
            raise LocalApprovalDeniedError(_DENIED)
        keyfile, binding = identity
        key = _load_bound_owner_key(keyfile, binding["origin"], binding["deviceId"])
        state = inspect_inventory(
            binding["origin"], binding["ownerSub"], binding["deviceId"], record["projectId"], key
        )
        if state != "project_missing":
            return False
        if cloud_posix_recovery.inspect_unbound_device(root, binding["origin"]) != identity:
            raise LocalApprovalDeniedError(_DENIED)
        if read_project(root, identity) != record:
            raise LocalApprovalDeniedError(_DENIED)
        name = record["projectId"] + ".json"
        archive = root / "detached-projects"
        archive.mkdir(mode=0o700, exist_ok=True)
        if not os.path.lexists(archive / name):
            cloud_pair_keys._write_private_json(archive, name, record)
        if cloud_pair_keys._read_private_json(archive, name) != record:
            raise LocalApprovalDeniedError(_DENIED)
        folder = root / "projects"
        fd = cloud_pair_keys._open_owner_private_dir(folder / name)
        try:
            if read_project(root, identity) != record:
                raise LocalApprovalDeniedError(_DENIED)
            os.unlink(name, dir_fd=fd)
            os.fsync(fd)
        finally:
            os.close(fd)
        return True


def _restore_existing_project(root: Path, identity: Identity) -> dict[str, str] | None:
    """Restore a connection anchor, never create a Cloud project or grant.

    The caller owns the session lock. A crash after detaching the old primary
    is safe: the independently recorded secondary bindings remain available.
    """
    from kicad_mcp.cloud_device_inventory_status import inspect_inventory
    from kicad_mcp.cloud_posix_project_bindings import existing_targets

    if not os.path.lexists(root / "project-bindings"):
        return None
    keyfile, binding = identity
    if read_project(root, identity) is not None:
        raise LocalApprovalDeniedError(_DENIED)
    selectors = {
        "ownerSub": binding["ownerSub"],
        "cloudOrigin": binding["origin"],
        "deviceId": binding["deviceId"],
        "keySlot": keyfile.stem,
        "projectId": "",
    }
    targets = existing_targets(root, selectors)
    if not targets:
        return None
    key = _load_bound_owner_key(keyfile, binding["origin"], binding["deviceId"])
    # Keep the diagnosis bounded below the server's source rate limit.
    # Sorting UUIDs chooses an internal transport anchor, not a user project.
    for target in targets[:25]:
        state = inspect_inventory(
            binding["origin"], binding["ownerSub"], binding["deviceId"], target.project_id, key
        )
        if state in {"device_disabled", "device_revoked", "unverified", "unavailable"}:
            break
        if state != "active":
            continue
        if target not in existing_targets(root, selectors):
            raise LocalApprovalDeniedError(_DENIED)
        selected = target.directory / (target.filename_stem + ".kicad_pro")
        adopt_project(root, identity, target.project_id, selected)
        return read_project(root, identity)
    return None


def adopt_project(root: Path, identity: Identity, project_id: str, selected: Path) -> bool:
    """Persist only an explicit native picker + owner Cloud bind result."""
    keyfile, binding = identity
    if (
        cloud_posix_recovery.inspect_unbound_device(root, binding["origin"]) != identity
        or read_project(root, identity) is not None
        or not isinstance(project_id, str)
        or not _UUID.fullmatch(project_id)
        or not selected.is_absolute()
        or selected.is_symlink()
        or not selected.is_file()
        or selected.suffix.lower() != ".kicad_pro"
        or not _STEM.fullmatch(selected.stem)
        or selected.resolve(strict=True) != selected
    ):
        raise LocalApprovalDeniedError(_DENIED)
    folder = root / "projects"
    folder.mkdir(mode=0o700, exist_ok=True)
    cloud_pair_keys._write_private_json(
        folder,
        project_id + ".json",
        {
            "ownerSub": binding["ownerSub"],
            "cloudOrigin": binding["origin"],
            "deviceId": binding["deviceId"],
            "projectId": project_id,
            "keySlot": keyfile.stem,
            "directory": str(selected.parent),
            "filenameStem": selected.stem,
        },
    )
    return True


def _folder_service(root: Path, identity: Identity) -> BrowserFolderService:
    return BrowserFolderService(
        LocalFolderBrowser([], default_bindings_file()),
        native_picker=_posix_owner_native_picker,
        authorization=lambda: (
            cloud_posix_recovery.inspect_unbound_device(root, identity[1]["origin"]) == identity
            and read_project(root, identity) is None
        ),
        on_bound=lambda pid, path: adopt_project(root, identity, pid, path),
    )


async def _wait_for_project(
    root: Path, identity: Identity, status: Callable[[str], None]
) -> dict[str, str]:
    keyfile, binding = identity
    failures = 0
    while True:
        existing = read_project(root, identity)
        if existing is not None:
            return existing
        if cloud_posix_recovery.inspect_unbound_device(root, binding["origin"]) != identity:
            raise LocalApprovalDeniedError(_DENIED)
        key = _load_bound_owner_key(keyfile, binding["origin"], binding["deviceId"])
        status("Connecting")
        try:
            await execute_owner_folder_only_session(
                origin=binding["origin"],
                trusted_origin=binding["origin"],
                owner_sub=binding["ownerSub"],
                device_id=binding["deviceId"],
                signing_key=key,
                folder_service_factory=lambda _: _folder_service(root, identity),
                on_ready=lambda _: status("Cloud acknowledged this device's signed session"),
                on_activity=status,
            )
            failures = 0
        except (OSError, ValueError, WebSocketException) as exc:
            if _is_remote_policy_rejection(exc):
                raise DeviceSessionRejectedError(
                    "Cloud denied the device session. Existing pairing was preserved."
                ) from exc
            failures += 1
            status("Connection interrupted; retrying")
        if read_project(root, identity) is None:
            await asyncio.sleep(min(20, 1 + failures * 2))


def connect_device_only(
    root: Path,
    origin: str,
    alias: str,
    approval: Callable[[str, str, str], None],
    status: Callable[[str], None],
) -> dict[str, str] | None:
    """One lock covers enrollment, signed folder selection and local binding."""
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    with _connector_session_lock(root):
        identity = ensure_device(root, origin, alias, approval)
        from kicad_mcp.cloud_legacy_project_migration import legacy_candidates
        from kicad_mcp.cloud_posix_project_bindings import migrate_legacy
        from kicad_mcp.cloud_windows_write_issuer import _KICAD_CLOUD_ORIGIN

        if origin == _KICAD_CLOUD_ORIGIN and legacy_candidates():
            keyfile, binding = identity
            selectors = {
                "ownerSub": binding["ownerSub"],
                "cloudOrigin": binding["origin"],
                "deviceId": binding["deviceId"],
                "keySlot": keyfile.stem,
                "projectId": "",
            }
            key = _load_bound_owner_key(keyfile, origin, binding["deviceId"])
            migrate_legacy(
                root,
                selectors,
                key,
                lambda: (
                    cloud_posix_recovery.inspect_unbound_device(root, origin) == identity
                    and read_project(root, identity) is None
                ),
            )
        existing = _restore_existing_project(root, identity)
        if existing is not None:
            status("Restored an existing Cloud project on this device.")
            return existing
        status("Use Add Project in Cloud Devices after Online appears.")
        try:
            try:
                return asyncio.run(_wait_for_project(root, identity, status))
            except DeviceSessionRejectedError:
                from kicad_mcp.cloud_posix_replacement import recover_device_locked

                if not recover_device_locked(root, origin, alias, approval):
                    raise
                identity = ensure_device(root, origin, alias, approval)
                status("Device restored. Use Add Project after Online appears.")
                return asyncio.run(_wait_for_project(root, identity, status))
        except KeyboardInterrupt:
            status("Disconnected. Your approved device identity remains saved.")
            return None
