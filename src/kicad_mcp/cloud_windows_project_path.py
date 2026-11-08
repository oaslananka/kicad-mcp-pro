"""Windows owner-selected KiCad project presence reads with pinned Win32 handles.

This is a *local filesystem* boundary, NOT a remote access grant, auth,
registration, Connector or automatic project selector. A separately approved
owner action must bind the project identity. We open every directory component
with reparse processing disabled and share-delete denied, retain those handles
until after querying exactly three fixed child file names, and never read
KiCad file contents or follow links. A separate Cloud transport must still
prove current approval before dispatching any request.
"""

from __future__ import annotations

import ctypes
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from functools import lru_cache
from pathlib import Path

from kicad_mcp.cloud_readonly_boundary import LocalReadDeniedError

_DENIED = "Windows KiCad project presence inspection denied."
_STEM = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z", re.ASCII)
_LOCAL_DRIVE = re.compile(r"[A-Za-z]:\\")
_FILE_READ_ATTRIBUTES = 0x0080
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_OPEN_EXISTING = 3
_FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_DIRECTORY = 0x00000010
_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
_FILE_ATTRIBUTE_OFFLINE = 0x00001000
_DRIVE_FIXED = 3
_DRIVE_REMOVABLE = 2
_ERROR_FILE_NOT_FOUND = 2
_ERROR_PATH_NOT_FOUND = 3


class _FileTime(ctypes.Structure):
    _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]


class _FileInfo(ctypes.Structure):
    _fields_ = [
        ("attributes", wintypes.DWORD),
        ("created", _FileTime),
        ("accessed", _FileTime),
        ("written", _FileTime),
        ("volume_serial", wintypes.DWORD),
        ("file_size_high", wintypes.DWORD),
        ("file_size_low", wintypes.DWORD),
        ("links", wintypes.DWORD),
        ("file_index_high", wintypes.DWORD),
        ("file_index_low", wintypes.DWORD),
    ]


@lru_cache(maxsize=1)
def _api() -> ctypes.CDLL:
    if os.name != "nt" or not callable(getattr(ctypes, "WinDLL", None)):
        raise LocalReadDeniedError(_DENIED)
    try:
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        api.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            ctypes.c_void_p,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        api.CreateFileW.restype = wintypes.HANDLE
        api.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(_FileInfo)]
        api.GetFileInformationByHandle.restype = wintypes.BOOL
        api.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]
        api.GetDriveTypeW.restype = wintypes.UINT
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.CloseHandle.restype = wintypes.BOOL
        return api
    except (OSError, AttributeError, TypeError) as exc:
        raise LocalReadDeniedError(_DENIED) from exc


def _path_parts(directory: Path) -> tuple[str, ...]:
    """Only absolute local-drive paths with no traversal/ADS/device namespace."""
    if os.name != "nt" or not isinstance(directory, Path):
        raise LocalReadDeniedError(_DENIED)
    raw = str(directory)
    if (
        len(raw) > 2048
        or "\x00" in raw
        or not _LOCAL_DRIVE.match(raw)
        or "/" in raw
        or raw.endswith((" ", "."))
    ):
        raise LocalReadDeniedError(_DENIED)
    parts = raw.split("\\")
    if not 2 <= len(parts) <= 128 or any(
        not part or part in {".", ".."} or ":" in part or part.endswith((" ", "."))
        for part in parts[1:]
    ):
        raise LocalReadDeniedError(_DENIED)
    root = parts[0] + "\\"
    return (root, *parts[1:])


def _open_checked(path: str, *, directory: bool, missing_ok: bool = False) -> int | None:
    api = _api()
    handle = api.CreateFileW(
        path,
        _FILE_READ_ATTRIBUTES,
        _FILE_SHARE_READ | _FILE_SHARE_WRITE,  # lock against directory renames
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if not handle or handle == invalid:
        error = ctypes.get_last_error()
        if missing_ok and error in {_ERROR_FILE_NOT_FOUND, _ERROR_PATH_NOT_FOUND}:
            return None
        raise LocalReadDeniedError(_DENIED)
    try:
        info = _FileInfo()
        if not api.GetFileInformationByHandle(handle, ctypes.byref(info)):
            raise LocalReadDeniedError(_DENIED)
        if (
            info.attributes & (_FILE_ATTRIBUTE_REPARSE_POINT | _FILE_ATTRIBUTE_OFFLINE)
            or bool(info.attributes & _FILE_ATTRIBUTE_DIRECTORY) != directory
            or (not directory and info.links != 1)
        ):
            raise LocalReadDeniedError(_DENIED)
        return int(handle)
    except BaseException:
        api.CloseHandle(handle)
        raise


@contextmanager
def _pinned_project(directory: Path) -> Iterator[str]:
    """Retain read-only handles for every path hop throughout a presence read."""
    parts = _path_parts(directory)
    api = _api()
    if api.GetDriveTypeW(parts[0]) not in {_DRIVE_FIXED, _DRIVE_REMOVABLE}:
        raise LocalReadDeniedError(_DENIED)
    opened: list[int] = []
    try:
        path = parts[0]
        for component in (None, *parts[1:]):
            if component is not None:
                path = path.rstrip("\\") + "\\" + component
            handle = _open_checked(path, directory=True)
            if handle is None:
                raise LocalReadDeniedError(_DENIED)
            opened.append(handle)
        yield path
    finally:
        for handle in reversed(opened):
            api.CloseHandle(handle)


def read_windows_project_presence(directory: Path, filename_stem: str) -> dict[str, bool]:
    """Read only fixed KiCad filename presence, no bytes, no owner grant."""
    if (
        not isinstance(filename_stem, str)
        or _STEM.fullmatch(filename_stem) is None
        or filename_stem in {".", ".."}
    ):
        raise LocalReadDeniedError(_DENIED)
    try:
        with _pinned_project(directory) as path:
            result = {}
            for kind, extension in (
                ("projectPresent", ".kicad_pro"),
                ("boardPresent", ".kicad_pcb"),
                ("schematicPresent", ".kicad_sch"),
            ):
                handle = _open_checked(
                    path + "\\" + filename_stem + extension,
                    directory=False,
                    missing_ok=True,
                )
                result[kind] = handle is not None
                if handle is not None:
                    _api().CloseHandle(handle)
            return result
    except (OSError, ValueError, TypeError) as exc:
        raise LocalReadDeniedError(_DENIED) from exc
