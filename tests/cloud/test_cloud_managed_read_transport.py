"""Post-authenticated managed reads do not authenticate a device or start a service."""

from __future__ import annotations

import asyncio
import base64
import json
import re
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
        if message.get("kind") == "connector.read_result":
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
    events: list[str] = []
    assert (
        await serve_authenticated_reads(
            socket, receipt, lambda _: dispatcher, max_reads=2, on_activity=events.append
        )
        == receipt
    )
    assert events[0] == "Tool call 1: read started"
    assert re.fullmatch(r"Tool call 1: project_summary completed \(\d+ ms\)", events[1])
    assert events[2] == "Tool call 2: read started"
    assert re.fullmatch(r"Tool call 2: project_summary completed \(\d+ ms\)", events[3])
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


# --- Bounded local-folder browse frames on the same signed socket -------------

FOLDER_REQUEST = "0f4a2c1e-7b60-4d21-9d3a-2f8f6e1c4b55"
BROWSE_PROJECT = "44444444-4444-4444-8444-444444444444"


def folder_frame(operation: str, **extra: object) -> str:
    body: dict[str, object] = {
        "kind": "connector.local_browser_request",
        "version": 1,
        "requestId": FOLDER_REQUEST,
        "operation": operation,
    }
    body.update(extra)
    return json.dumps(body)


class ScriptedSocket:
    """Delivers queued frames verbatim; records every outgoing frame."""

    def __init__(self, incoming: list[str]) -> None:
        self.pending = list(incoming)
        self.sent: list[dict[str, object]] = []

    async def recv(self) -> str:
        if not self.pending:
            raise AssertionError("test socket unexpectedly drained")
        return self.pending.pop(0)

    async def send(self, value: str) -> None:
        self.sent.append(json.loads(value))
        message = self.sent[-1]
        # Cloud signs every read result with an immediate sequence ack.
        if message.get("kind") == "connector.read_result":
            self.pending.append(
                json.dumps(
                    {
                        "kind": "connector.read_ack",
                        "version": 1,
                        "sequence": message["sequence"],
                        "requestId": message["result"]["requestId"],
                    }
                )
            )


class StagedFolderService:
    def __init__(self) -> None:
        self.listed: list[str] = []
        self.bound: list[tuple[str, str]] = []

    def list(self, folder_id: str) -> dict[str, object]:
        self.listed.append(folder_id)
        return {
            "folderId": folder_id,
            "name": "KiCad Projects",
            "parentId": None,
            "project": False,
            "more": False,
            "folders": [{"id": "child", "name": "Board1", "project": True}],
        }

    def bind(self, folder_id: str, project_id: str) -> bool:
        self.bound.append((folder_id, project_id))
        return True

    def choose(self) -> dict[str, object]:
        return {"status": "cancelled"}

    def project_path(self, project_id: str) -> str | None:
        return None


def _signed_socket_dispatch(db_dispatcher: LocalReadDispatch) -> LocalReadDispatch:
    """Dispatcher factory form; the same object proves scope/scope isolation."""
    return db_dispatcher


@pytest.mark.anyio
async def test_folder_frames_are_answered_without_consuming_read_sequences(
    tmp_path: Path,
) -> None:
    (tmp_path / "board.kicad_pro").write_text('{"secret": true}')
    dispatcher = build_dispatcher(tmp_path, [True])
    service = StagedFolderService()
    socket = ScriptedSocket([folder_frame("list", folderId="root"), request(1)])
    receipt = HandshakeReceipt(DEVICE, SESSION)

    def factory(_receipt: HandshakeReceipt) -> LocalReadDispatch:
        return dispatcher

    # Serve one interleaved folder frame, then one read: sequences untouched.
    events: list[str] = []
    served = await serve_authenticated_reads(
        socket, receipt, factory, max_reads=1, folder_service=service, on_activity=events.append
    )
    assert served == receipt
    assert events[0] == "Folder request completed"
    assert events[1] == "Tool call 1: read started"
    assert re.fullmatch(r"Tool call 1: project_summary completed \(\d+ ms\)", events[2])
    kinds = [item["kind"] for item in socket.sent]
    assert kinds == ["connector.local_browser_result", "connector.read_result"]
    folder_result = socket.sent[0]
    assert folder_result == {
        "kind": "connector.local_browser_result",
        "version": 1,
        "requestId": FOLDER_REQUEST,
        "operation": "list",
        "folderId": "root",
        "name": "KiCad Projects",
        "parentId": None,
        "project": False,
        "more": False,
        "folders": [{"id": "child", "name": "Board1", "project": True}],
    }
    read_result = socket.sent[1]
    assert read_result["sequence"] == 1
    assert read_result["result"]["files"]["projectPresent"] is True


