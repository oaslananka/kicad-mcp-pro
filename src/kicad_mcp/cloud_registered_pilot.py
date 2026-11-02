"""Owner-terminal entry point for an already-registered, single Cloud project.

A convenience launcher, not an unattended Connector or an alternate
authorization path. The existing operator pilot owns all consent and signing.
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from kicad_mcp import cloud_operator_pilot
from kicad_mcp.cloud_local_registry import (
    _FIELDS,
    _UUID,
    _unique,
    _valid_identity_selectors,
    default_registry_root,
    resolve_registered_read,
)
from kicad_mcp.cloud_pair_keys import LocalApprovalDeniedError, _open_owner_private_dir

_DENIED = "Registered Cloud pilot unavailable; check local registration and owner terminal."
_MODE_FLAGS = {
    "presence": (),
    "inspection": ("--inspection-once",),
    "board-counts": ("--board-counts-once",),
    "schematic-counts": ("--schematic-counts-once",),
    "native-drc": ("--native-drc-once",),
}


def _single_registered_identity(root: Path) -> dict[str, str]:
    """Read only a private, uniquely registered project with no symlink follows."""
    folder = root / "projects"
    # No implicit enrollment, no untrusted path/ID arguments, no selection by
    # whichever record happens to sort first when there are multiple grants.
    names = list(folder.iterdir())
    if len(names) != 1 or names[0].suffix != ".json" or _UUID.fullmatch(names[0].stem) is None:
        raise LocalApprovalDeniedError(_DENIED)

    fd = -1
    directory_fd = -1
    try:
        directory_fd = _open_owner_private_dir(names[0])
        fd = os.open(
            names[0].name,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_nlink != 1
            or info.st_mode & 0o077
            or not 1 <= info.st_size <= 2048
        ):
            raise LocalApprovalDeniedError(_DENIED)
        record = json.loads(os.read(fd, 2049), object_pairs_hook=_unique)
        if (
            not isinstance(record, dict)
            or record.keys() != _FIELDS
            or any(not isinstance(value, str) for value in record.values())
            or record["projectId"] != names[0].stem
            or not _valid_identity_selectors(
                record["ownerSub"], record["cloudOrigin"], record["deviceId"], record["projectId"]
            )
        ):
            raise LocalApprovalDeniedError(_DENIED)
        selected = resolve_registered_read(
            owner_sub=record["ownerSub"],
            origin=record["cloudOrigin"],
            device_id=record["deviceId"],
            project_id=record["projectId"],
            registry_root=root,
        )
        key_info = selected.key_file.lstat()
        if (
            not stat.S_ISREG(key_info.st_mode)
            or key_info.st_uid != os.getuid()
            or key_info.st_nlink != 1
            or key_info.st_mode & 0o077
        ):
            raise LocalApprovalDeniedError(_DENIED)
        return record
    except (OSError, ValueError, TypeError) as exc:
        raise LocalApprovalDeniedError(_DENIED) from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Foreground one-shot KiCad Cloud operation for one pre-registered local project"
    )
    parser.add_argument("--mode", choices=tuple(_MODE_FLAGS), default="presence")
    options = parser.parse_args(argv)
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(
            "An interactive owner terminal is required; no unattended Cloud access.",
            file=sys.stderr,
        )
        return 1
    try:
        record = _single_registered_identity(default_registry_root())
    except (LocalApprovalDeniedError, OSError, ValueError):
        print(_DENIED, file=sys.stderr)
        return 1
    return cloud_operator_pilot.main(
        [
            "--cloud-origin",
            record["cloudOrigin"],
            "--owner-sub",
            record["ownerSub"],
            "--device-id",
            record["deviceId"],
            "--project-id",
            record["projectId"],
            "--allow-once",
            *_MODE_FLAGS[options.mode],
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
