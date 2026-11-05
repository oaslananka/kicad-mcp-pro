"""Offline, per-device, crash-durable write-proof replay marker.

No network, native KiCad edit, permission grant or background cleanup is
exposed. The marker directory MUST be pre-provisioned by the local operator
as owner-private storage, never selected by a Cloud/agent-supplied field.
Cloud already reserves globally in PostgreSQL; this second fence is local
to one connector device/host and is not a cross-host database.
"""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from kicad_mcp.cloud_pair_keys import _open_owner_private_dir

_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
    re.ASCII,
)


class LocalWriteMarker:
    """Provide the verifier's one-shot callback with atomic O_EXCL files.

    Records are retained rather than silently purged: deleting a live marker
    would weaken replay protection. An operator must separately own any
    future safe-after-expiry maintenance policy. No directory is auto-created.
    """

    def __init__(self, owner_private_directory: Path) -> None:
        self._directory = owner_private_directory

    def consume_once(self, session_id: str, request_id: str) -> bool:
        """Durably consume one UUID exactly once, failing closed on all errors."""
        nofollow = getattr(os, "O_NOFOLLOW", None)
        getuid = getattr(os, "getuid", None)
        if (
            os.name != "posix"
            or type(nofollow) is not int
            or not callable(getuid)
            or not isinstance(self._directory, Path)
            or not self._directory.is_absolute()
            or not isinstance(session_id, str)
            or _UUID.fullmatch(session_id) is None
            or not isinstance(request_id, str)
            or _UUID.fullmatch(request_id) is None
        ):
            return False

        # The UUID is a validated basename only; the directory comes from
        # trusted operator configuration, never a remote command.
        marker = self._directory / (request_id + ".used")
        directory_fd: int | None = None
        file_fd: int | None = None
        try:
            directory_fd = _open_owner_private_dir(marker)
            file_fd = os.open(
                marker.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow | getattr(os, "O_CLOEXEC", 0),
                0o600,
                dir_fd=directory_fd,
            )
            info = os.fstat(file_fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != getuid()
                or info.st_nlink != 1
                or info.st_mode & 0o077
            ):
                return False
            record = session_id.encode("ascii") + b"\n"
            if os.write(file_fd, record) != len(record):
                return False
            # The callback returns True only after both the record and the
            # directory entry are committed. Failed/partial markers are never
            # removed here; retry must fail closed rather than double-execute.
            os.fsync(file_fd)
            os.fsync(directory_fd)
            return True
        except (OSError, ValueError, TypeError):
            return False
        finally:
            if file_fd is not None:
                os.close(file_fd)
            if directory_fd is not None:
                os.close(directory_fd)
