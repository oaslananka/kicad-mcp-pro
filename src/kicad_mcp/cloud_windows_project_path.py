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
from typing import cast

from kicad_mcp.cloud_readonly_boundary import LocalReadDeniedError

_DENIED = "Windows KiCad project presence inspection denied."
_STEM = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z", re.ASCII)
_LOCAL_DRIVE = re.compile(r"[A-Za-z]:\\")
_FILE_READ_ATTRIBUTES = 0x0080
_FILE_GENERIC_READ = 0x80000000
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
    factory = getattr(ctypes, "WinDLL", None)
    if os.name != "nt" or not callable(factory):
        raise LocalReadDeniedError(_DENIED)
    try:
        api = cast(ctypes.CDLL, factory("kernel32", use_last_error=True))
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


def _open_checked(
    path: str, *, directory: bool, missing_ok: bool = False, read_contents: bool = False
) -> int | None:
    api = _api()
    handle = api.CreateFileW(
        path,
        _FILE_GENERIC_READ if read_contents else _FILE_READ_ATTRIBUTES,
        (_FILE_SHARE_READ if read_contents else _FILE_SHARE_READ | _FILE_SHARE_WRITE),
        # Data-read handles also exclude concurrent writers and delete/replace.
        None,
        _OPEN_EXISTING,
        _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_FLAG_BACKUP_SEMANTICS,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if not handle or handle == invalid:
        last_error = getattr(ctypes, "get_last_error", None)
        if not callable(last_error):
            raise LocalReadDeniedError(_DENIED)
        error = int(last_error())
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


def _copy_pinned_input(source: str, destination: Path, *, limit: int, required: bool) -> None:
    """Read from a checked Win32 file HANDLE, not a re-opened pathname.

    Every directory ancestor remains pinned by the caller; the leaf's
    no-reparse, single-link handle is opened without write/delete sharing.
    """
    import msvcrt  # Windows only; the CRT owns the handle after conversion.

    handle = _open_checked(source, directory=False, missing_ok=not required, read_contents=True)
    if handle is None:
        if required:
            raise LocalReadDeniedError(_DENIED)
        return
    # Linux type checking intentionally lacks Windows-only CRT/OS constants.
    # Check at the real Windows boundary rather than type-ignoring or guessing.
    opener = getattr(msvcrt, "open_osfhandle", None)
    binary_flag = getattr(os, "O_BINARY", None)
    if not callable(opener) or type(binary_flag) is not int:
        _api().CloseHandle(handle)
        raise LocalReadDeniedError(_DENIED)
    try:
        fd = opener(handle, os.O_RDONLY | binary_flag)
    except (OSError, ValueError) as exc:
        _api().CloseHandle(handle)
        raise LocalReadDeniedError(_DENIED) from exc
    try:
        with os.fdopen(fd, "rb") as reader:
            before = os.fstat(reader.fileno())
            if not 0 <= before.st_size <= limit:
                raise LocalReadDeniedError(_DENIED)
            with destination.open("xb") as output:
                remaining = limit
                while True:
                    chunk = reader.read(min(65536, remaining + 1))
                    if not chunk:
                        break
                    if len(chunk) > remaining:
                        raise LocalReadDeniedError(_DENIED)
                    output.write(chunk)
                    remaining -= len(chunk)
            after = os.fstat(reader.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise LocalReadDeniedError(_DENIED)
    except (OSError, ValueError) as exc:
        raise LocalReadDeniedError(_DENIED) from exc


def copy_windows_drc_inputs(directory: Path, filename_stem: str, scratch: Path) -> None:
    """Copy only three owner-bound KiCad inputs for offline native DRC.

    This is not a Cloud authorization or native command dispatcher.
    The scratch folder is a caller-created private TemporaryDirectory.
    """
    if (
        os.name != "nt"
        or not isinstance(filename_stem, str)
        or not _STEM.fullmatch(filename_stem)
        or filename_stem in {".", ".."}
        or not isinstance(scratch, Path)
        or not scratch.is_dir()
    ):
        raise LocalReadDeniedError(_DENIED)
    try:
        with _pinned_project(directory) as pinned:
            for extension, limit, required in (
                (".kicad_pcb", 32 * 1024 * 1024, True),
                (".kicad_pro", 4 * 1024 * 1024, False),
                (".kicad_dru", 1024 * 1024, False),
            ):
                name = filename_stem + extension
                _copy_pinned_input(
                    pinned + os.sep + name, scratch / name, limit=limit, required=required
                )
    except (OSError, ValueError, TypeError) as exc:
        raise LocalReadDeniedError(_DENIED) from exc
