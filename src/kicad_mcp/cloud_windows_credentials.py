"""Windows user-owned Cloud credential primitive (not an enrollment switch).

Only the *current Windows user's* Generic Credential store is used. Despite
its confusing name, CRED_PERSIST_LOCAL_MACHINE persists for the same user
on this computer; it is NOT DPAPI's CRYPTPROTECT_LOCAL_MACHINE (all users).

The existing Cloud CLI must continue to fail closed on Windows until the
entire device registry, signed binding, service and revoke flows are audited.
"""

from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes
from functools import lru_cache
from typing import cast

from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError

_DENIED = "local approval denied"
_RECORD_ID = re.compile(r"[0-9a-f]{32}\Z", re.ASCII)
_PARTS = frozenset(
    {
        "key",
        "binding",
        "registration",
        "project_path",
        "active",
        "selected",
        # Owner-approved recovery keeps the old selection in this same user vault.
        "archived_selected",
        "archived_active",
        "owner_api",
        # A public Ed25519 issuer key independently approved by the local
        # Windows owner. Never a key furnished by a write request itself.
        "write_issuer",
    }
)
_PREFIX = "KiCadMCPPro/Cloud/v1"
_MAX_BLOB_BYTES = 2048
_CRED_TYPE_GENERIC = 1
_CRED_PERSIST_LOCAL_MACHINE = 2  # Per-user, per-machine credential persistence.
_ERROR_NOT_FOUND = 1168


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


class _CredentialW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FileTime),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(wintypes.BYTE)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def _last_error() -> int:
    """Read the Win32 last-error slot only when Windows exposes it."""
    reader = getattr(ctypes, "get_last_error", None)
    if not callable(reader):
        raise LocalApprovalDeniedError(_DENIED)
    error = reader()
    if type(error) is not int:
        raise LocalApprovalDeniedError(_DENIED)
    return error


def _target(record_id: str, part: str) -> str:
    # Never permit arbitrary credential-manager names, user input, or paths.
    if (
        not isinstance(record_id, str)
        or _RECORD_ID.fullmatch(record_id) is None
        or part not in _PARTS
    ):
        raise LocalApprovalDeniedError(_DENIED)
    return f"{_PREFIX}/{record_id}/{part}"


@lru_cache(maxsize=1)
def _api() -> ctypes.CDLL:
    loader = getattr(ctypes, "WinDLL", None)
    if os.name != "nt" or not callable(loader):
        raise LocalApprovalDeniedError(_DENIED)
    try:
        api = loader("Advapi32.dll", use_last_error=True)
        api.CredReadW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.POINTER(ctypes.POINTER(_CredentialW)),
        ]
        api.CredReadW.restype = wintypes.BOOL
        api.CredWriteW.argtypes = [ctypes.POINTER(_CredentialW), wintypes.DWORD]
        api.CredWriteW.restype = wintypes.BOOL
        api.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
        api.CredDeleteW.restype = wintypes.BOOL
        api.CredFree.argtypes = [ctypes.c_void_p]
        api.CredFree.restype = None
        return cast(ctypes.CDLL, api)
    except (OSError, AttributeError, ValueError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc


def read_credential(record_id: str, part: str) -> bytes | None:
    """Read from current user's vault, None only for an absent credential."""
    target = _target(record_id, part)
    api = _api()
    pointer = ctypes.POINTER(_CredentialW)()
    if not api.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(pointer)):
        if _last_error() == _ERROR_NOT_FOUND:
            return None
        raise LocalApprovalDeniedError(_DENIED)
    try:
        entry = pointer.contents
        if (
            entry.Type != _CRED_TYPE_GENERIC
            or entry.Persist != _CRED_PERSIST_LOCAL_MACHINE
            or entry.TargetName != target
            or not 1 <= entry.CredentialBlobSize <= _MAX_BLOB_BYTES
            or not entry.CredentialBlob
        ):
            raise LocalApprovalDeniedError(_DENIED)
        return ctypes.string_at(entry.CredentialBlob, entry.CredentialBlobSize)
    finally:
        api.CredFree(pointer)


def create_credential(record_id: str, part: str, data: bytes) -> None:
    """Create a unique, owner-scoped record. Never intentionally replace one.

    Callers must use a fresh random record ID for each enrollment. Credential
    Manager has no atomic create-only API; this does NOT itself make pairing
    race-safe, so the overall Windows enrollment remains disabled.
    """
    target = _target(record_id, part)
    if not isinstance(data, bytes) or not 1 <= len(data) <= _MAX_BLOB_BYTES:
        raise LocalApprovalDeniedError(_DENIED)
    if read_credential(record_id, part) is not None:
        raise LocalApprovalDeniedError(_DENIED)

    api = _api()
    buffer = (wintypes.BYTE * len(data)).from_buffer_copy(data)
    entry = _CredentialW()
    entry.Type = _CRED_TYPE_GENERIC
    entry.TargetName = target
    entry.CredentialBlobSize = len(data)
    entry.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(wintypes.BYTE))
    entry.Persist = _CRED_PERSIST_LOCAL_MACHINE
    if not api.CredWriteW(ctypes.byref(entry), 0):
        raise LocalApprovalDeniedError(_DENIED)


def delete_credential(record_id: str, part: str) -> bool:
    """Remove only a namespaced record explicitly selected by its random ID."""
    target = _target(record_id, part)
    if _api().CredDeleteW(target, _CRED_TYPE_GENERIC, 0):
        return True
    if _last_error() == _ERROR_NOT_FOUND:
        return False
    raise LocalApprovalDeniedError(_DENIED)