@pytest.mark.anyio
async def test_native_folder_choice_cancel_logs_outcome_without_binding_project(
    tmp_path: Path,
) -> None:
    (tmp_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    dispatcher = build_dispatcher(tmp_path, [True])
    service = StagedFolderService()
    socket = ScriptedSocket([folder_frame("choose"), request(1)])
    events: list[str] = []
    receipt = HandshakeReceipt(DEVICE, SESSION)
    result = await serve_authenticated_reads(
        socket,
        receipt,
        lambda _: dispatcher,
        max_reads=1,
        folder_service=service,
        on_activity=events.append,
    )
    assert result == receipt
    assert events[:2] == [
        "Opening Windows project folder dialog",
        "Folder selection cancelled",
    ]
    assert events[2] == "Tool call 1: read started"
    assert service.bound == []
    assert socket.sent[0]["kind"] == "connector.local_browser_result"
    assert socket.sent[0]["status"] == "cancelled"


@pytest.mark.anyio
async def test_folder_service_is_required_before_any_browse_frame_is_answered() -> None:
    socket = ScriptedSocket([folder_frame("list", folderId="root")])
    receipt = HandshakeReceipt(DEVICE, SESSION)
    with pytest.raises(CloudHandshakeDeniedError):
        await serve_authenticated_reads(socket, receipt, _signed_socket_dispatch, max_reads=1)


@pytest.mark.anyio
async def test_managed_native_drc_requires_local_opt_in_and_returns_counts_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "board.kicad_pro").write_text('{"private": "NOT_FOR_CLOUD"}')
    calls: list[OperatorProject] = []
    monkeypatch.setattr(
        "kicad_mcp.cloud_read_dispatch.summarize_native_pcb_drc",
        lambda selected: calls.append(selected) or {"violations": 17, "unconnectedItems": 4},
    )
    dispatcher = LocalReadDispatch(
        verified=VerifiedLocalBinding(
            device_id=DEVICE,
            project_id=PROJECT,
            operations=frozenset({"project_summary", "run_drc"}),
            session_id=SESSION,
            session_expires_unix_ms=int(time.time() * 1000) + 240_000,
        ),
        operator_project=OperatorProject(DEVICE, PROJECT, tmp_path, "board"),
        current_authorization=lambda: True,
        max_reads=2,
        native_drc=True,
    )
    receipt = HandshakeReceipt(DEVICE, SESSION)
    blocked = Socket([request(1, operation="run_drc")])
    with pytest.raises(CloudHandshakeDeniedError):
        await serve_authenticated_reads(blocked, receipt, lambda _: dispatcher, max_reads=1)
    assert blocked.sent == []
    assert calls == []

    allowed = Socket([request(1), request(2, operation="run_drc")])
    assert (
        await serve_authenticated_reads(
            allowed, receipt, lambda _: dispatcher, max_reads=2, allow_native_drc=True
        )
        == receipt
    )
    assert len(calls) == 1
    assert [msg["result"]["operation"] for msg in allowed.sent] == [
        "project_summary",
        "run_drc",
    ]
    assert allowed.sent[1]["result"]["counts"] == {"violations": 17, "unconnectedItems": 4}
    assert "NOT_FOR_CLOUD" not in json.dumps(allowed.sent)
    assert str(tmp_path) not in json.dumps(allowed.sent)


@pytest.mark.anyio
async def test_native_transport_refuses_false_dispatcher_claim(tmp_path: Path) -> None:
    dispatcher = build_dispatcher(tmp_path, [True])
    socket = Socket([request(1, operation="run_drc")])
    with pytest.raises(CloudHandshakeDeniedError):
        await serve_authenticated_reads(
            socket,
            HandshakeReceipt(DEVICE, SESSION),
            lambda _: dispatcher,
            max_reads=1,
            allow_native_drc=True,
        )
    assert socket.sent == []


# --- Multiple owner-bound projects on one signed Connector session ------------

OTHER_PROJECT = "44444444-4444-4444-8444-444444444444"


