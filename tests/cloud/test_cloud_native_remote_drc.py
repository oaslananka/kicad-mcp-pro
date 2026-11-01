"""Native one-shot DRC counts must remain separate from the presence pilot."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_mcp.cloud_read_dispatch import LocalReadDispatch
from kicad_mcp.cloud_readonly_boundary import (
    LocalReadDeniedError,
    OperatorProject,
    VerifiedLocalBinding,
)

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
REQUEST = "44444444-4444-4444-8444-444444444444"
NOW = 1_800_000_000_000


def frame(operation: str = "run_drc", **changes: object) -> bytes:
    request: dict[str, object] = {
        "kind": "connector.read_request",
        "version": 1,
        "requestId": REQUEST,
        "deviceId": DEVICE,
        "projectId": PROJECT,
        "operation": operation,
        "deadlineUnixMs": NOW + 1000,
    }
    request.update(changes)
    return json.dumps(request, separators=(",", ":")).encode()


def dispatcher(
    tmp_path: Path, *, native_drc: bool, operations: frozenset[str] | None = None
) -> LocalReadDispatch:
    return LocalReadDispatch(
        verified=VerifiedLocalBinding(
            DEVICE,
            PROJECT,
            frozenset({"run_drc"}) if operations is None else operations,
            SESSION,
            NOW + 15000,
        ),
        operator_project=OperatorProject(DEVICE, PROJECT, tmp_path, "TEST"),
        current_authorization=lambda: True,
        clock_ms=lambda: NOW,
        max_reads=1,
        native_drc=native_drc,
    )


def test_explicit_native_drc_returns_only_counts_and_consumes_one_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    calls = []
    monkeypatch.setattr(
        "kicad_mcp.cloud_read_dispatch.summarize_native_pcb_drc",
        lambda selected: calls.append(selected) or {"violations": 3, "unconnectedItems": 1},
    )
    reader = dispatcher(tmp_path, native_drc=True)
    result = reader.read(frame(), sequence=1)
    assert result == {
        "kind": "connector.local_drc_preview",
        "version": 1,
        "requestId": REQUEST,
        "projectId": PROJECT,
        "operation": "run_drc",
        "counts": {"violations": 3, "unconnectedItems": 1},
    }
    assert len(calls) == 1
    assert "TEST" not in json.dumps(result)
    with pytest.raises(LocalReadDeniedError):
        reader.read(frame(), sequence=2)


@pytest.mark.parametrize(
    ("native", "ops", "operation"),
    [
        (False, frozenset({"run_drc"}), "run_drc"),
        (True, frozenset({"project_summary"}), "run_drc"),
        (True, frozenset({"run_drc"}), "run_erc"),
        (True, frozenset({"run_drc"}), "write_board"),
        (True, frozenset({"run_drc"}), "project_summary"),
    ],
)
def test_operation_downgrade_or_cross_mode_never_runs_native(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    native: bool,
    ops: frozenset[str],
    operation: str,
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.cloud_read_dispatch.summarize_native_pcb_drc",
        lambda _: pytest.fail("native operation must not be invoked"),
    )
    reader = dispatcher(tmp_path, native_drc=native, operations=ops)
    with pytest.raises(LocalReadDeniedError):
        reader.read(frame(operation), sequence=1)


@pytest.mark.parametrize(
    "change",
    [
        {"projectId": "55555555-5555-4555-8555-555555555555"},
        {"deviceId": "66666666-6666-4666-8666-666666666666"},
        {"deadlineUnixMs": NOW},
        {"deadlineUnixMs": NOW + 30001},
        {"filePath": "unauthorized-private-path"},
    ],
)
def test_invalid_binding_or_deadline_denied(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    change: dict[str, object],
) -> None:
    monkeypatch.setattr(
        "kicad_mcp.cloud_read_dispatch.summarize_native_pcb_drc",
        lambda _: pytest.fail("native operation must not be invoked"),
    )
    reader = dispatcher(tmp_path, native_drc=True)
    with pytest.raises(LocalReadDeniedError):
        reader.read(frame(**change), sequence=1)


def test_native_transport_requires_separate_explicit_pilot_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import asyncio
    import json

    from kicad_mcp.cloud_outbound_handshake import (
        CloudHandshakeDeniedError,
        HandshakeReceipt,
        _complete_authorized_read,
    )

    messages = [
        json.dumps(
            {
                "kind": "connector.authorized_read",
                "version": 1,
                "sequence": 1,
                "request": json.loads(frame()),
            }
        ),
        json.dumps(
            {
                "kind": "connector.read_ack",
                "version": 1,
                "sequence": 1,
                "requestId": REQUEST,
            }
        ),
    ]

    class TestSocket:
        def __init__(self) -> None:
            self.sent: list[dict[str, object]] = []

        async def recv(self) -> str:
            return messages.pop(0)

        async def send(self, value: str) -> None:
            self.sent.append(json.loads(value))

    monkeypatch.setattr(
        "kicad_mcp.cloud_read_dispatch.summarize_native_pcb_drc",
        lambda _: {"violations": 1, "unconnectedItems": 0},
    )
    receipt = HandshakeReceipt(DEVICE, SESSION)

    def factory(_: HandshakeReceipt) -> LocalReadDispatch:
        return dispatcher(tmp_path, native_drc=True)

    socket = TestSocket()
    with pytest.raises(CloudHandshakeDeniedError):
        asyncio.run(
            _complete_authorized_read(socket, receipt, factory, operator_presence_pilot=True)
        )
    assert socket.sent == []

    socket = TestSocket()
    messages[:] = [
        json.dumps(
            {
                "kind": "connector.authorized_read",
                "version": 1,
                "sequence": 1,
                "request": json.loads(frame()),
            }
        ),
        json.dumps(
            {
                "kind": "connector.read_ack",
                "version": 1,
                "sequence": 1,
                "requestId": REQUEST,
            }
        ),
    ]
    asyncio.run(
        _complete_authorized_read(
            socket,
            receipt,
            factory,
            operator_presence_pilot=True,
            operator_native_drc_pilot=True,
        )
    )
    assert len(socket.sent) == 1
    result = socket.sent[0]
    assert result["kind"] == "connector.read_result"
    response = result["result"]
    assert isinstance(response, dict)
    assert response["operation"] == "run_drc"
    assert response["counts"] == {"violations": 1, "unconnectedItems": 0}
