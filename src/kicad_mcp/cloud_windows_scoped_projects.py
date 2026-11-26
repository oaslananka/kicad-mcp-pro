"""Explicit Windows secondary selection, scoped to the current owner/device key."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kicad_mcp.cloud_folder_browse_receiver import BrowserFolderService, default_bindings_file
from kicad_mcp.cloud_local_folder_browser import LocalFolderBrowser
from kicad_mcp.cloud_local_registry import _STEM
from kicad_mcp.cloud_pair_keys import _unique
from kicad_mcp.cloud_readonly_boundary import OperatorProject
from kicad_mcp.cloud_windows_credentials import (
    create_credential,
    list_secondary_slots,
    read_credential,
)
from kicad_mcp.cloud_windows_enrollment import WindowsEnrolledDevice, WindowsRegisteredProject
from kicad_mcp.cloud_windows_local_selection import WindowsLocalProjectSelection
from kicad_mcp.cloud_windows_project_path import read_windows_project_presence

_PROJECT_SUFFIX = ".kicad_pro"


def _identity(
    project: WindowsEnrolledDevice | WindowsRegisteredProject, pid: str
) -> dict[str, str]:
    if not isinstance(pid, str) or str(UUID(pid)) != pid:
        raise ValueError("Invalid secondary project ID.")
    return {
        "recordId": project.record_id,
        "origin": project.origin,
        "ownerSub": project.owner_sub,
        "deviceId": project.device_id,
        "fingerprint": project.fingerprint,
        "projectId": pid,
    }


def _device_prefix(identity: dict[str, str]) -> str:
    payload = json.dumps(
        {k: v for k, v in identity.items() if k != "projectId"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(b"kicad-cloud-windows-device-v1\0" + payload).hexdigest()[:16]


def _slot(identity: dict[str, str]) -> str:
    payload = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return (
        _device_prefix(identity)
        + hashlib.sha256(b"kicad-cloud-windows-project-v1\0" + payload).hexdigest()[:16]
    )


def _valid_file(file: Path) -> bool:
    return (
        file.is_absolute()
        and file.suffix.lower() == _PROJECT_SUFFIX
        and _STEM.fullmatch(file.stem) is not None
        and file.is_file()
        and not file.is_symlink()
        and not file.is_junction()
        and file.resolve(strict=True) == file
        and read_windows_project_presence(file.parent, file.stem).get("projectPresent") is True
    )


def resolve(
    project: WindowsEnrolledDevice | WindowsRegisteredProject, pid: str
) -> OperatorProject | None:
    try:
        identity = _identity(project, pid)
        raw = read_credential(_slot(identity), "secondary_project")
        if raw is None:
            return None
        data = json.loads(raw, object_pairs_hook=_unique)
        file = Path(data["file"])
        if data != {**identity, "file": str(file)} or not _valid_file(file):
            return None
        return OperatorProject(project.device_id, pid, file.parent, file.stem)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RuntimeError):
        return None


def save(project: WindowsEnrolledDevice | WindowsRegisteredProject, pid: str, file: Path) -> bool:
    try:
        identity = _identity(project, pid)
        if not _valid_file(file):
            return False
        slot = _slot(identity)
        blob = json.dumps({**identity, "file": str(file)}, sort_keys=True).encode()
        current = read_credential(slot, "secondary_project")
        if current is None:
            create_credential(slot, "secondary_project", blob)
        elif current != blob:
            return False
        return resolve(project, pid) == OperatorProject(
            project.device_id, pid, file.parent, file.stem
        )
    except (OSError, ValueError, TypeError, RuntimeError):
        return False


def folder_service(
    project: WindowsRegisteredProject,
    selected: WindowsLocalProjectSelection,
    authorized: Callable[[], bool],
) -> BrowserFolderService:
    def on_bound(pid: str, file: Path) -> bool:
        if not authorized():
            return False
        if pid == project.project_id:
            return file == selected.directory / (selected.filename_stem + _PROJECT_SUFFIX)
        return save(project, pid, file)

    def bound_path(pid: str) -> str | None:
        if not authorized():
            return None
        if pid == project.project_id:
            file = selected.directory / (selected.filename_stem + _PROJECT_SUFFIX)
            return str(file) if _valid_file(file) else None
        target = resolve(project, pid)
        if target is None:
            return None
        return str(target.directory / (target.filename_stem + _PROJECT_SUFFIX))

    return BrowserFolderService(
        LocalFolderBrowser([], default_bindings_file()),
        authorization=authorized,
        on_bound=on_bound,
        bound_path=bound_path,
    )


def existing_targets(device: WindowsEnrolledDevice) -> list[OperatorProject]:
    prefix = _device_prefix(_identity(device, device.device_id))
    targets = []
    for slot in list_secondary_slots(prefix):
        try:
            raw = read_credential(slot, "secondary_project")
            if raw is None:
                continue
            data = json.loads(raw, object_pairs_hook=_unique)
            pid = data["projectId"]
            if _slot(_identity(device, pid)) != slot:
                continue
            target = resolve(device, pid)
            if target is not None:
                targets.append(target)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            continue
    return sorted(targets, key=lambda target: target.project_id)


def migrate_legacy(
    device: WindowsEnrolledDevice | WindowsRegisteredProject,
    key: Ed25519PrivateKey,
    authorized: Callable[[], bool],
    primary: str | None,
) -> int:
    """Owner foreground only, with the verified device key and session mutex."""
    from kicad_mcp.cloud_legacy_project_migration import migrate
    from kicad_mcp.cloud_windows_write_issuer import _KICAD_CLOUD_ORIGIN

    if device.origin != _KICAD_CLOUD_ORIGIN:
        return 0

    def completed(pid: str) -> bool:
        identity = _identity(device, pid)
        return read_credential(_slot(identity), "legacy_project_migration") is not None

    def mark(pid: str) -> None:
        identity = _identity(device, pid)
        create_credential(
            _slot(identity),
            "legacy_project_migration",
            json.dumps(identity, sort_keys=True).encode(),
        )

    def publish(pid: str, file: Path) -> bool:
        return authorized() and save(device, pid, file)

    try:
        return migrate(
            origin=device.origin,
            owner=device.owner_sub,
            device=device.device_id,
            primary=primary,
            key=key,
            authorized=authorized,
            completed=completed,
            record_completed=mark,
            save=publish,
        )
    except (OSError, ValueError, TypeError):
        return 0
