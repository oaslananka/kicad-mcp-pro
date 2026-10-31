"""Fail-closed local identity resolution for the opt-in Cloud CLI.

No network, commands, auto-registration, owner identity proof or privilege
separation. A *trusted offline operator* must provision registry entries;
same-UID/sudo automation can still alter them, so production stays disabled.
"""

from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError, _open_owner_private_dir
from kicad_mcp.cloud_readonly_boundary import _open_operator_directory

_DENIED = "local approval denied"
_UUID = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", re.ASCII
)
_STEM = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", re.ASCII)
_FIELDS = frozenset(
    {"ownerSub", "cloudOrigin", "deviceId", "projectId", "keySlot", "directory", "filenameStem"}
)


@dataclass(frozen=True)
class LocalRegisteredRead:
    key_file: Path
    project_directory: Path
    filename_stem: str


def default_registry_root() -> Path:
    """Fixed application-owned root; not an LLM/CLI supplied path."""
    return Path.home() / ".local" / "share" / "kicad-mcp-cloud"


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    if len({name for name, _ in pairs}) != len(pairs):
        raise LocalApprovalDeniedError(_DENIED)
    return dict(pairs)


def _valid_identity_selectors(owner_sub: str, origin: str, device_id: str, project_id: str) -> bool:
    """Validate public identifier inputs before constructing any registry pathname."""
    return (
        isinstance(owner_sub, str)
        and 1 <= len(owner_sub) <= 256
        and isinstance(origin, str)
        and origin.startswith("https://")
        and 1 <= len(origin) <= 256
        and origin.isascii()
        and isinstance(device_id, str)
        and _UUID.fullmatch(device_id) is not None
        and isinstance(project_id, str)
        and _UUID.fullmatch(project_id) is not None
    )


def resolve_registered_read(
    *,
    owner_sub: str,
    origin: str,
    device_id: str,
    project_id: str,
    # An injectable test fixture root; production CLI never accepts a root.
    registry_root: Path | None = None,
) -> LocalRegisteredRead:
    """Read one pre-provisioned project record; never discover local projects.

    This is a *path-selection* boundary, not independent user verification.
    An authenticated owner must eventually control creation of these records
    from outside the automation process; current CLI does not implement it.
    """
    if not _valid_identity_selectors(owner_sub, origin, device_id, project_id):
        raise LocalApprovalDeniedError(_DENIED)

    root = default_registry_root() if registry_root is None else registry_root
    # The CLI never forwards a path from the LLM into registry_root.
    if not isinstance(root, Path) or not root.is_absolute():
        raise LocalApprovalDeniedError(_DENIED)
    project_record = root / "projects" / (project_id + ".json")

    nofollow = getattr(os, "O_NOFOLLOW", None)
    nonblock = getattr(os, "O_NONBLOCK", None)
    getuid = getattr(os, "getuid", None)
    if (
        os.name != "posix"
        or type(nofollow) is not int
        or type(nonblock) is not int
        or not callable(getuid)
    ):
        raise LocalApprovalDeniedError(_DENIED)

    fd: int | None = None
    folder_fd: int | None = None
    try:
        # Require existing 0700, owner-owned registries and pinned directory
        # handles. A missing root fails closed; no implicit mkdir from reads.
        folder_fd = _open_owner_private_dir(project_record)
        fd = os.open(
            project_record.name,
            os.O_RDONLY | nofollow | nonblock | getattr(os, "O_CLOEXEC", 0),
            dir_fd=folder_fd,
        )
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_uid != getuid()
            or info.st_mode & 0o077
            or not 1 <= info.st_size <= 2048
        ):
            raise LocalApprovalDeniedError(_DENIED)
        document = json.loads(os.read(fd, 2049), object_pairs_hook=_unique)
        if (
            not isinstance(document, dict)
            or set(document) != _FIELDS
            or any(not isinstance(value, str) for value in document.values())
            or document["ownerSub"] != owner_sub
            or document["cloudOrigin"] != origin
            or document["deviceId"] != device_id
            or document["projectId"] != project_id
            or _UUID.fullmatch(document["keySlot"]) is None
            or _STEM.fullmatch(document["filenameStem"]) is None
            or document["filenameStem"] in {".", ".."}
        ):
            raise LocalApprovalDeniedError(_DENIED)
        directory = Path(document["directory"])
        if not directory.is_absolute() or any(
            piece in {".", ".."} for piece in directory.parts[1:]
        ):
            raise LocalApprovalDeniedError(_DENIED)
        pinned = _open_operator_directory(directory)
        os.close(pinned)
        # The only key selector is a validated UUID stored in the private
        # offline registry, never a CLI pathname or Cloud request.
        key_file = root / "keys" / (document["keySlot"] + ".pem")
        key_directory_fd = _open_owner_private_dir(key_file)
        os.close(key_directory_fd)
        return LocalRegisteredRead(
            key_file=key_file,
            project_directory=directory,
            filename_stem=document["filenameStem"],
        )
    except (OSError, ValueError, TypeError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc
    finally:
        if fd is not None:
            os.close(fd)
        if folder_fd is not None:
            os.close(folder_fd)
