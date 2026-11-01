"""Bound, one-shot transport into a real local MCP engine, without Cloud networking."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from kicad_mcp.cloud_outbound_handshake import (
    CloudHandshakeDeniedError,
    HandshakeReceipt,
    _complete_authorized_inspection,
)
from kicad_mcp.cloud_project_worker_bridge import BoundConnectorProjectWorker
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
REQUEST = "44444444-4444-4444-8444-444444444444"


class RecordingSocket:
    def __init__(self, request: dict[str, object]) -> None:
        self.inbound = [
            json.dumps(
                {
                    "kind": "connector.authorized_read",
                    "version": 1,
                    "sequence": 1,
                    "request": request,
                }
            ),
            json.dumps(
                {"kind": "connector.read_ack", "version": 1, "sequence": 1, "requestId": REQUEST}
            ),
        ]
        self.sent: list[dict[str, object]] = []

    async def recv(self) -> str:
        return self.inbound.pop(0)

    async def send(self, value: str) -> None:
        self.sent.append(json.loads(value))


def frame(**changes: object) -> dict[str, object]:
    request: dict[str, object] = {
        "kind": "connector.read_request",
        "version": 1,
        "requestId": REQUEST,
        "deviceId": DEVICE,
        "projectId": PROJECT,
        "operation": "project_worker_inspection",
        "deadlineUnixMs": int(time.time() * 1000) + 30_000,
    }
    request.update(changes)
    return request


def bound_worker(root: Path) -> BoundConnectorProjectWorker:
    return BoundConnectorProjectWorker(
        verified=VerifiedLocalBinding(
            device_id=DEVICE,
            project_id=PROJECT,
            operations=frozenset({"project_worker_inspection"}),
            session_id=SESSION,
            session_expires_unix_ms=int(time.time() * 1000) + 80_000,
        ),
        operator_project=OperatorProject(
            device_id=DEVICE, project_id=PROJECT, directory=root, filename_stem="board"
        ),
        current_authorization=lambda: True,
    )


@pytest.mark.anyio
async def test_real_local_inspection_returns_only_typed_engine_status(tmp_path: Path) -> None:
    root = tmp_path / "private-board"
    root.mkdir()
    (root / "board.kicad_pro").write_text('{"secret": "PRIVATE_DESIGN"}', encoding="utf-8")
    socket = RecordingSocket(frame())
    receipt = HandshakeReceipt(DEVICE, SESSION)
    assert (
        await _complete_authorized_inspection(socket, receipt, lambda _receipt: bound_worker(root))
        == receipt
    )
    assert len(socket.sent) == 1
    body = socket.sent[0]
    assert body["kind"] == "connector.read_result"
    result = body["result"]
    assert result["operation"] == "project_worker_inspection"
    assert result["projectId"] == PROJECT
    assert isinstance(result["status"]["engineVersion"], str)
    assert type(result["status"]["cliAvailable"]) is bool
    assert type(result["status"]["ipcAvailable"]) is bool
    caps = result["status"]["capabilities"]
    assert set(caps) == {"fileBackedDrc", "fileBackedErc", "livePcbRead", "liveSchematicRead"}
    assert all(type(value) is bool for value in caps.values())
    payload = json.dumps(body)
    assert "PRIVATE_DESIGN" not in payload
    assert str(root) not in payload
    assert "cliPath" not in payload


@pytest.mark.anyio
@pytest.mark.parametrize(
    "change",
    [
        {"operation": "run_drc"},
        {"projectId": "55555555-5555-4555-8555-555555555555"},
        {"deviceId": "66666666-6666-4666-8666-666666666666"},
        {"deadlineUnixMs": 1},
        {"arguments": {"tool": "kicad_set_project"}},
    ],
)
async def test_invalid_cloud_operation_never_launches_project_worker(
    tmp_path: Path, change: dict[str, object]
) -> None:
    socket = RecordingSocket(frame(**change))
    invoked = False

    def factory(_receipt: HandshakeReceipt) -> BoundConnectorProjectWorker:
        nonlocal invoked
        invoked = True
        return bound_worker(tmp_path)

    with pytest.raises((CloudHandshakeDeniedError, ValueError)):
        await _complete_authorized_inspection(socket, HandshakeReceipt(DEVICE, SESSION), factory)
    assert socket.sent == []
    # Wrong IDs may be checked by the bound local worker, which still cannot dispatch.
    if "operation" in change or "arguments" in change or "deadlineUnixMs" in change:
        assert not invoked or socket.sent == []