@pytest.mark.anyio
async def test_owner_bound_second_project_is_readable_on_same_device(tmp_path: Path) -> None:
    """A Cloud-added project must not be a registration with an unusable MCP route."""
    primary = tmp_path / "primary"
    secondary = tmp_path / "secondary"
    primary.mkdir()
    secondary.mkdir()
    (primary / "board.kicad_pro").write_text("PRIMARY_PRIVATE")
    (secondary / "other.kicad_pro").write_text("OTHER_PRIVATE")

    allowed = {OTHER_PROJECT: secondary}
    device_grant = [True]

    def resolve(project_id: str) -> OperatorProject | None:
        folder = allowed.get(project_id)
        return OperatorProject(DEVICE, project_id, folder, "other") if folder is not None else None

    dispatcher = LocalReadDispatch(
        verified=VerifiedLocalBinding(
            device_id=DEVICE,
            project_id=PROJECT,
            operations=frozenset({"project_summary"}),
            session_id=SESSION,
            session_expires_unix_ms=int(time.time() * 1000) + 240_000,
        ),
        operator_project=OperatorProject(DEVICE, PROJECT, primary, "board"),
        current_authorization=lambda: device_grant[0],
        project_resolver=resolve,
        max_reads=3,
    )
    socket = Socket(
        [
            request(1),
            request(2, projectId=OTHER_PROJECT),
            request(3),
        ]
    )
    receipt = HandshakeReceipt(DEVICE, SESSION)
    assert (
        await serve_authenticated_reads(socket, receipt, lambda _: dispatcher, max_reads=3)
        == receipt
    )
    assert [msg["result"]["projectId"] for msg in socket.sent] == [PROJECT, OTHER_PROJECT, PROJECT]
    for msg in socket.sent:
        assert msg["result"]["files"]["projectPresent"] is True
        assert "PRIVATE" not in json.dumps(msg)
        assert str(tmp_path) not in json.dumps(msg)


@pytest.mark.anyio
async def test_removed_or_unbound_second_project_never_delivers_a_read(tmp_path: Path) -> None:
    folder = tmp_path / "other"
    folder.mkdir()
    (folder / "other.kicad_pro").write_text("{}")
    allowed = {OTHER_PROJECT: folder}
    primary = build_dispatcher(tmp_path, [True])
    mapped = LocalReadDispatch(
        verified=primary._verified,
        operator_project=primary._project,
        current_authorization=lambda: True,
        project_resolver=lambda pid: (
            OperatorProject(DEVICE, pid, allowed[pid], "other") if pid in allowed else None
        ),
        max_reads=2,
    )
    raw = json.loads(request(1, projectId=OTHER_PROJECT))["request"]
    frame = json.dumps(raw).encode()
    result = mapped.read(frame, sequence=1)
    assert result["projectId"] == OTHER_PROJECT
    del allowed[OTHER_PROJECT]
    with pytest.raises(LocalReadDeniedError):
        mapped.assert_delivery_authorized(frame, device_id=DEVICE, session_id=SESSION)

    rejected = Socket([request(1, projectId=OTHER_PROJECT)])
    with pytest.raises(LocalReadDeniedError):
        await serve_authenticated_reads(
            rejected,
            HandshakeReceipt(DEVICE, SESSION),
            lambda _: LocalReadDispatch(
                verified=primary._verified,
                operator_project=primary._project,
                current_authorization=lambda: True,
                project_resolver=lambda _id: None,
            ),
            max_reads=1,
        )
    assert rejected.sent == []


@pytest.mark.parametrize("malicious", ["wrong_device", "raiser", "wrong_project"])
def test_project_resolver_cannot_switch_device_or_leak_local_failure(
    tmp_path: Path, malicious: str
) -> None:
    def resolve(project_id: str) -> OperatorProject:
        if malicious == "raiser":
            raise RuntimeError("secret absolute path from invalid mapping")
        return OperatorProject(
            "99999999-9999-4999-8999-999999999999" if malicious == "wrong_device" else DEVICE,
            PROJECT if malicious == "wrong_project" else project_id,
            tmp_path,
            "board",
        )

    dispatcher = LocalReadDispatch(
        verified=VerifiedLocalBinding(
            device_id=DEVICE,
            project_id=PROJECT,
            operations=frozenset({"project_summary"}),
            session_id=SESSION,
            session_expires_unix_ms=int(time.time() * 1000) + 240_000,
        ),
        operator_project=OperatorProject(DEVICE, PROJECT, tmp_path, "board"),
        current_authorization=lambda: True,
        project_resolver=resolve,
    )
    message = json.loads(request(1, projectId=OTHER_PROJECT))["request"]
    encoded = json.dumps(message).encode()
    with pytest.raises(LocalReadDeniedError, match="request denied"):
        dispatcher.read(encoded, sequence=1)


@pytest.mark.anyio
async def test_activity_logger_exception_never_invalidates_a_signed_read(tmp_path: Path) -> None:
    dispatcher = build_dispatcher(tmp_path, [True])
    socket = Socket([request(1)])

    def broken_terminal(_message: str) -> None:
        raise OSError("terminal output unavailable")

    receipt = HandshakeReceipt(DEVICE, SESSION)
    assert (
        await serve_authenticated_reads(
            socket, receipt, lambda _: dispatcher, max_reads=1, on_activity=broken_terminal
        )
        == receipt
    )
    assert len(socket.sent) == 1
    assert socket.sent[0]["result"]["operation"] == "project_summary"


