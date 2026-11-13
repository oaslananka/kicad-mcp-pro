"""Win32 crash-durable replay fence for a future owner-granted Cloud edit.

This module does NOT authorize edits or expose a write transport. Every marker
is created with Windows CREATE_NEW in a fixed current-user LOCALAPPDATA
location; two processes cannot claim the same request even when the Cloud
reservation check races. Directory handles are pinned through no-reparse
CreateFileW checks, and the file is flushed before reporting success.

The trusted user must provision this directory. A Cloud-supplied pathname or
an arbitrary writable/shared directory is never accepted.
"""

from __future__ import annotations

import ctypes
import os
from pathlib import Path

from kicad_mcp.cloud_windows_project_path import _api, _pinned_project

_CREATE_NEW = 1
_FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
_FILE_ATTRIBUTE_NORMAL = 0x00000080
_GENERIC_WRITE = 0x40000000


def default_windows_write_marker_directory() -> Path | None:
    """Use only the current Windows user's fixed, private application folder."""
    if os.name != "nt":
        return None
    appdata = os.environ.get("LOCALAPPDATA")
    if not appdata or not Path(appdata).is_absolute():
        return None
    return Path(appdata) / "KiCadMCPPro" / "Cloud" / "write-markers"


def consume_windows_write_marker(directory: Path, session_id: str, request_id: str) -> bool:
    """Consume a validated request ID exactly once, never creating a directory.

    The caller validates both IDs as strict lowercase UUIDs; this boundary
    independently rejects separator characters to avoid unexpected consumers.
    """
    expected = default_windows_write_marker_directory()
    if (
        os.name != "nt"
        or expected is None
        or not isinstance(directory, Path)
        or directory != expected
        or any(char not in "0123456789abcdef-" for char in request_id + session_id)
        or len(request_id) != 36
        or len(session_id) != 36
    ):
        return False
    try:
        import msvcrt

        binary = getattr(os, "O_BINARY", None)
        if type(binary) is not int:
            return False
        with _pinned_project(directory) as pinned:
            api = _api()
            marker = pinned + "\\" + request_id + ".used"
            handle = api.CreateFileW(
                marker,
                _GENERIC_WRITE,
                0,  # No other reader/writer/deleter while the record is being committed.
                None,
                _CREATE_NEW,  # Atomic O_EXCL equivalent: replay cannot overwrite.
                _FILE_FLAG_OPEN_REPARSE_POINT | _FILE_ATTRIBUTE_NORMAL,
                None,
            )
            if not handle or handle == ctypes.c_void_p(-1).value:
                return False
            try:
                opener = getattr(msvcrt, "open_osfhandle", None)
                if not callable(opener):
                    api.CloseHandle(handle)
                    return False
                fd = opener(handle, os.O_WRONLY | binary)
                if type(fd) is not int:
                    api.CloseHandle(handle)
                    return False
            except (OSError, ValueError):
                api.CloseHandle(handle)
                return False
            try:
                record = session_id.encode("ascii") + b"\n"
                if os.write(fd, record) != len(record):
                    return False
                os.fsync(fd)
                return True
            finally:
                os.close(fd)
    except (OSError, ValueError, TypeError, ImportError):
        # A failed or partial marker is intentionally not deleted. A retry
        # must fail closed rather than execute a command for the second time.
        return False
