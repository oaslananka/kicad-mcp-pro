"""Post-authenticated managed reads do not authenticate a device or start a service."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from uuid import UUID

import pytest

from kicad_mcp.cloud_managed_read_transport import serve_authenticated_reads
from kicad_mcp.cloud_outbound_handshake import CloudHandshakeDeniedError, HandshakeReceipt
from kicad_mcp.cloud_read_dispatch import LocalReadDispatch
from kicad_mcp.cloud_readonly_boundary import (
    LocalReadDeniedError,
    OperatorProject,
    VerifiedLocalBinding,
)

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"


def request(sequence: int, **changes: object) -> str:
    frame: dict[str, object] = {
        "kind": "connector.read_request",
        "version": 1,
        "requestId": str(UUID(int=sequence + 5, version=4)),
        "deviceId": DEVICE,
        "projectId": PROJECT,
        "operation": "project_summary",
        "deadlineUnixMs": int(time.time() * 1000) + 30_000,
    }
    frame.update(changes)
    return json.dumps(
        {"kind": "connector.authorized_read", "version": 1, "sequence": sequence, "request": frame}
    )


class Socket:
    def __init__(
        self, incoming: list[str], *, revoke_after: int = 0, grant: list[bool] | None = None
    ) -> None:
        self.incoming: asyncio.Queue[str] = asyncio.Queue()
        if incoming:
            self.incoming.put_nowait(incoming[0])
        self.scheduled = list(incoming[1:])
        self.sent: list[dict[str, object]] = []
        self.revoke_after = revoke_after
        self.grant = grant

    async def recv(self) -> str:
        return await self.incoming.get()

    async def send(self, value: str) -> None:
        message = json.loads(value)
        self.sent.append(message)
        if self.grant is not None and len(self.sent) == self.revoke_after:
            self.grant[0] = False
        self.incoming.put_nowait(
            json.dumps(
                {
                    "kind": "connector.read_ack",
                    "version": 1,
                    "sequence": message["sequence"],
                    "requestId": message["result"]["requestId"],
                }
            )
        )
        if self.scheduled:
            self.incoming.put_nowait(self.scheduled.pop(0))


def build_dispatcher(root: Path, grant: list[bool]) -> LocalReadDispatch:
    return LocalReadDispatch(
        verified=VerifiedLocalBinding(
            device_id=DEVICE,
            project_id=PROJECT,
            operations=frozenset({"project_summary"}),
            session_id=SESSION,
            session_expires_unix_ms=int(time.time() * 1000) + 240_000,
        ),
        operator_project=OperatorProject(
            device_id=DEVICE,
            project_id=PROJECT,
            directory=root,
            filename_stem="board",
        ),
        current_authorization=lambda: grant[0],
        max_reads=16,
    )


@pytest.mark.anyio
async def test_two_successive_reads_on_same_authenticated_socket(tmp_path: Path) -> None:
    (tmp_path / "board.kicad_pro").write_text('{"not_transmitted": "SECRET"}')
    grant = [True]
    socket = Socket([request(1), request(2)])
    dispatcher = build_dispatcher(tmp_path, grant)
    receipt = HandshakeReceipt(DEVICE, SESSION)
    assert (
        await serve_authenticated_reads(socket, receipt, lambda _: dispatcher, max_reads=2)
        == receipt
    )
    assert [item["sequence"] for item in socket.sent] == [1, 2]
    for item in socket.sent:
        assert item["result"]["files"]["projectPresent"] is True
        assert "SECRET" not in json.dumps(item)
        assert str(tmp_path) not in json.dumps(item)


@pytest.mark.anyio
async def test_owner_off_blocks_next_read_without_delivering_anything(tmp_path: Path) -> None:
    grant = [True]
    socket = Socket([request(1), request(2)], revoke_after=1, grant=grant)
    dispatcher = build_dispatcher(tmp_path, grant)
    receipt = HandshakeReceipt(DEVICE, SESSION)
    with pytest.raises((LocalReadDeniedError, CloudHandshakeDeniedError)):
        await serve_authenticated_reads(socket, receipt, lambda _: dispatcher, max_reads=2)
    assert [item["sequence"] for item in socket.sent] == [1]
    post_revoke_frame = json.loads(request(3))["request"]
    post_revoke_payload = json.dumps(post_revoke_frame).encode()
    with pytest.raises(LocalReadDeniedError):
        dispatcher.read(post_revoke_payload, sequence=3)


@pytest.mark.anyio
@pytest.mark.parametrize("second", [1, 3, 0, -1, True])
async def test_replay_out_of_order_or_invalid_sequences_fail_closed(
    tmp_path: Path, second: object
) -> None:
    raw = json.loads(request(2))
    raw["sequence"] = second
    socket = Socket([request(1), json.dumps(raw)])
    receipt = HandshakeReceipt(DEVICE, SESSION)
    dispatcher = build_dispatcher(tmp_path, [True])
    with pytest.raises((LocalReadDeniedError, CloudHandshakeDeniedError)):
        await serve_authenticated_reads(
            socket,
            receipt,
            lambda _: dispatcher,
            max_reads=2,
        )
    assert len(socket.sent) == 1


@pytest.mark.anyio
async def test_rejects_unexpected_ack_without_next_response(tmp_path: Path) -> None:
    class InvalidAck(Socket):
        async def send(self, value: str) -> None:
            self.sent.append(json.loads(value))
            self.incoming.put_nowait(
                json.dumps(
                    {
                        "kind": "connector.read_ack",
                        "version": 1,
                        "sequence": 500,
                        "requestId": self.sent[-1]["result"]["requestId"],
                    }
                )
            )

    socket = InvalidAck([request(1), request(2)])
    receipt = HandshakeReceipt(DEVICE, SESSION)
    dispatcher = build_dispatcher(tmp_path, [True])
    with pytest.raises(CloudHandshakeDeniedError):
        await serve_authenticated_reads(
            socket,
            receipt,
            lambda _: dispatcher,
            max_reads=2,
        )
    assert len(socket.sent) == 1


@pytest.mark.anyio
async def test_cross_session_receipt_is_not_authority(tmp_path: Path) -> None:
    socket = Socket([request(1)])
    receipt = HandshakeReceipt(DEVICE, "99999999-9999-4999-8999-999999999999")
    dispatcher = build_dispatcher(tmp_path, [True])
    with pytest.raises(LocalReadDeniedError):
        await serve_authenticated_reads(
            socket,
            receipt,
            lambda _: dispatcher,
            max_reads=1,
        )
    assert socket.sent == []


@pytest.mark.anyio
async def test_revocation_while_local_inspection_is_running_drops_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import threading

    from kicad_mcp import cloud_read_dispatch

    entered = threading.Event()
    resume = threading.Event()
    original = cloud_read_dispatch.inspect_readonly

    def delayed_inspection(*args: object, **kwargs: object) -> dict[str, object]:
        entered.set()
        assert resume.wait(timeout=5)
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(cloud_read_dispatch, "inspect_readonly", delayed_inspection)
    grant = [True]
    socket = Socket([request(1)])
    dispatcher = build_dispatcher(tmp_path, grant)
    task = asyncio.create_task(
        serve_authenticated_reads(
            socket, HandshakeReceipt(DEVICE, SESSION), lambda _: dispatcher, max_reads=1
        )
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        grant[0] = False
    finally:
        resume.set()
    with pytest.raises(LocalReadDeniedError):
        await task
    assert socket.sent == []


@pytest.mark.anyio
async def test_native_read_is_rejected_even_on_authenticated_socket(tmp_path: Path) -> None:
    socket = Socket([request(1, operation="run_drc")])
    receipt = HandshakeReceipt(DEVICE, SESSION)
    dispatcher = build_dispatcher(tmp_path, [True])
    with pytest.raises(LocalReadDeniedError):
        await serve_authenticated_reads(
            socket,
            receipt,
            lambda _: dispatcher,
            max_reads=1,
        )
    assert socket.sent == []


@pytest.mark.anyio
@pytest.mark.parametrize("max_reads", [0, 17, True, 1.0, -1])
async def test_invalid_session_read_budgets_are_rejected(tmp_path: Path, max_reads: object) -> None:
    socket = Socket([request(1)])
    receipt = HandshakeReceipt(DEVICE, SESSION)
    dispatcher = build_dispatcher(tmp_path, [True])
    with pytest.raises(CloudHandshakeDeniedError):
        await serve_authenticated_reads(
            socket,
            receipt,
            lambda _: dispatcher,
            max_reads=max_reads,  # type: ignore[arg-type]
        )