@pytest.mark.anyio
async def test_untrusted_activity_callback_type_is_refused(tmp_path: Path) -> None:
    socket = Socket([request(1)])
    receipt = HandshakeReceipt(DEVICE, SESSION)
    with pytest.raises(CloudHandshakeDeniedError):
        await serve_authenticated_reads(
            socket,
            receipt,
            lambda _: build_dispatcher(tmp_path, [True]),
            max_reads=1,
            on_activity="unsafe",  # type: ignore[arg-type]
        )
    assert socket.sent == []


@pytest.mark.anyio
async def test_managed_write_revisions_returns_prepared_shas(tmp_path: Path) -> None:
    req = json.dumps(
        {
            "kind": "connector.prepare_write_revisions",
            "version": 1,
            "requestId": "55555555-5555-4555-8555-555555555555",
            "deviceId": DEVICE,
            "projectId": PROJECT,
        }
    )
    socket = Socket([req, request(1)])
    receipt = HandshakeReceipt(DEVICE, SESSION)
    revisions = {
        "expectedBoardSha256": "a" * 64,
        "expectedLiveBoardSha256": "b" * 64,
    }
    await serve_authenticated_reads(
        socket,
        receipt,
        lambda _: build_dispatcher(tmp_path, [True]),
        max_reads=1,
        allow_native_write=True,
        revisions_preparer=lambda project_id: revisions if project_id == PROJECT else {},
        write_executor=lambda project_id, proof, persist: {"requestId": "x"},
    )
    assert len(socket.sent) == 2
    assert socket.sent[0] == {
        "kind": "connector.write_revisions_result",
        "version": 1,
        "requestId": "55555555-5555-4555-8555-555555555555",
        "expectedBoardSha256": "a" * 64,
        "expectedLiveBoardSha256": "b" * 64,
    }


@pytest.mark.anyio
async def test_managed_authorized_write_executes_and_receives_ack(tmp_path: Path) -> None:
    # Real v2 wire proposals carry both disk and live KiCad revision digests.
    # A tiny dummy proof previously masked the 1 KiB transport size failure.
    payload = {
        "kind": "connector.write_request",
        "version": 2,
        "requestId": "77777777-7777-4777-8777-777777777777",
        "deviceId": DEVICE,
        "projectId": PROJECT,
        "sessionId": SESSION,
        "deadlineUnixMs": int(time.time() * 1000) + 8000,
        "command": {
            "operation": "pcb_move_footprint",
            "reference": "R1",
            "xMm": 32,
            "yMm": 29,
            "rotationDeg": None,
            "expectedBoardSha256": "a" * 64,
            "expectedLiveBoardSha256": "b" * 64,
        },
    }
    proof_obj = {
        "kind": "connector.signed_write_proposal",
        "version": 2,
        "payload": base64.urlsafe_b64encode(
            json.dumps(payload, separators=(",", ":")).encode("utf-8")
        )
        .decode("ascii")
        .rstrip("="),
        "signature": "A" * 86,
    }
    write_frame = json.dumps(
        {
            "kind": "connector.authorized_write",
            "version": 1,
            "sequence": 1,
            "projectId": PROJECT,
            "proof": proof_obj,
            "persistToDisk": True,
        }
    )
    assert 1024 < len(write_frame.encode("utf-8")) <= 3072
    ack_frame = json.dumps(
        {
            "kind": "connector.write_ack",
            "version": 1,
            "sequence": 1,
            "requestId": "77777777-7777-4777-8777-777777777777",
        }
    )

    class CustomSocket:
        def __init__(self) -> None:
            self.incoming: asyncio.Queue[str] = asyncio.Queue()
            self.incoming.put_nowait(write_frame)
            self.sent: list[dict[str, object]] = []

        async def recv(self) -> str:
            return await self.incoming.get()

        async def send(self, val: str) -> None:
            msg = json.loads(val)
            self.sent.append(msg)
            if msg.get("kind") == "connector.write_result":
                self.incoming.put_nowait(ack_frame)

    socket = CustomSocket()
    receipt = HandshakeReceipt(DEVICE, SESSION)
    calls: list[tuple[str, bytes, bool]] = []
    activity: list[str] = []

    def execute(project_id: str, proof: bytes, persist: bool) -> dict[str, object]:
        calls.append((project_id, proof, persist))
        return {
            "requestId": "77777777-7777-4777-8777-777777777777",
            "projectId": PROJECT,
            "operation": "pcb_move_footprint",
            "nativeCommitted": True,
            "savedToDisk": True,
            "diskBoardSha256": "c" * 64,
        }

    await serve_authenticated_reads(
        socket,  # type: ignore[arg-type]
        receipt,
        lambda _: build_dispatcher(tmp_path, [True]),
        max_reads=1,
        allow_native_write=True,
        revisions_preparer=lambda project_id: {"expectedBoardSha256": "a" * 64},
        write_executor=execute,
        on_activity=activity.append,
    )
    assert activity[:4] == [
        "Tool call 1: write started",
        "Cloud WRITE envelope validated",
        "Cloud WRITE local executor returned",
        "Cloud WRITE response acknowledged",
    ]
    assert re.fullmatch(r"Tool call 1: pcb_move_footprint completed \(\d+ ms\)", activity[4])
    assert len(calls) == 1
    assert calls[0][0] == PROJECT
    assert calls[0][2] is True
    assert json.loads(calls[0][1]) == proof_obj
    assert len(socket.sent) == 1
    assert socket.sent[0]["kind"] == "connector.write_result"
    assert socket.sent[0]["result"]["operation"] == "pcb_move_footprint"
    assert socket.sent[0]["result"]["savedToDisk"] is True


