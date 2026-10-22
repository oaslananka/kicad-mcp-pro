"""Readiness must be based on actual board replies, not socket existence."""

from __future__ import annotations

import json
import os
import socket
from collections.abc import Iterator
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest
from kipy.errors import ApiError, ApiStatusCode

from scripts import check_reference_live_gui_readiness as gate

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX Unix socket readiness gate")


@pytest.fixture
def ipc_socket() -> Iterator[tuple[socket.socket, str]]:
    # Avoid Unix sockaddr path-length limits in deeply nested CI pytest temp roots.
    with TemporaryDirectory(prefix="kicad-ipc-") as directory:
        name = Path(directory) / "api.sock"
        server = socket.socket(socket.AF_UNIX)
        try:
            server.bind(str(name))
            yield server, "ipc://" + str(name)
        finally:
            server.close()


def test_available_private_socket_with_confirmed_board_is_ready(
    ipc_socket: tuple[socket.socket, str],
) -> None:
    listener, endpoint = ipc_socket
    seen: list[tuple[str, int]] = []

    class Client:
        def get_version(self):
            return "10.0.7 (ubuntu)"

        def get_board(self):
            return SimpleNamespace(name="fixture.kicad_pcb")

    def factory(*, socket_path: str, timeout_ms: int):
        seen.append((socket_path, timeout_ms))
        return Client()

    try:
        r = gate.probe_live_gui(
            ipc_socket=endpoint, expected_board_name="fixture.kicad_pcb", client_factory=factory
        )
    finally:
        listener.close()
    assert r["status"] == "ready"
    assert r["gui_ready"] is True
    assert r["blocking_reasons"] == []
    assert seen == [(endpoint, 3000)]
    assert r["counts_as_task_success"] is False
    assert r["executes_agent"] is False
    assert r["attempt_reserved"] is False
    assert endpoint not in json.dumps(r)


def test_real_socket_with_kicad_first_run_modal_is_blocked(
    ipc_socket: tuple[socket.socket, str],
) -> None:
    listener, endpoint = ipc_socket

    class Client:
        def get_version(self):
            raise ApiError("private workstation path", code=ApiStatusCode.AS_NOT_READY)

    try:
        r = gate.probe_live_gui(
            ipc_socket=endpoint,
            expected_board_name="fixture.kicad_pcb",
            client_factory=lambda **_: Client(),
        )
    finally:
        listener.close()
    assert r["status"] == "blocked"
    assert r["blocking_reasons"] == ["kicad_gui_not_ready"]
    assert r["ipc_probe_performed"] is True
    assert r["counts_as_task_success"] is False
    assert "private workstation path" not in json.dumps(r)


@pytest.mark.parametrize(
    ("mode", "reason"),
    [
        ("board_mismatch", "live_board_identity_mismatch"),
        ("wrong_version", "incompatible_kicad_gui_version"),
        ("unavailable", "kicad_gui_ipc_unavailable"),
    ],
)
def test_bounded_read_only_probe_rejects_unusable_gui(
    ipc_socket: tuple[socket.socket, str], mode: str, reason: str
) -> None:
    listener, endpoint = ipc_socket

    class Client:
        def get_version(self):
            if mode == "unavailable":
                raise OSError("user path")
            return "11.0.0" if mode == "wrong_version" else "10.0.7"

        def get_board(self):
            return SimpleNamespace(name="other.kicad_pcb")

    try:
        result = gate.probe_live_gui(
            ipc_socket=endpoint,
            expected_board_name="fixture.kicad_pcb",
            client_factory=lambda **_: Client(),
        )
    finally:
        listener.close()
    assert result["blocking_reasons"] == [reason]
    assert result["status"] == "blocked"
    assert "user path" not in json.dumps(result)


def test_no_socket_or_unreviewed_symlink_is_rejected_without_client_invocation(
    tmp_path: Path, ipc_socket: tuple[socket.socket, str]
) -> None:
    linked = tmp_path / "alias.sock"
    listener, endpoint = ipc_socket
    linked.symlink_to(Path(endpoint.removeprefix("ipc://")))

    def fail(**_: object):
        raise AssertionError("must fail before IPC access")

    try:
        for value in (
            None,
            "tcp://127.0.0.1:1",
            "ipc:///tmp/not-existing.sock",
            "ipc://" + str(linked),
        ):
            r = gate.probe_live_gui(
                ipc_socket=value, expected_board_name="fixture.kicad_pcb", client_factory=fail
            )
            assert r["status"] == "blocked"
            assert r["ipc_probe_performed"] is False
    finally:
        listener.close()
    assert endpoint.startswith("ipc:///")


def test_expected_board_identity_is_mandatory(
    ipc_socket: tuple[socket.socket, str],
) -> None:
    listener, endpoint = ipc_socket
    try:
        for name in (None, "", "../../private.kicad_pcb", "other.sch", "a/b.kicad_pcb"):
            r = gate.probe_live_gui(
                ipc_socket=endpoint, expected_board_name=name, client_factory=lambda **_: None
            )
            assert r["blocking_reasons"] == ["expected_board_identity_missing"]
    finally:
        listener.close()


def test_gui_becomes_not_ready_during_board_read(
    ipc_socket: tuple[socket.socket, str],
) -> None:
    listener, endpoint = ipc_socket

    class Client:
        def get_version(self):
            return "10.0.7"

        def get_board(self):
            raise ApiError("private dialogue", code=ApiStatusCode.AS_NOT_READY)

    try:
        r = gate.probe_live_gui(
            ipc_socket=endpoint,
            expected_board_name="fixture.kicad_pcb",
            client_factory=lambda **_: Client(),
        )
    finally:
        listener.close()
    assert r["status"] == "blocked"
    assert r["blocking_reasons"] == ["kicad_gui_not_ready"]
    assert "private dialogue" not in json.dumps(r)
