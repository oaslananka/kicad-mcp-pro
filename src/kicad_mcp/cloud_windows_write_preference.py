"""Optional owner-only persistent opt-in for an exact paired Windows PCB.

An opt-in never grants Cloud project/client access, trusts an issuer, starts
a Connector, or authorizes a native command. It only remembers the owner's
explicit local choice for later *interactive foreground* sessions.
"""

from __future__ import annotations

import os
import re

from kicad_mcp.cloud_windows_credentials import (
    create_credential,
    delete_credential,
    read_credential,
)
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

_RECORD = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_PROJECT = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z",
    re.ASCII,
)
_DENIED = "request denied"
_PART = "write_preference"


def _value(record_id: str, project_id: str) -> bytes:
    if (
        os.name != "nt"
        or not isinstance(record_id, str)
        or not isinstance(project_id, str)
        or _RECORD.fullmatch(record_id) is None
        or _PROJECT.fullmatch(project_id) is None
    ):
        raise LocalWriteDeniedError(_DENIED)
    return b"owner-write-v1:" + project_id.encode("ascii")


def owner_native_write_remembered(record_id: str, project_id: str) -> bool:
    """Default OFF. Never infer permission for another project or record."""
    expected = _value(record_id, project_id)
    return read_credential(record_id, _PART) == expected


def remember_owner_native_write(record_id: str, project_id: str) -> None:
    """Called only from a verified interactive local owner action."""
    expected = _value(record_id, project_id)
    previous = read_credential(record_id, _PART)
    if previous is None:
        create_credential(record_id, _PART, expected)
    elif previous != expected:
        raise LocalWriteDeniedError(_DENIED)


def forget_owner_native_write(record_id: str, project_id: str) -> bool:
    """Revoke this remembered preference without altering trust anchors."""
    expected = _value(record_id, project_id)
    previous = read_credential(record_id, _PART)
    if previous is None:
        return False
    if previous != expected:
        raise LocalWriteDeniedError(_DENIED)
    return delete_credential(record_id, _PART)