def test_signed_write_wire_cap_keeps_legacy_read_limits() -> None:
    from kicad_mcp.cloud_outbound_handshake import _read_strict_json

    # Only the signed owner WRITE envelope may exceed 1 KiB; ordinary reads
    # and handshake frames retain their original strict byte bound.
    for kind, padding in (
        ("connector.authorized_read", 1024),
        ("connector.authorized_write", 3072),
    ):
        oversized = json.dumps({"kind": kind, "padding": "x" * padding})
        with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
            _read_strict_json(oversized, kind)


@pytest.mark.anyio
async def test_managed_write_stage_activity_is_redacted(tmp_path: Path) -> None:
    """A real owner terminal needs stage evidence without proof or PCB content."""
    write_frame = json.dumps(
        {
            "kind": "connector.authorized_write",
            "version": 1,
            "sequence": 1,
            "projectId": PROJECT,
            "proof": {
                "kind": "connector.signed_write_proposal",
                "version": 2,
                "payload": "c2VjcmV0LWJvYXJk",
                "signature": "c2ln",
            },
            "persistToDisk": True,
        }
    )
    events: list[str] = []

    def reject(_: str, __: bytes, ___: bool) -> dict[str, object]:
        raise ValueError("sensitive-private-project-path")

    socket = Socket([write_frame])
    with pytest.raises(ValueError, match="sensitive-private-project-path"):
        await serve_authenticated_reads(
            socket,
            HandshakeReceipt(DEVICE, SESSION),
            lambda _: build_dispatcher(tmp_path, [True]),
            max_reads=1,
            allow_native_write=True,
            revisions_preparer=lambda _: {"expectedBoardSha256": "a" * 64},
            write_executor=reject,
            on_activity=events.append,
        )
    assert events == [
        "Tool call 1: write started",
        "Cloud WRITE envelope validated",
        "Cloud WRITE local executor rejected",
        "Tool call 1: write failed",
    ]
    assert "sensitive-private" not in " ".join(events)
    assert socket.sent == []


@pytest.mark.anyio
async def test_managed_write_denied_when_allow_native_write_is_false(tmp_path: Path) -> None:
    write_frame = json.dumps(
        {
            "kind": "connector.authorized_write",
            "version": 1,
            "sequence": 1,
            "proof": {},
        }
    )
    socket = Socket([write_frame])
    receipt = HandshakeReceipt(DEVICE, SESSION)
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        await serve_authenticated_reads(
            socket,
            receipt,
            lambda _: build_dispatcher(tmp_path, [True]),
            max_reads=1,
            allow_native_write=False,
        )


@pytest.mark.anyio
async def test_managed_prepare_revisions_denied_when_not_allowed_or_no_preparer(
    tmp_path: Path,
) -> None:
    frame = json.dumps(
        {
            "kind": "connector.prepare_write_revisions",
            "version": 1,
            "requestId": "req1",
            "deviceId": DEVICE,
            "projectId": PROJECT,
        }
    )
    socket = Socket([frame])
    receipt = HandshakeReceipt(DEVICE, SESSION)
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        await serve_authenticated_reads(
            socket,
            receipt,
            lambda _: build_dispatcher(tmp_path, [True]),
            max_reads=1,
            allow_native_write=False,
            revisions_preparer=None,
        )


@pytest.mark.anyio
async def test_managed_prepare_revisions_denied_on_malformed_request(
    tmp_path: Path,
) -> None:
    frame = json.dumps(
        {
            "kind": "connector.prepare_write_revisions",
            "version": 2,
            "requestId": "req1",
        }
    )
    socket = Socket([frame])
    receipt = HandshakeReceipt(DEVICE, SESSION)
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        await serve_authenticated_reads(
            socket,
            receipt,
            lambda _: build_dispatcher(tmp_path, [True]),
            max_reads=1,
            allow_native_write=True,
            revisions_preparer=lambda: {},
        )


