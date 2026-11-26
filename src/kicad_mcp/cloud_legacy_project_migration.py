"""One-way import of old local folder selections, gated by signed inventory."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from kicad_mcp import cloud_pair_keys
from kicad_mcp.cloud_folder_browse_receiver import default_bindings_file

_LIMIT = 256 * 1024


def _read_posix(path: Path) -> bytes:
    """Old cache was not necessarily mode 0600; never accept shared writers."""
    getuid = getattr(os, "getuid", None)
    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    if (
        os.name != "posix"
        or not callable(getuid)
        or type(nofollow) is not int
        or type(nonblock) is not int
    ):
        raise ValueError("Unsafe legacy cache platform.")
    uid = getuid()
    folder = cloud_pair_keys._open_owner_directory(path.parent)
    try:
        parent = os.fstat(folder)
        if parent.st_uid != uid or parent.st_mode & 0o022:
            raise ValueError("Unsafe legacy cache directory.")
        fd = os.open(path.name, os.O_RDONLY | nofollow | nonblock, dir_fd=folder)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != uid
                or info.st_nlink != 1
                or info.st_mode & 0o022
                or not 1 <= info.st_size <= _LIMIT
            ):
                raise ValueError("Unsafe legacy cache.")
            raw = os.read(fd, _LIMIT + 1)
            if len(raw) != info.st_size or os.fstat(fd).st_mtime_ns != info.st_mtime_ns:
                raise ValueError("Legacy cache changed.")
            return raw
        finally:
            os.close(fd)
    finally:
        os.close(folder)


def legacy_candidates() -> dict[str, Path]:
    """Read only the historical fixed current-user cache, never a Cloud path."""
    path = default_bindings_file()
    try:
        if os.name == "nt":
            from kicad_mcp.cloud_windows_project_path import read_legacy_folder_cache

            raw = read_legacy_folder_cache(path, _LIMIT)
        else:
            raw = _read_posix(path)
        data = json.loads(raw, object_pairs_hook=cloud_pair_keys._unique)
        if not isinstance(data, dict):
            return {}
        candidates = {}
        for pid, value in data.items():
            if not isinstance(pid, str) or not isinstance(value, str) or len(value) > 2048:
                continue
            try:
                file = Path(value)
                if (
                    str(UUID(pid)) == pid
                    and file.is_absolute()
                    and file.suffix.lower() == ".kicad_pro"
                    and file.is_file()
                    and not file.is_symlink()
                    and not file.is_junction()
                    and file.resolve(strict=True) == file
                ):
                    candidates[pid] = file
            except (OSError, ValueError, RuntimeError):
                continue
        return candidates
    except (OSError, ValueError, TypeError, RuntimeError):
        return {}


def migrate(
    *,
    origin: str,
    owner: str,
    device: str,
    primary: str | None,
    key: Ed25519PrivateKey,
    authorized: Callable[[], bool],
    completed: Callable[[str], bool],
    record_completed: Callable[[str], None],
    save: Callable[[str, Path], bool],
) -> int:
    """Import previously chosen paths only for this authenticated inventory.

    A durable one-way receipt is created before publishing a scoped binding.
    A crash in that narrow window fails closed rather than reviving a revoked
    local binding on a later startup. No Cloud registration or grant is made.
    """
    from kicad_mcp.cloud_device_inventory_status import inspect_inventory

    if not authorized():
        return 0
    candidates = legacy_candidates()
    pending = [pid for pid in sorted(candidates) if pid != primary and not completed(pid)]
    count = 0
    for pid in pending[:25]:
        if not authorized():
            break
        state = inspect_inventory(origin, owner, device, pid, key)
        if state not in {"active", "project_disabled", "project_missing"}:
            break
        if not authorized() or legacy_candidates().get(pid) != candidates[pid]:
            break
        record_completed(pid)
        if state != "project_missing" and save(pid, candidates[pid]):
            count += 1
    return count
