#!/usr/bin/env python3
"""Read-only IPC readiness gate for an already launched *isolated* benchmark GUI.

A live socket alone is not proof that KiCad is ready (first-run dialogs can
leave IPC returning AS_NOT_READY). This probe never starts KiCad or an agent,
reserves a benchmark attempt, writes a project or credits a benchmark success.
"""

from __future__ import annotations

import argparse
import json
import re
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any

SCHEMA = "reference-live-gui-readiness.v1"


def _is_existing_socket(ipc_socket: str | None) -> bool:
    """Reject unknown, missing and symlinked IPC addresses before connecting."""
    if (
        not isinstance(ipc_socket, str)
        or not ipc_socket.startswith("ipc:///")
        or len(ipc_socket) > 4096
    ):
        return False
    path = Path(ipc_socket.removeprefix("ipc://"))
    try:
        return not path.is_symlink() and stat.S_ISSOCK(path.lstat().st_mode)
    except OSError:
        return False


def _ipc_failure_reason(exc: Exception) -> str:
    """Use the stable protobuf status, never exception text or private paths."""
    try:
        from kipy.errors import ApiError, ApiStatusCode
    except ImportError:
        return "kicad_gui_ipc_unavailable"
    if isinstance(exc, ApiError) and exc.code == ApiStatusCode.AS_NOT_READY:
        return "kicad_gui_not_ready"
    return "kicad_gui_ipc_unavailable"


def probe_live_gui(
    *,
    ipc_socket: str | None,
    expected_board_name: str | None,
    client_factory: Callable[..., Any] | None = None,
) -> dict[str, object]:
    """Require a real KiCad 10 board IPC response, not a socket presence test."""
    result: dict[str, object] = {
        "schema_version": SCHEMA,
        "status": "blocked",
        "blocking_reasons": [],
        "gui_ready": False,
        "ipc_probe_performed": False,
        "executes_agent": False,
        "attempt_reserved": False,
        "counts_as_task_success": False,
    }

    def block(reason: str) -> dict[str, object]:
        result["blocking_reasons"] = [reason]
        return result

    if not isinstance(expected_board_name, str) or not re.fullmatch(
        r"[A-Za-z0-9_.-]+\.kicad_pcb", expected_board_name
    ):
        return block("expected_board_identity_missing")
    if not _is_existing_socket(ipc_socket):
        return block("private_ipc_socket_missing")

    if client_factory is None:
        try:
            from kipy import KiCad
        except ImportError:
            return block("kicad_ipc_binding_unavailable")
        client_factory = KiCad
    try:
        result["ipc_probe_performed"] = True
        client = client_factory(socket_path=ipc_socket, timeout_ms=3000)
        version = str(client.get_version())
        if re.match(r"10\.\d+(?:\.\d+)?\b", version) is None:
            return block("incompatible_kicad_gui_version")
        board = client.get_board()
        if str(getattr(board, "name", "")) != expected_board_name:
            return block("live_board_identity_mismatch")
    except Exception as exc:
        return block(_ipc_failure_reason(exc))
    result.update(status="ready", gui_ready=True)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ipc-socket", required=True, help="Explicit private IPC Unix socket URI")
    parser.add_argument(
        "--expected-board-name", required=True, help="Exact isolated .kicad_pcb basename"
    )
    args = parser.parse_args(argv)
    result = probe_live_gui(
        ipc_socket=args.ipc_socket, expected_board_name=args.expected_board_name
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