@pytest.mark.anyio
async def test_managed_write_denied_on_malformed_envelope_or_non_dict_proof(
    tmp_path: Path,
) -> None:
    frame = json.dumps(
        {
            "kind": "connector.authorized_write",
            "version": 1,
            "sequence": 1,
            "proof": "not-a-dict",
        }
    )
    socket = Socket([frame])
    receipt = HandshakeReceipt(DEVICE, SESSION)
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        await serve_authenticated_reads(
            socket,
            receipt,
            lambda _: build_dispatcher(tmp_path, [True]),
            max_reads=1,
            allow_native_write=True,
            write_executor=lambda *_: {},
        )


@pytest.mark.anyio
async def test_managed_write_denied_on_non_str_ack_or_mismatched_ack(
    tmp_path: Path,
) -> None:
    proof_obj = {
        "kind": "connector.signed_write_proposal",
        "version": 2,
        "payload": "dGVzdA",
        "signature": "c2ln",
    }
    write_frame = json.dumps(
        {
            "kind": "connector.authorized_write",
            "version": 1,
            "sequence": 1,
            "projectId": PROJECT,
            "proof": proof_obj,
            "persistToDisk": True,
        }
    )

    class NonStrAckSocket:
        def __init__(self) -> None:
            self.incoming: asyncio.Queue[object] = asyncio.Queue()
            self.incoming.put_nowait(write_frame)

        async def recv(self) -> object:
            return await self.incoming.get()

        async def send(self, val: str) -> None:
            msg = json.loads(val)
            if msg.get("kind") == "connector.write_result":
                self.incoming.put_nowait(12345)  # non-str triggers line 210

    socket1 = NonStrAckSocket()
    receipt = HandshakeReceipt(DEVICE, SESSION)

    def dispatch_factory(_: HandshakeReceipt) -> LocalReadDispatch:
        return build_dispatcher(tmp_path, [True])

    def revs_prep() -> dict[str, str]:
        return {"revisions": {}}

    def executor(*_: object) -> dict[str, object]:
        return {"requestId": "req1"}

    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        await serve_authenticated_reads(
            socket1,  # type: ignore[arg-type]
            receipt,
            dispatch_factory,
            max_reads=1,
            allow_native_write=True,
            revisions_preparer=revs_prep,
            write_executor=executor,
        )

    class MismatchedAckSocket:
        def __init__(self) -> None:
            self.incoming: asyncio.Queue[object] = asyncio.Queue()
            self.incoming.put_nowait(write_frame)

        async def recv(self) -> object:
            return await self.incoming.get()

        async def send(self, val: str) -> None:
            msg = json.loads(val)
            if msg.get("kind") == "connector.write_result":
                self.incoming.put_nowait(
                    json.dumps(
                        {
                            "kind": "connector.write_ack",
                            "version": 1,
                            "sequence": 999,  # mismatched sequence triggers line 204
                            "requestId": "different-req",
                        }
                    )
                )

    socket2 = MismatchedAckSocket()
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        await serve_authenticated_reads(
            socket2,  # type: ignore[arg-type]
            receipt,
            dispatch_factory,
            max_reads=1,
            allow_native_write=True,
            revisions_preparer=revs_prep,
            write_executor=executor,
        )


@pytest.mark.anyio
async def test_signed_read_frames_denials_on_valid_session(tmp_path: Path) -> None:
    receipt = HandshakeReceipt(DEVICE, SESSION)

    def dispatch_factory(_: HandshakeReceipt) -> LocalReadDispatch:
        return build_dispatcher(tmp_path, [True])

    # 1. Folder frame without folder_service attached
    socket_no_folder = ScriptedSocket([folder_frame("list", folderId="root")])
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        await serve_authenticated_reads(
            socket_no_folder,
            receipt,
            dispatch_factory,
            max_reads=1,
            folder_service=None,
        )

    # 2. Unknown kind frame
    unknown_frame = json.dumps({"kind": "connector.unknown_action", "version": 1})
    socket_unknown = ScriptedSocket([unknown_frame])
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        await serve_authenticated_reads(
            socket_unknown,
            receipt,
            dispatch_factory,
            max_reads=1,
        )

    # 3. Non-string raw frame
    class BinaryFrameSocket:
        async def recv(self) -> object:
            return b"\x00\x01\x02"

        async def send(self, val: str) -> None:
            pass

    binary_socket = BinaryFrameSocket()
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        await serve_authenticated_reads(
            binary_socket,  # type: ignore[arg-type]
            receipt,
            dispatch_factory,
            max_reads=1,
        )


@pytest.mark.anyio
async def test_signed_session_rotates_at_idle_without_false_disconnect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_managed_read_transport as transport

    monkeypatch.setattr(transport, "_SESSION_REFRESH_SECONDS", 0.02)
    socket = Socket([])
    receipt = HandshakeReceipt(DEVICE, SESSION)
    activity: list[str] = []
    assert (
        await serve_authenticated_reads(
            socket,
            receipt,
            lambda _: build_dispatcher(tmp_path, [True]),
            max_reads=2,
            on_activity=activity.append,
        )
        == receipt
    )
    assert activity == ["Refreshing signed Cloud session"]
    assert socket.sent == []


