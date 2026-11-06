"""Inspect one Windows owner-local project reference; never grant Cloud access.

This module only checks consistency among *existing* same-user Credential
Manager entries and independently provided selectors. There is no project
directory or path in this record: the Windows filesystem/reparse boundary,
remote owner approval and current Cloud grant are separate prerequisites.
This is NOT a project enrollment, a local permission, or a Connector switch.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

from kicad_mcp.cloud_local_registry import _STEM, _UUID
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError
from kicad_mcp.cloud_windows_binding import _unique, inspect_local_binding
from kicad_mcp.cloud_windows_credentials import _target, read_credential

_DENIED = "local approval denied"
_FIELDS = frozenset(
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


@dataclass(frozen=True, slots=True)
class WindowsLocalProjectReference:
    """Non-authoritative local project identity; not an access grant."""

    registration_id: str
    record_id: str
    origin: str
    owner_sub: str
    device_id: str
    project_id: str
    filename_stem: str
    fingerprint: str


def inspect_project_reference(
    *,
    registration_id: str,
    record_id: str,
    expected_origin: str,
    expected_owner_sub: str,
    expected_device_id: str,
    expected_project_id: str,
    expected_filename_stem: str,
) -> WindowsLocalProjectReference:
    """Require a separate random project slot bound to an owner key/device.

    Selectors MUST originate from an independent approved local/Cloud action.
    The returned identity is never proof of Cloud authorization. No project
    path is accepted, searched for or opened, and no credential is written.
    """
    if os.name != "nt":
        raise LocalApprovalDeniedError(_DENIED)
    try:
        _target(registration_id, "registration")
        if (
            registration_id == record_id
            or not isinstance(expected_project_id, str)
            or _UUID.fullmatch(expected_project_id) is None
            or not isinstance(expected_filename_stem, str)
            or _STEM.fullmatch(expected_filename_stem) is None
        ):
            raise LocalApprovalDeniedError(_DENIED)

        binding = inspect_local_binding(
            record_id=record_id,
            expected_origin=expected_origin,
            expected_owner_sub=expected_owner_sub,
            expected_device_id=expected_device_id,
        )

        raw = read_credential(registration_id, "registration")
        if raw is None or not 1 <= len(raw) <= 2048:
            raise LocalApprovalDeniedError(_DENIED)
        document = json.loads(raw, object_pairs_hook=_unique)
        if (
            not isinstance(document, dict)
            or set(document) != _FIELDS
            or not all(isinstance(value, str) for value in document.values())
            or document["registrationId"] != registration_id
            or document["recordId"] != binding.record_id
            or document["origin"] != binding.origin
            or document["ownerSub"] != binding.owner_sub
            or document["deviceId"] != binding.device_id
            or document["fingerprint"] != binding.fingerprint
            or document["projectId"] != expected_project_id
            or document["filenameStem"] != expected_filename_stem
        ):
            raise LocalApprovalDeniedError(_DENIED)

        return WindowsLocalProjectReference(
            registration_id=registration_id,
            record_id=binding.record_id,
            origin=binding.origin,
            owner_sub=binding.owner_sub,
            device_id=binding.device_id,
            project_id=expected_project_id,
            filename_stem=expected_filename_stem,
            fingerprint=binding.fingerprint,
        )
    except (OSError, ValueError, TypeError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc
