"""Offline-only expected KiCad board SHA-256 preflight; no mutation."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import stat
from pathlib import Path

from kicad_mcp.cloud_pair_keys import _open_owner_private_dir
from kicad_mcp.cloud_readonly_boundary import OperatorProject
from kicad_mcp.cloud_write_contract import LocalWriteDeniedError

MAX_BOARD_BYTES = 128 * 1024 * 1024
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", re.ASCII)
_SHA = re.compile(r"[0-9a-f]{64}", re.ASCII)
_DENIED = "request denied"


def verify_operator_board_revision(operator_project: OperatorProject, expected_sha256: str) -> None:
    """Read a pinned approved board and fail closed on stale revisions.

    This preflight never grants a write: the native adapter must revalidate
    the same file/revision under its edit lock immediately before mutation.
    Paths and expected hash must come from separately trusted local policy
    and an independently verified signed command, respectively.
    """
    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    getuid = getattr(os, "getuid", None)
    if (
        os.name != "posix"
        or type(nofollow) is not int
        or type(nonblock) is not int
        or not callable(getuid)
        or not isinstance(operator_project, OperatorProject)
        or not isinstance(operator_project.directory, Path)
        or not operator_project.directory.is_absolute()
        or not isinstance(operator_project.filename_stem, str)
        or _NAME.fullmatch(operator_project.filename_stem) is None
        or operator_project.filename_stem in {".", ".."}
        or not isinstance(expected_sha256, str)
        or _SHA.fullmatch(expected_sha256) is None
    ):
        raise LocalWriteDeniedError(_DENIED)

    filename = operator_project.directory / (operator_project.filename_stem + ".kicad_pcb")
    directory_fd: int | None = None
    board_fd: int | None = None
    try:
        directory_fd = _open_owner_private_dir(filename)
        board_fd = os.open(
            filename.name,
            os.O_RDONLY | nofollow | nonblock | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        before = os.fstat(board_fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != getuid()
            or before.st_nlink != 1
            or before.st_mode & 0o022
            or not before.st_mode & 0o200
            or not 1 <= before.st_size <= MAX_BOARD_BYTES
        ):
            raise LocalWriteDeniedError(_DENIED)
        digest = hashlib.sha256()
        read_bytes = 0
        while read_bytes < before.st_size:
            chunk = os.read(board_fd, min(65536, before.st_size - read_bytes))
            if not chunk:
                raise LocalWriteDeniedError(_DENIED)
            digest.update(chunk)
            read_bytes += len(chunk)
        after = os.fstat(board_fd)
        if (
            read_bytes != before.st_size
            or (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            )
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            or not hmac.compare_digest(digest.hexdigest(), expected_sha256)
        ):
            raise LocalWriteDeniedError(_DENIED)
    except (OSError, ValueError, TypeError) as exc:
        raise LocalWriteDeniedError(_DENIED) from exc
    finally:
        if board_fd is not None:
            os.close(board_fd)
        if directory_fd is not None:
            os.close(directory_fd)