@pytest.mark.anyio
async def test_signed_session_does_not_cut_off_started_read_at_refresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_managed_read_transport as transport
    from kicad_mcp import cloud_read_dispatch

    (tmp_path / "board.kicad_pro").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(transport, "_SESSION_REFRESH_SECONDS", 0.02)
    original = cloud_read_dispatch.inspect_readonly

    def slow_inspect(*args: object, **kwargs: object) -> object:
        time.sleep(0.06)
        return original(*args, **kwargs)

    monkeypatch.setattr(cloud_read_dispatch, "inspect_readonly", slow_inspect)
    socket = Socket([request(1)])
    activity: list[str] = []
    receipt = HandshakeReceipt(DEVICE, SESSION)
    assert (
        await serve_authenticated_reads(
            socket,
            receipt,
            lambda _: build_dispatcher(tmp_path, [True]),
            max_reads=1,
            on_activity=activity.append,
        )
        == receipt
    )
    assert socket.sent[0]["kind"] == "connector.read_result"
    assert activity[0] == "Tool call 1: read started"
    assert activity[1].startswith("Tool call 1: project_summary completed")
    assert "Refreshing signed Cloud session" not in activity


@pytest.mark.anyio
async def test_signed_session_deadline_already_elapsed_rotates_without_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp import cloud_managed_read_transport as transport

    monkeypatch.setattr(transport, "_SESSION_REFRESH_SECONDS", 0.0)
    socket = Socket([])
    receipt = HandshakeReceipt(DEVICE, SESSION)
    events: list[str] = []
    assert (
        await serve_authenticated_reads(
            socket,
            receipt,
            lambda _: build_dispatcher(tmp_path, [True]),
            max_reads=1,
            on_activity=events.append,
        )
        == receipt
    )
    assert events == ["Refreshing signed Cloud session"]
    assert socket.sent == []


@pytest.mark.anyio
@pytest.mark.parametrize("project_id", [None, "not-a-project", "A" * 36, "0" * 36])
async def test_signed_write_rejects_unbound_project_id_before_native_callback(
    tmp_path: Path, project_id: str | None
) -> None:
    """Cloud's outer project selector must never select or change an unapproved PCB."""
    calls: list[str] = []
    proof = {
        "kind": "connector.signed_write_proposal",
        "version": 2,
        "payload": "dGVzdA",
        "signature": "c2ln",
    }
    frame = {
        "kind": "connector.authorized_write",
        "version": 1,
        "sequence": 1,
        "proof": proof,
        "persistToDisk": True,
    }
    if project_id is not None:
        frame["projectId"] = project_id

    def execute(_: str, _proof: bytes, _persist: bool) -> dict[str, object]:
        calls.append("native_mutation")
        return {"requestId": "unexpected"}

    socket = Socket([json.dumps(frame)])
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        await serve_authenticated_reads(
            socket,
            HandshakeReceipt(DEVICE, SESSION),
            lambda _: build_dispatcher(tmp_path, [True]),
            max_reads=1,
            allow_native_write=True,
            revisions_preparer=lambda _: {"expectedBoardSha256": "a" * 64},
            write_executor=execute,
        )
    assert calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("project_id", [None, "not-a-project", "A" * 36])
async def test_signed_revision_probe_rejects_unbound_project_id_before_native_access(
    tmp_path: Path, project_id: str | None
) -> None:
    calls: list[str] = []
    frame: dict[str, object] = {
        "kind": "connector.prepare_write_revisions",
        "version": 1,
        "requestId": "55555555-5555-4555-8555-555555555555",
        "deviceId": DEVICE,
    }
    if project_id is not None:
        frame["projectId"] = project_id

    def prepare(_: str) -> dict[str, str]:
        calls.append("read_board")
        return {"expectedBoardSha256": "a" * 64}

    socket = Socket([json.dumps(frame)])
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        await serve_authenticated_reads(
            socket,
            HandshakeReceipt(DEVICE, SESSION),
            lambda _: build_dispatcher(tmp_path, [True]),
            max_reads=1,
            allow_native_write=True,
            revisions_preparer=prepare,
            write_executor=lambda _id, _proof, _persist: {},
        )
    assert calls == []


