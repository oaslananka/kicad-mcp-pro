"""Win32 owner-project native transaction lock using the OS sharing boundary.

No network route or write tool is exposed. The trusted operator supplies one
fixed KiCad project; the per-project lock lives in the current user's private
Cloud app directory rather than writing into the KiCad project folder.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

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


class _Win32FileApi(NamedTuple):
    """Narrow typed wrapper over dynamic Windows DLL function names."""

    create: Callable[..., int]
    file_info: Callable[..., bool]
    close: Callable[..., bool]


def _validated_api() -> _Win32FileApi:
    dll = _api()
    create = getattr(dll, "CreateFileW", None)
    file_info = getattr(dll, "GetFileInformationByHandle", None)
    close = getattr(dll, "CloseHandle", None)
    if not callable(create) or not callable(file_info) or not callable(close):
        raise LocalWriteDeniedError(_DENIED)
    return _Win32FileApi(create, file_info, close)


def _open_checked_exclusive_lock(api: _Win32FileApi, filename: str, binary: int) -> int:
    """Open a single-link empty file with native exclusive Win32 sharing."""
    import msvcrt

    handle = api.create(
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
            not api.file_info(handle, ctypes.byref(info))
            or info.attributes & (_FILE_ATTRIBUTE_OFFLINE | _FILE_ATTRIBUTE_REPARSE_POINT)
            or info.attributes & 0x10
            or info.links != 1
            or info.file_size_low != 0
            or info.file_size_high != 0
        ):
            raise LocalWriteDeniedError(_DENIED)
        opener = getattr(msvcrt, "open_osfhandle", None)
        if not callable(opener):
            raise LocalWriteDeniedError(_DENIED)
        fd = opener(handle, os.O_RDWR | binary)
        if type(fd) is not int:
            raise LocalWriteDeniedError(_DENIED)
        return int(fd)
    except BaseException:
        api.close(handle)
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
            fd = _open_checked_exclusive_lock(
                _validated_api(), pinned + "\\" + name + ".lock", binary
            )
            yield  # The handles protect both directories and the lock itself.
    except (OSError, ValueError, TypeError) as exc:
        raise LocalWriteDeniedError(_DENIED) from exc
    finally:
        if fd is not None:
            os.close(fd)
