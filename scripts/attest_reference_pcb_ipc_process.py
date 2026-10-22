#!/usr/bin/env python3
"""Read-only Linux PCB GUI/IPC process-isolation diagnostic (not edit approval)."""

from __future__ import annotations

import argparse
import os
import socket
import stat
import struct
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.check_reference_live_gui_readiness import probe_live_gui

_SCHEMA = "reference-pcb-ipc-process-isolation.v1"


def _peer_identity(path: Path) -> tuple[int, int]:
    """Identify the actual kernel IPC server, not a user-supplied process ID."""
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2.0)
        client.connect(str(path))
        pid, uid, _ = struct.unpack(
            "3i", client.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        )
    return pid, uid


def _is_real_scoped_path(path: Path, root: Path) -> bool:
    if (
        not path.is_absolute()
        or path == root
        or not path.is_relative_to(root)
        or ".." in path.parts
    ):
        return False
    current = path
    while current != root:
        # Reject each path component, not merely the final leaf.
        if current.is_symlink():
            return False
        current = current.parent
    return True


def _process_has_expected_board(pid: int, board_file: Path) -> bool:
    if pid <= 0:
        return False
    try:
        proc = Path("/proc") / str(pid)
        try:
            is_editor = Path(os.readlink(proc / "exe")).name == "pcbnew"
        except PermissionError:
            # Linux may restrict /proc/PID/exe across UIDs; /proc/PID/comm is
            # readable on many systems but spoofable. This is observation
            # only and can NEVER enable editing or count task success.
            is_editor = (proc / "comm").read_text().strip() == "pcbnew"
        if not is_editor:
            return False
        arguments = (proc / "cmdline").read_bytes().split(b"\0")
        return os.fsencode(str(board_file)) in arguments
    except OSError:
        return False


@dataclass(frozen=True)
class _FixtureOwners:
    root_uid: int
    socket_uid: int
    board_uid: int
    socket_inode: int


def _fixture_owners(
    endpoint: Path, board_file: Path, root: Path
) -> tuple[_FixtureOwners | None, str | None]:
    if not root.is_absolute() or root.is_symlink() or ".." in root.parts:
        return None, "reviewed_sandbox_root_required"
    try:
        root_stat = root.stat()
        if not stat.S_ISDIR(root_stat.st_mode) or root_stat.st_mode & 0o022:
            return None, "reviewed_sandbox_root_required"
        if not _is_real_scoped_path(endpoint, root) or not _is_real_scoped_path(board_file, root):
            return None, "unscoped_or_symlinked_fixture"
        socket_stat = endpoint.lstat()
        board_stat = board_file.lstat()
        if not stat.S_ISSOCK(socket_stat.st_mode) or not stat.S_ISREG(board_stat.st_mode):
            return None, "private_socket_or_board_missing"
    except OSError:
        return None, "private_socket_or_board_missing"
    return (
        _FixtureOwners(
            root_uid=root_stat.st_uid,
            socket_uid=socket_stat.st_uid,
            board_uid=board_stat.st_uid,
            socket_inode=socket_stat.st_ino,
        ),
        None,
    )


def _dedicated_peer(uid: int, owners: _FixtureOwners) -> bool:
    return uid not in (0, os.getuid()) and (
        owners.root_uid == owners.socket_uid == owners.board_uid == uid
    )


def _peer_still_matches(
    endpoint: Path,
    owners: _FixtureOwners,
    peer: tuple[int, int],
    peer_reader: Callable[[Path], tuple[int, int]],
) -> bool:
    try:
        return endpoint.lstat().st_ino == owners.socket_inode and peer_reader(endpoint) == peer
    except (OSError, ValueError):
        return False


def attest_pcb_process_isolation(
    *,
    socket_uri: str | None,
    board_file: Path,
    sandbox_root: Path,
    peer_reader: Callable[[Path], tuple[int, int]] = _peer_identity,
    process_checker: Callable[[int, Path], bool] = _process_has_expected_board,
    live_probe: Callable[..., dict[str, Any]] = probe_live_gui,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "schema_version": _SCHEMA,
        "status": "blocked",
        "blocking_reasons": [],
        "isolated_gui_attested": False,
        "ipc_board_ready": False,
        "approved_for_editing": False,
        "attempt_reserved": False,
        "executes_agent": False,
        "counts_as_task_success": False,
    }

    def block(reason: str) -> dict[str, Any]:
        result["blocking_reasons"] = [reason]
        return result

    if sys.platform != "linux" or not hasattr(socket, "SO_PEERCRED"):
        return block("linux_peer_credentials_required")
    if (
        not isinstance(socket_uri, str)
        or not socket_uri.startswith("ipc:///")
        or len(socket_uri) > 4096
    ):
        return block("private_socket_required")
    endpoint = Path(socket_uri.removeprefix("ipc://"))
    owners, scope_error = _fixture_owners(endpoint, board_file, sandbox_root)
    if scope_error is not None or owners is None:
        return block(scope_error or "private_socket_or_board_missing")
    try:
        pid, uid = peer_reader(endpoint)
    except (OSError, ValueError, struct.error):
        return block("ipc_peer_identity_unavailable")
    if not _dedicated_peer(uid, owners):
        return block("ipc_peer_not_dedicated_user")
    if not process_checker(pid, board_file):
        return block("ipc_peer_not_expected_pcb_editor")
    diagnostic = live_probe(ipc_socket=socket_uri, expected_board_name=board_file.name)
    if diagnostic["gui_ready"] is not True:
        return block(diagnostic["blocking_reasons"][0])
    if not _peer_still_matches(endpoint, owners, (pid, uid), peer_reader):
        return block("ipc_identity_changed_during_probe")
    result.update(status="observed_isolated_gui", ipc_board_ready=True, isolated_gui_attested=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ipc-socket", required=True)
    parser.add_argument("--board-file", type=Path, required=True)
    parser.add_argument("--sandbox-root", type=Path, required=True)
    args = parser.parse_args(argv)
    import json

    result = attest_pcb_process_isolation(
        socket_uri=args.ipc_socket,
        board_file=args.board_file,
        sandbox_root=args.sandbox_root,
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["isolated_gui_attested"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