@pytest.mark.anyio
@pytest.mark.parametrize("persist_flag", ["false", "true", 0, 1, None, {}])
async def test_signed_write_rejects_non_boolean_persist_flag_before_native_callback(
    tmp_path: Path, persist_flag: object
) -> None:
    """Malformed persist flags may not silently turn an unsaved edit into a disk write."""
    calls: list[str] = []
    frame = {
        "kind": "connector.authorized_write",
        "version": 1,
        "sequence": 1,
        "projectId": PROJECT,
        "persistToDisk": persist_flag,
        "proof": {
            "kind": "connector.signed_write_proposal",
            "version": 2,
            "payload": "dGVzdA",
            "signature": "c2ln",
        },
    }

    def execute(_: str, _proof: bytes, _persist: bool) -> dict[str, object]:
        calls.append("native_mutation")
        raise AssertionError("native call must not start")

    socket = Socket([json.dumps(frame)])
    with pytest.raises(CloudHandshakeDeniedError, match="handshake denied"):
        await serve_authenticated_reads(
            socket,
            HandshakeReceipt(DEVICE, SESSION),
            lambda _: build_dispatcher(tmp_path, [True]),
            max_reads=1,
            allow_native_write=True,
            revisions_preparer=lambda _: {"expectedBoardSha256": "a" * 64},
            write_executor=execute,
        )
    assert calls == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "ok", "is_error"),
    [
        ("call", True, True),
        ("call", True, False),
        ("call", False, False),
        ("catalog", False, False),
        ("catalog", True, False),
    ],
)
async def test_mcp_tool_error_is_not_logged_as_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str, ok: bool, is_error: bool
) -> None:
    # Delivery/acknowledgment success is not the same as a successful MCP tool.
    from types import SimpleNamespace

    from kicad_mcp import cloud_managed_read_transport as transport

    async def signed_mcp_reply(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "requestId": "example",
            "method": method,
            "ok": ok,
            "result": {
                "isError": is_error,
                "content": [{"type": "text", "text": "secret-local-project-path"}],
                "structuredContent": {"reason": "local_mcp_read_timeout"},
            },
        }

    monkeypatch.setattr(transport, "_serve_one_mcp_request", signed_mcp_reply)
    activity: list[str] = []
    served = await transport._serve_one_signed_frame(
        Socket([]),
        json.dumps({"kind": "connector.mcp_request"}),
        0,
        build_dispatcher(tmp_path, [True]),
        HandshakeReceipt(DEVICE, SESSION),
        None,
        activity.append,
        mcp_service=SimpleNamespace(dispatch=object()),
    )
    assert served == 1
    assert activity[0] == "Tool call 1: mcp started"
    outcome = "failed" if (is_error or not ok) else "completed"
    assert re.fullmatch(rf"Tool call 1: mcp {outcome} \(\d+ ms\)", activity[1])
    assert "secret-local-project-path" not in " ".join(activity)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("method", "name", "is_error", "expected_label"),
    [
        ("call", "run_drc", False, "mcp run_drc"),
        ("call", "run_erc", True, "mcp run_erc"),
        ("call", "pcb_get_info", False, "mcp pcb_get_info"),
        ("catalog", None, False, "mcp catalog"),
        ("call", "run_drc\\nPRIVATE_DATA", True, "mcp"),
        ("call", "C:/private/project", True, "mcp"),
        ("call", "x" * 150, True, "mcp"),
    ],
)
async def test_mcp_activity_labels_real_tool_without_logging_untrusted_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    name: str | None,
    is_error: bool,
    expected_label: str,
) -> None:
    from types import SimpleNamespace

    from kicad_mcp import cloud_managed_read_transport as transport

    async def signed_reply(*_args: object, **_kwargs: object) -> dict[str, object]:
        return {
            "requestId": "example",
            "method": method,
            "ok": True,
            "result": {"isError": is_error},
        }

    monkeypatch.setattr(transport, "_serve_one_mcp_request", signed_reply)
    nested: dict[str, object] = {
        "kind": "connector.mcp_request",
        "version": 1,
        "requestId": "00000000-0000-4000-8000-000000000001",
        "projectId": PROJECT,
        "method": method,
    }
    if name is not None:
        nested["toolName"] = name
    if method == "call":
        nested["argumentsJson"] = '{"local_path":"SECRET_ARGUMENTS"}'
    frame = {
        "kind": "connector.mcp_request",
        "version": 1,
        "sequence": 1,
        "request": nested,
    }
    activity: list[str] = []
    count = await transport._serve_one_signed_frame(
        Socket([]),
        json.dumps(frame),
        0,
        build_dispatcher(tmp_path, [True]),
        HandshakeReceipt(DEVICE, SESSION),
        None,
        activity.append,
        mcp_service=SimpleNamespace(dispatch=object()),
    )
    assert count == 1
    assert activity[0] == f"Tool call 1: {expected_label} started"
    outcome = "failed" if is_error else "completed"
    assert activity[1].startswith(f"Tool call 1: {expected_label} {outcome} (")
    assert activity[1].endswith(" ms)")
    assert "PRIVATE_DATA" not in " ".join(activity)
    assert "C:/private/project" not in " ".join(activity)
    assert "SECRET_ARGUMENTS" not in " ".join(activity)
