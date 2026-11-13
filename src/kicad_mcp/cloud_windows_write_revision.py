"""Read-only SHA-256 guard for one owner-approved Win32 KiCad PCB file.

This does not execute any native KiCad mutation or create a write grant. Every
directory ancestor and the board file are opened without following reparse
points; the board is read from an immutable Win32 handle that denies concurrent
writers and delete/replace for the duration of the inspection.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from pathlib import Path
from typing import BinaryIO

from kicad_mcp.cloud_readonly_boundary import OperatorProject
from kicad_mcp.cloud_windows_project_path import _api, _open_checked, _pinned_project
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

_MAX_BOARD_BYTES = 128 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", re.ASCII)
_SHA256 = re.compile(r"[0-9a-f]{64}", re.ASCII)
_DENIED = "request denied"


def _check_revision_inputs(policy: OperatorProject, expected_sha256: str) -> None:
    if (
        os.name != "nt"
        or not isinstance(policy, OperatorProject)
        or not isinstance(policy.directory, Path)
        or not policy.directory.is_absolute()
        or not isinstance(policy.filename_stem, str)
        or _NAME.fullmatch(policy.filename_stem) is None
        or policy.filename_stem in {".", ".."}
        or not isinstance(expected_sha256, str)
        or _SHA256.fullmatch(expected_sha256) is None
    ):
        raise LocalWriteDeniedError(_DENIED)


def _open_pinned_board_fd(parent: str, stem: str, binary: int) -> int:
    """Transfer a no-reparse Win32 handle to an owning binary file descriptor."""
    import msvcrt

    handle = _open_checked(parent + "\\" + stem + ".kicad_pcb", directory=False, read_contents=True)
    if handle is None:
        raise LocalWriteDeniedError(_DENIED)
    try:
        return msvcrt.open_osfhandle(handle, os.O_RDONLY | binary)
    except (OSError, ValueError):
        _api().CloseHandle(handle)
        raise


def _digest_pinned_board(reader: BinaryIO) -> str:
    """Refuse concurrent file changes or truncated reads from the pinned handle."""
    before = os.fstat(reader.fileno())
    if not 1 <= before.st_size <= _MAX_BOARD_BYTES:
        raise LocalWriteDeniedError(_DENIED)
    digest = hashlib.sha256()
    remaining = before.st_size
    while remaining:
        chunk = reader.read(min(65536, remaining))
        if not chunk:
            raise LocalWriteDeniedError(_DENIED)
        remaining -= len(chunk)
        digest.update(chunk)
    after = os.fstat(reader.fileno())
    if before.st_size != after.st_size or before.st_mtime_ns != after.st_mtime_ns:
        raise LocalWriteDeniedError(_DENIED)
    return digest.hexdigest()


def verify_windows_board_revision(policy: OperatorProject, expected_sha256: str) -> None:
    """Pin and hash the real local PCB, refusing stale or substituted boards."""
    _check_revision_inputs(policy, expected_sha256)
    try:
        binary = getattr(os, "O_BINARY", None)
        if type(binary) is not int:
            raise LocalWriteDeniedError(_DENIED)
        with _pinned_project(policy.directory) as parent:
            fd = _open_pinned_board_fd(parent, policy.filename_stem, binary)
            with os.fdopen(fd, "rb") as reader:
                actual = _digest_pinned_board(reader)
        if not hmac.compare_digest(actual, expected_sha256):
            raise LocalWriteDeniedError(_DENIED)
    except (OSError, ValueError, TypeError) as exc:
        raise LocalWriteDeniedError(_DENIED) from exc
