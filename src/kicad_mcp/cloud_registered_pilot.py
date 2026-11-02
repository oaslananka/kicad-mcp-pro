"""Owner-terminal entry point for an already-registered, single Cloud project.

A convenience launcher, not an unattended Connector or an alternate
authorization path. The existing operator pilot owns all consent and signing.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import stat
import sys
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException

from kicad_mcp import cloud_operator_pilot
from kicad_mcp.cloud_local_registry import (
    _FIELDS,
    _UUID,
    _unique,
    _valid_identity_selectors,
    default_registry_root,
    resolve_registered_read,
)
from kicad_mcp.cloud_outbound_handshake import _endpoint
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

    fd = -1
    directory_fd = -1
    try:
        directory_fd = _open_owner_private_dir(names[0])
        fd = os.open(
            names[0].name,
            os.O_RDONLY | nofollow | nonblock | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_fd,
        )
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != getuid()
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
            or key_info.st_uid != getuid()
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


async def _check_transport(origin: str) -> None:
    """Check only the TLS WebSocket upgrade; never send device identity or proof."""
    endpoint = _endpoint(origin=origin, trusted_origin=origin)
    # Both connection setup and shutdown are individually bounded; no extra
    # cancellation scope is needed for a handshake-only probe.
    async with connect(
        endpoint,
        origin=None,
        compression=None,
        max_size=1024,
        max_queue=2,
        open_timeout=5,
        close_timeout=2,
    ) as socket:
        if socket.transport.get_extra_info("ssl_object") is None:
            raise ValueError("unverified Cloud TLS")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Foreground one-shot KiCad Cloud operation for one pre-registered local project"
    )
    parser.add_argument("--mode", choices=tuple(_MODE_FLAGS), default="presence")
    parser.add_argument(
        "--check-transport",
        action="store_true",
        help="Check Cloud TLS/WebSocket ingress without sending device credentials",
    )
    options = parser.parse_args(argv)
    if options.check_transport:
        if options.mode != "presence":
            parser.error("--check-transport cannot be combined with an operation mode")
        try:
            record = _single_registered_identity(default_registry_root())
            asyncio.run(_check_transport(record["cloudOrigin"]))
        except (OSError, ValueError, WebSocketException):
            print("Cloud Connector transport is unavailable", file=sys.stderr)
            return 1
        print("Cloud Connector TLS/WebSocket ingress reachable; device not connected")
        return 0
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print(
            "An interactive owner terminal is required; no unattended Cloud access.",
            file=sys.stderr,
        )
        return 1
    try:
        record = _single_registered_identity(default_registry_root())
    except (OSError, ValueError):
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
