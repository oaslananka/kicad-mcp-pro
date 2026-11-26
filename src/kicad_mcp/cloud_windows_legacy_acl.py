"""Conservative Windows ACL checks for legacy local selections.

Read owner and DACL from the existing pinned file handle. This is not an
effective-access calculator: ambiguous ACE types or grants to other writers
are refused, even if a deny ACE might cancel them.
"""

from __future__ import annotations

import ctypes
import os
import struct
from ctypes import wintypes
from functools import lru_cache
from typing import cast

from kicad_mcp.cloud_readonly_boundary import LocalReadDeniedError

_DENIED = "Legacy folder selection ownership or permissions could not be verified."
# GENERIC_READ/EXECUTE, SYNCHRONIZE, READ_CONTROL and file read/execute rights.
_READ_ONLY = 0xA01200A9
_PRIVILEGED = frozenset({"S-1-5-18", "S-1-5-32-544"})
_Ace = tuple[int, int, int, str]


def _owner_only_writers(user: str, owner: str, entries: list[_Ace] | None) -> bool:
    trusted = _PRIVILEGED | {user}
    if not user or owner not in trusted or entries is None:
        return False
    for kind, flags, mask, trustee in entries:
        if flags & 0x08:  # INHERIT_ONLY_ACE: no grant on this object.
            continue
        if kind == 1:  # ACCESS_DENIED_ACE cannot confer write authority.
            continue
        if kind != 0 or (trustee not in trusted and mask & ~_READ_ONLY):
            return False
    return True


class _AclSize(ctypes.Structure):
    _fields_ = [
        ("count", wintypes.DWORD),
        ("used", wintypes.DWORD),
        ("free", wintypes.DWORD),
    ]


@lru_cache(maxsize=1)
def _apis() -> tuple[ctypes.CDLL, ctypes.CDLL]:
    loader = getattr(ctypes, "WinDLL", None)
    if os.name != "nt" or not callable(loader):
        raise LocalReadDeniedError(_DENIED)
    kernel = cast(ctypes.CDLL, loader("kernel32.dll", use_last_error=True, winmode=0x800))
    security = cast(ctypes.CDLL, loader("advapi32.dll", use_last_error=True, winmode=0x800))
    pointer = ctypes.c_void_p
    pp = ctypes.POINTER(pointer)
    kernel.GetCurrentProcess.argtypes = []
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [pointer]
    kernel.LocalFree.restype = pointer
    security.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, pp]
    security.OpenProcessToken.restype = wintypes.BOOL
    security.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        pointer,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    security.GetTokenInformation.restype = wintypes.BOOL
    security.GetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.DWORD,
        pp,
        pp,
        pp,
        pp,
        pp,
    ]
    security.GetSecurityInfo.restype = wintypes.DWORD
    security.GetAclInformation.argtypes = [pointer, pointer, wintypes.DWORD, ctypes.c_int]
    security.GetAclInformation.restype = wintypes.BOOL
    security.GetAce.argtypes = [pointer, wintypes.DWORD, pp]
    security.GetAce.restype = wintypes.BOOL
    security.ConvertSidToStringSidW.argtypes = [pointer, pp]
    security.ConvertSidToStringSidW.restype = wintypes.BOOL
    return kernel, security


def _sid(address: ctypes.c_void_p) -> str:
    kernel, security = _apis()
    result = ctypes.c_void_p()
    if not address.value or not security.ConvertSidToStringSidW(address, ctypes.byref(result)):
        raise LocalReadDeniedError(_DENIED)
    try:
        return ctypes.wstring_at(result)
    finally:
        kernel.LocalFree(result)


def _current_user() -> str:
    kernel, security = _apis()
    token = ctypes.c_void_p()
    if not security.OpenProcessToken(kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)):
        raise LocalReadDeniedError(_DENIED)
    try:
        size = wintypes.DWORD()
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(size))
        if not ctypes.sizeof(ctypes.c_void_p) <= size.value <= 65536:
            raise LocalReadDeniedError(_DENIED)
        data = ctypes.create_string_buffer(size.value)
        if not security.GetTokenInformation(token, 1, data, size.value, ctypes.byref(size)):
            raise LocalReadDeniedError(_DENIED)
        # TOKEN_USER starts with SID_AND_ATTRIBUTES.Sid.
        address = ctypes.c_void_p.from_buffer(data)
        return _sid(address)
    finally:
        kernel.CloseHandle(token)


def _entries(dacl: ctypes.c_void_p) -> list[_Ace] | None:
    if not dacl.value:
        return None  # NULL DACL permits all access.
    _, security = _apis()
    size = _AclSize()
    if not security.GetAclInformation(dacl, ctypes.byref(size), ctypes.sizeof(size), 2):
        raise LocalReadDeniedError(_DENIED)
    if size.count > 1024 or not 8 <= size.used <= 65535:
        raise LocalReadDeniedError(_DENIED)
    return [_read_ace(security, dacl, index, size.used) for index in range(size.count)]


def _read_ace(security: ctypes.CDLL, dacl: ctypes.c_void_p, index: int, used: int) -> _Ace:
    address = ctypes.c_void_p()
    if not security.GetAce(dacl, index, ctypes.byref(address)) or address.value is None:
        raise LocalReadDeniedError(_DENIED)
    kind, flags, length = struct.unpack("<BBH", ctypes.string_at(address, 4))
    if length < 4 or length > used:
        raise LocalReadDeniedError(_DENIED)
    if kind not in (0, 1) or flags & 8:
        return kind, flags, 0, ""
    # Standard allow/deny ACE: header, mask, variable-length SID.
    if length < 16:
        raise LocalReadDeniedError(_DENIED)
    raw = ctypes.string_at(address, length)
    mask = struct.unpack_from("<I", raw, 4)[0]
    if raw[8] != 1 or raw[9] > 15 or 16 + raw[9] * 4 != length:
        raise LocalReadDeniedError(_DENIED)
    return kind, flags, mask, _sid(ctypes.c_void_p(address.value + 8))


def require_private_writers(handle: int) -> None:
    """Only the current user and privileged local OS principals may write."""
    try:
        kernel, security = _apis()
        owner = ctypes.c_void_p()
        dacl = ctypes.c_void_p()
        descriptor = ctypes.c_void_p()
        # SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION.
        result = security.GetSecurityInfo(
            handle,
            1,
            5,
            ctypes.byref(owner),
            None,
            ctypes.byref(dacl),
            None,
            ctypes.byref(descriptor),
        )
        try:
            if result != 0 or not descriptor.value:
                raise LocalReadDeniedError(_DENIED)
            if not _owner_only_writers(_current_user(), _sid(owner), _entries(dacl)):
                raise LocalReadDeniedError(_DENIED)
        finally:
            if descriptor.value:
                kernel.LocalFree(descriptor)
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        raise LocalReadDeniedError(_DENIED) from exc
