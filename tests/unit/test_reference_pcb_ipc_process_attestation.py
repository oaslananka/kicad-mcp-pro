"""Isolated PCB IPC attestation is read-only and never grants editing access."""

from __future__ import annotations

import json
import os
import socket
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from scripts import attest_reference_pcb_ipc_process as gate

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux SO_PEERCRED")


@pytest.fixture
def fixture_paths(tmp_path: Path) -> Iterator[tuple[Path, Path, Path]]:
    root = tmp_path / "reviewed"
    root.mkdir(mode=0o700)
    board = root / "fixture.kicad_pcb"
    board.write_text("test-content")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    ipc_path = root / "api.sock"
    server.bind(str(ipc_path))
    server.listen(2)
    try:
        yield root, board, ipc_path
    finally:
        server.close()


def _call(root: Path, board: Path, ipc: Path, **overrides: object) -> dict[str, Any]:
    args = {
        "socket_uri": "ipc://" + str(ipc),
        "board_file": board,
        "sandbox_root": root,
        "peer_reader": lambda _: (777, root.stat().st_uid),
        "process_checker": lambda _pid, _board: True,
        "live_probe": lambda **_: {"gui_ready": True, "blocking_reasons": []},
    }
    args.update(overrides)
    return gate.attest_pcb_process_isolation(**args)


def test_rejects_same_user_gui_even_when_board_and_socket_exist(fixture_paths) -> None:
    root, board, ipc = fixture_paths
    result = _call(root, board, ipc)
    assert result["blocking_reasons"] == ["ipc_peer_not_dedicated_user"]
    assert result["approved_for_editing"] is False
    assert result["counts_as_task_success"] is False


def test_observed_distinct_user_is_only_candidate_not_authorization(
    fixture_paths, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, board, ipc = fixture_paths
    uid = os.getuid()
    monkeypatch.setattr(gate.os, "getuid", lambda: uid + 131)
    r = _call(root, board, ipc)
    assert r["status"] == "observed_isolated_gui"
    assert r["isolated_gui_attested"] is True
    assert r["ipc_board_ready"] is True
    assert r["approved_for_editing"] is False
    assert r["attempt_reserved"] is False
    assert r["executes_agent"] is False
    assert r["counts_as_task_success"] is False
    assert str(root) not in json.dumps(r)


@pytest.mark.parametrize(
    "case,expected",
    [
        ("wrong_process", "ipc_peer_not_expected_pcb_editor"),
        ("switch_peer", "ipc_identity_changed_during_probe"),
        ("gui_unready", "kicad_gui_not_ready"),
    ],
)
def test_attestation_fail_closed(
    fixture_paths, monkeypatch: pytest.MonkeyPatch, case: str, expected: str
) -> None:
    root, board, ipc = fixture_paths
    uid = os.getuid()
    monkeypatch.setattr(gate.os, "getuid", lambda: uid + 131)
    args = {}
    if case == "wrong_process":
        args["process_checker"] = lambda *_: False
    if case == "switch_peer":
        identities = iter([(777, uid), (778, uid)])
        args["peer_reader"] = lambda _: next(identities)
    if case == "gui_unready":
        args["live_probe"] = lambda **_: {
            "gui_ready": False,
            "blocking_reasons": ["kicad_gui_not_ready"],
        }
    r = _call(root, board, ipc, **args)
    assert r["status"] == "blocked"
    assert r["blocking_reasons"] == [expected]
    assert r["approved_for_editing"] is False


def test_symlinked_or_unscoped_socket_never_probed(fixture_paths) -> None:
    root, board, ipc = fixture_paths
    alias = root / "alias.sock"
    alias.symlink_to(ipc)
    for path in (alias, root.parent / "non-review-socket.sock"):
        result = _call(
            root,
            board,
            path,
            peer_reader=lambda *_: pytest.fail("unsafe socket connected"),
        )
        assert result["blocking_reasons"] == ["unscoped_or_symlinked_fixture"]


def test_kernel_peer_credentials_return_actual_owner(fixture_paths) -> None:
    root, _, ipc = fixture_paths
    pid, uid = gate._peer_identity(ipc)
    assert pid == os.getpid()
    assert uid == os.getuid()
    assert str(root) not in str((pid, uid))


def test_wrong_executable_fails_without_fallback_authorization() -> None:
    # No actual GUI or fake process name is allowed to mint edit authorization.
    assert (
        gate._process_has_expected_board(os.getpid(), Path("/usr/tmp/unrelated.kicad_pcb")) is False
    )


def test_lexical_parent_traversal_is_rejected_before_connect(fixture_paths) -> None:
    root, board, ipc = fixture_paths
    disguised = root / "other" / ".." / "api.sock"
    result = _call(
        root,
        board,
        disguised,
        peer_reader=lambda *_: pytest.fail("traversal used before verification"),
    )
    assert result["blocking_reasons"] == ["unscoped_or_symlinked_fixture"]


def test_world_writable_sandbox_root_is_rejected(fixture_paths) -> None:
    root, board, ipc = fixture_paths
    root.chmod(0o777)
    try:
        result = _call(root, board, ipc)
        assert result["blocking_reasons"] == ["reviewed_sandbox_root_required"]
    finally:
        root.chmod(0o700)
