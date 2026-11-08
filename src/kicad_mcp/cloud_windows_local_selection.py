"""Owner-confirmed Windows project selector, with no automatic Cloud permission.

A separate random current-user Credential Manager record binds the
previously confirmed Cloud device/project to an explicitly owner-chosen local
KiCad directory. The Windows handle-based presence boundary rejects unsafe
paths before storing and again before use. No Cloud access is enabled here.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_windows_credentials import (
    create_credential,
    read_credential,
)
from kicad_mcp.cloud_windows_enrollment import WindowsRegisteredProject
from kicad_mcp.cloud_windows_project_path import read_windows_project_presence
from kicad_mcp.cloud_windows_project_record import inspect_project_reference

_DENIED = "Owner-selected local KiCad project path is unavailable."
_FIELDS = frozenset(
    {
        "registrationId",
        "recordId",
        "origin",
        "ownerSub",
        "deviceId",
        "projectId",
        "filenameStem",
        "directory",
    }
)


@dataclass(frozen=True, slots=True)
class WindowsLocalProjectSelection:
    registration_id: str
    record_id: str
    device_id: str
    project_id: str
    filename_stem: str
    directory: Path


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len({key for key, _ in pairs}) != len(pairs):
        raise LocalApprovalDeniedError(_DENIED)
    return dict(pairs)


def _verified_cloud_project(project: WindowsRegisteredProject) -> None:
    if os.name != "nt" or not isinstance(project, WindowsRegisteredProject):
        raise LocalApprovalDeniedError(_DENIED)
    selected = inspect_project_reference(
        registration_id=project.registration_id,
        record_id=project.record_id,
        expected_origin=project.origin,
        expected_owner_sub=project.owner_sub,
        expected_device_id=project.device_id,
        expected_project_id=project.project_id,
        expected_filename_stem=project.filename_stem,
    )
    if selected.fingerprint != project.fingerprint:
        raise LocalApprovalDeniedError(_DENIED)


def bind_owner_selected_project(
    project: WindowsRegisteredProject,
    directory: Path,
    *,
    owner_confirm: Callable[[Path], bool],
) -> WindowsLocalProjectSelection:
    """Record only an explicitly confirmed local path; never enable Cloud."""
    _verified_cloud_project(project)
    if not isinstance(directory, Path):
        raise LocalApprovalDeniedError(_DENIED)
    read = read_windows_project_presence(directory, project.filename_stem)
    if not any(read.values()):
        raise LocalApprovalDeniedError("No matching KiCad file is present.")
    if owner_confirm(directory) is not True:
        raise LocalApprovalDeniedError("The owner did not approve the local project.")
    document = {
        "registrationId": project.registration_id,
        "recordId": project.record_id,
        "origin": project.origin,
        "ownerSub": project.owner_sub,
        "deviceId": project.device_id,
        "projectId": project.project_id,
        "filenameStem": project.filename_stem,
        "directory": str(directory),
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if not 1 <= len(encoded) <= 2048:
        raise LocalApprovalDeniedError(_DENIED)
    create_credential(project.registration_id, "project_path", encoded)
    return inspect_owner_selected_project(project)


def inspect_owner_selected_project(
    project: WindowsRegisteredProject,
) -> WindowsLocalProjectSelection:
    """Require full same-user Cloud record match + recheck Win32 path on read."""
    _verified_cloud_project(project)
    raw = read_credential(project.registration_id, "project_path")
    if not raw or len(raw) > 2048:
        raise LocalApprovalDeniedError(_DENIED)
    try:
        data = json.loads(raw, object_pairs_hook=_unique)
        if (
            not isinstance(data, dict)
            or set(data) != _FIELDS
            or not all(isinstance(value, str) for value in data.values())
            or any(
                data[key] != getattr(project, attr)
                for key, attr in (
                    ("registrationId", "registration_id"),
                    ("recordId", "record_id"),
                    ("origin", "origin"),
                    ("ownerSub", "owner_sub"),
                    ("deviceId", "device_id"),
                    ("projectId", "project_id"),
                    ("filenameStem", "filename_stem"),
                )
            )
        ):
            raise LocalApprovalDeniedError(_DENIED)
        directory = Path(data["directory"])
        if not any(read_windows_project_presence(directory, project.filename_stem).values()):
            raise LocalApprovalDeniedError(_DENIED)
        return WindowsLocalProjectSelection(
            registration_id=project.registration_id,
            record_id=project.record_id,
            device_id=project.device_id,
            project_id=project.project_id,
            filename_stem=project.filename_stem,
            directory=directory,
        )
    except (ValueError, OSError, TypeError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc
