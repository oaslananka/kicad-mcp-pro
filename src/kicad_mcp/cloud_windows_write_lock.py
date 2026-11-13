"""Win32 owner-project native transaction lock using the OS sharing boundary.

No network route or write tool is exposed. The trusted operator supplies one
fixed KiCad project; the per-project lock lives in the current user's private
Cloud app directory rather than writing into the KiCad project folder.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from kicad_mcp.cloud_windows_project_path import (
    _FILE_ATTRIBUTE_OFFLINE,
    _FILE_ATTRIBUTE_REPARSE_POINT,
    _api,
    _FileInfo,
    _pinned_project,
)
from kicad_mcp.cloud_windows_write_marker import default_windows_write_marker_directory
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

_GENERIC_READ_WRITE = 0x80000000 | 0x40000000
_OPEN_ALWAYS = 4
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_DENIED = "request denied"


def _open_checked_exclusive_lock(api: object, filename: str, binary: int) -> int:
    """Open a single-link empty file with native exclusive Win32 sharing."""
    import msvcrt

    handle = api.CreateFileW(
        filename,
        _GENERIC_READ_WRITE,
        0,  # No competing writer or deleter while this lock is open.
        None,
        _OPEN_ALWAYS,
        _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_ATTRIBUTE_NORMAL,
        None,
    )
    if not handle or handle == ctypes.c_void_p(-1).value:
        raise LocalWriteDeniedError(_DENIED)
    try:
        info = _FileInfo()
        if (
            not api.GetFileInformationByHandle(handle, ctypes.byref(info))
            or info.attributes & (_FILE_ATTRIBUTE_OFFLINE | _FILE_ATTRIBUTE_REPARSE_POINT)
            or info.attributes & 0x10
            or info.links != 1
            or info.file_size_low != 0
            or info.file_size_high != 0
        ):
            raise LocalWriteDeniedError(_DENIED)
        return msvcrt.open_osfhandle(handle, os.O_RDWR | binary)
    except BaseException:
        api.CloseHandle(handle)
        raise


@contextmanager
def lock_windows_operator_project(directory: Path, stem: str) -> Iterator[None]:
    """Hold no-reparse ancestor handles and an exclusive, per-board file lock."""
    expected = default_windows_write_marker_directory()
    if (
        os.name != "nt"
        or expected is None
        or not isinstance(directory, Path)
        or not directory.is_absolute()
        or not isinstance(stem, str)
        or not stem
    ):
        raise LocalWriteDeniedError(_DENIED)
    fd: int | None = None
    try:
        binary = getattr(os, "O_BINARY", None)
        if type(binary) is not int:
            raise LocalWriteDeniedError(_DENIED)
        name = hashlib.sha256((str(directory).casefold() + "\x00" + stem).encode()).hexdigest()
        with _pinned_project(directory), _pinned_project(expected) as pinned:
            fd = _open_checked_exclusive_lock(_api(), pinned + "\\" + name + ".lock", binary)
            yield  # The handles protect both directories and the lock itself.
    except (OSError, ValueError, TypeError) as exc:
        raise LocalWriteDeniedError(_DENIED) from exc
    finally:
        if fd is not None:
            os.close(fd)
