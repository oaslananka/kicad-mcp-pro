"""Adversarial generic Cloud MCP write, replay, project and path tests."""

from __future__ import annotations

import base64
import hashlib
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from mcp.types import Tool

from kicad_mcp.cloud_generic_mcp_bridge import (
    GenericMcpDeniedError,
    _redact_private_paths,
    _safe_arguments,
    is_generic_cloud_tool_safe,
)
from kicad_mcp.cloud_generic_mcp_proof import (
    GenericMcpProofDeniedError,
    verify_generic_mcp_write_proof,
)
from kicad_mcp.cloud_generic_mcp_transport import (
    GenericMcpTransportError,
    GenericProjectMcpService,
    _owner_project_files,
)
from kicad_mcp.cloud_managed_read_transport import _serve_one_mcp_request
from kicad_mcp.cloud_outbound_handshake import HandshakeReceipt
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
REQ = "44444444-4444-4444-8444-444444444444"
OTHER_REQ = "55555555-5555-4555-8555-555555555555"
DOMAIN = b"kicad-cloud-signed-mcp-tool-v1\x00"


def signed_proof(
    key: Ed25519PrivateKey,
    args: str,
    *,
    name: str = "sch_add_symbol",
    request_id: str = REQ,
    deadline: int | None = None,
    changes: dict[str, object] | None = None,
) -> bytes:
    now = time.time_ns() // 1_000_000
    payload: dict[str, object] = {
        "kind": "connector.mcp_tool_write",
        "version": 1,
        "requestId": request_id,
        "deviceId": DEVICE,
        "projectId": PROJECT,
        "sessionId": SESSION,
        "deadlineUnixMs": now + 8_000 if deadline is None else deadline,
        "toolName": name,
        "argumentsSha256": hashlib.sha256(args.encode("utf8")).hexdigest(),
    }
    payload.update(changes or {})
    encoded = json.dumps(payload, separators=(",", ":")).encode()
    sig = key.sign(DOMAIN + encoded)
    return json.dumps(
        {
            "kind": "connector.signed_mcp_tool",
            "version": 1,
            "payload": base64.urlsafe_b64encode(encoded).decode().rstrip("="),
            "signature": base64.urlsafe_b64encode(sig).decode().rstrip("="),
        },
        separators=(",", ":"),
    ).encode()


def frame(
    method: str,
    *,
    name: str = "sch_add_symbol",
    args: str = '{"reference":"R9"}',
    request_id: str = REQ,
    proof: bytes | None = None,
) -> dict[str, object]:
    request: dict[str, object] = {
        "kind": "connector.mcp_request",
        "version": 1,
        "requestId": request_id,
        "projectId": PROJECT,
        "method": method,
    }
    if method == "call":
        request.update({"toolName": name, "argumentsJson": args})
    else:
        request.update({"offset": 0})
    if proof is not None:
        request["proof"] = json.loads(proof)
    return request


def project_fixture(folder) -> OperatorProject:
    (folder / "board.kicad_pro").write_text("{}", encoding="utf8")
    (folder / "board.kicad_pcb").write_text("(kicad_pcb)", encoding="utf8")
    return OperatorProject(
        device_id=DEVICE, project_id=PROJECT, directory=folder, filename_stem="board"
    )


@pytest.mark.asyncio
async def test_signed_owner_write_round_trip_replay_revocation_and_pcb_guard(
    tmp_path, monkeypatch
) -> None:
    project = project_fixture(tmp_path)
    key = Ed25519PrivateKey.generate()
    seen: set[tuple[str, str]] = set()
    invoked: list[tuple[str, dict[str, object]]] = []
    states = {"authorized": True}
    started: list[str] = []

    def consume(session: str, request: str) -> bool:
        pair = (session, request)
        if pair in seen:
            return False
        seen.add(pair)
        return True

    class Worker:
        async def call_tool(self, name, arguments):
            invoked.append((name, arguments))
            return SimpleNamespace(
                isError=False,
                content=[SimpleNamespace(type="text", text="ok")],
                model_dump=lambda **_: {
                    "content": [{"type": "text", "text": "saved"}],
                    "isError": False,
                },
            )

        async def list_tools(self):
            return SimpleNamespace(
                tools=[
                    Tool(
                        name="sch_add_symbol", description="Symbol", inputSchema={"type": "object"}
                    ),
                    Tool(
                        name="pcb_move_footprint",
                        description="Move",
                        inputSchema={"type": "object"},
                    ),
                    Tool(
                        name="kicad_get_version", description="Read", inputSchema={"type": "object"}
                    ),
                ]
            )

    @asynccontextmanager
    async def managed(folder, *, profile, operating_mode):
        assert folder == tmp_path
        assert profile == "expert"
        started.append(operating_mode)
        yield Worker()

    monkeypatch.setattr("kicad_mcp.cloud_generic_mcp_transport.project_stdio_worker", managed)
    service = GenericProjectMcpService(
        receipt=HandshakeReceipt(device_id=DEVICE, session_id=SESSION),
        local_project=lambda id: project if id == PROJECT else None,
        current_authorization=lambda: states["authorized"],
        allow_native_write=True,
        trusted_issuer_key=key.public_key(),
        consume_once=consume,
    )
    args = '{"reference":"R9"}'
    valid = frame("call", args=args, proof=signed_proof(key, args))
    result = await service.dispatch(valid)
    assert result["ok"] is True
    assert result["result"]["content"][0]["text"] == "saved"
    assert invoked[-1] == ("sch_add_symbol", {"reference": "R9"})
    assert started == ["write"]
    assert seen == {(SESSION, REQ)}
    previous = list(invoked)

    with pytest.raises(GenericMcpTransportError):
        await service.dispatch(valid)
    assert invoked == previous

    _prevalidated_186_arg0 = frame(
        "call",
        args='{"reference":"R8"}',
        request_id=OTHER_REQ,
        proof=signed_proof(key, args, request_id=OTHER_REQ),
    )
    with pytest.raises(GenericMcpTransportError):
        await service.dispatch(_prevalidated_186_arg0)
    assert invoked == previous

    states["authorized"] = False
    _prevalidated_198_arg0 = frame("catalog")
    with pytest.raises(GenericMcpTransportError):
        await service.dispatch(_prevalidated_198_arg0)
    assert started == ["write"]
    states["authorized"] = True

    _prevalidated_203_arg0 = frame("call", name="kicad_set_project", args="{}")
    with pytest.raises(GenericMcpTransportError):
        await service.dispatch(_prevalidated_203_arg0)
    _prevalidated_205_arg0 = frame("call", args=args, proof=None)
    with pytest.raises(GenericMcpTransportError):
        await service.dispatch(_prevalidated_205_arg0)
    _prevalidated_207_arg0 = frame(
        "call", name="kicad_get_version", args="{}", proof=signed_proof(key, "{}")
    )
    with pytest.raises(GenericMcpTransportError):
        await service.dispatch(_prevalidated_207_arg0)

    checked: list[str] = []

    def reject_other_gui_board(_project):
        checked.append("checked")
        raise GenericMcpTransportError("wrong_active_board")

    monkeypatch.setattr(
        "kicad_mcp.cloud_generic_mcp_transport._require_owner_live_pcb", reject_other_gui_board
    )
    pcb_args = '{"reference":"R1","x":32,"y":30}'
    _prevalidated_222_arg0 = frame(
        "call",
        name="pcb_move_footprint",
        args=pcb_args,
        request_id=OTHER_REQ,
        proof=signed_proof(key, pcb_args, name="pcb_move_footprint", request_id=OTHER_REQ),
    )
    with pytest.raises(GenericMcpTransportError):
        await service.dispatch(_prevalidated_222_arg0)
    assert checked == ["checked"]
    assert [name for name, _ in invoked if name != "kicad_set_project"] == ["sch_add_symbol"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda f: f.update({"offset": -1}),
        lambda f: f.update({"offset": True}),
        lambda f: f.update({"toolName": "INVALID NAME"}),
        lambda f: f.update({"unknown": 1}),
        lambda f: f.update({"version": True}),
    ],
)
@pytest.mark.asyncio
async def test_invalid_catalog_frame_never_starts_native_worker(tmp_path, mutate) -> None:
    project = project_fixture(tmp_path)
    service = GenericProjectMcpService(
        receipt=HandshakeReceipt(device_id=DEVICE, session_id=SESSION),
        local_project=lambda _: project,
        current_authorization=lambda: True,
    )
    request = frame("catalog")
    mutate(request)
    with pytest.raises(GenericMcpTransportError):
        await service.dispatch(request)


def test_owner_project_requires_unique_matching_design_files(tmp_path) -> None:
    project = project_fixture(tmp_path)
    assert _owner_project_files(project) == {
        "project_dir": str(tmp_path.resolve()),
        "pcb_file": "board.kicad_pcb",
    }
    schematic = tmp_path / "board.kicad_sch"
    schematic.write_text("(kicad_sch)", encoding="utf8")
    assert _owner_project_files(project)["sch_file"] == "board.kicad_sch"
    unrelated = tmp_path / "wrong.kicad_sch"
    unrelated.write_text("(kicad_sch)", encoding="utf8")
    with pytest.raises(GenericMcpTransportError):
        _owner_project_files(project)
    unrelated.unlink()
    extra_pcb = tmp_path / "another.kicad_pcb"
    extra_pcb.write_text("(kicad_pcb)", encoding="utf8")
    with pytest.raises(GenericMcpTransportError):
        _owner_project_files(project)
    extra_pcb.unlink()
    (tmp_path / "board.kicad_pro").rename(tmp_path / "wrong.kicad_pro")
    with pytest.raises(GenericMcpTransportError):
        _owner_project_files(project)


@pytest.mark.parametrize(
    "unsafe",
    [
        {"nested": [{"path": "\\\\server\\share\\board.kicad_pcb"}]},
        {"path": "file:///tmp/disallowed"},
        {"path": "https://ok/../../another"},
        {"path": ["safe", {"to": "/etc/passwd"}]},
        {"path": "C:/Users/other/board.kicad_pcb"},
        {"path": "a\\..\\secret.kicad_sch"},
        {"path": "hello\x00there"},
        {"path": "a" * 16_385},
    ],
)
def test_nested_remote_file_arguments_never_cross_owner_folder(unsafe) -> None:
    assert _safe_arguments(unsafe) is False


def test_strict_safe_names_and_redaction_budgets() -> None:
    for name in (
        "kicad_set_project",
        "project_import_archive",
        "pcb_import_",
        "jobset_signoff",
        "variant_export_manufacturing_package",
    ):
        assert is_generic_cloud_tool_safe(name) is False
    assert _safe_arguments({"tags": ["R1", {"name": "board.kicad_sch"}]}) is True
    assert _safe_arguments({"n": {1: "bad"}}) is False
    assert _safe_arguments({"nested": 1}, depth=13) is False
    with pytest.raises(GenericMcpDeniedError):
        _redact_private_paths("detail", "C:/owner", "C:/owner", depth=17)
    assert _redact_private_paths({"path": ["C:/owner/board.kicad_sch"]}, "C:/owner", "") == {
        "path": ["[local-path]/board.kicad_sch"]
    }


@pytest.mark.parametrize(
    "invalid",
    [
        b'{ "kind":1,"kind":1}',
        b'{"kind":NaN}',
        b"\xff",
        b"[]",
        b'{"kind":"connector.signed_mcp_tool","version":2,"payload":"x","signature":"y"}',
    ],
)
def test_signed_proof_rejects_duplicate_keys_nonfinite_and_wrong_frame(tmp_path, invalid) -> None:
    key = Ed25519PrivateKey.generate()
    project = project_fixture(tmp_path)
    now = time.time_ns() // 1_000_000
    verified = VerifiedLocalBinding(
        device_id=DEVICE,
        project_id=PROJECT,
        session_id=SESSION,
        operations=frozenset({"mcp_bridge"}),
        session_expires_unix_ms=now + 90_000,
    )
    _prevalidated_341_trusted_issuer_key = key.public_key()
    with pytest.raises(GenericMcpProofDeniedError):
        verify_generic_mcp_write_proof(
            invalid,
            arguments_json="{}",
            trusted_issuer_key=_prevalidated_341_trusted_issuer_key,
            verified=verified,
            operator_project=project,
            now_unix_ms=now,
            consume_once=lambda *_: True,
        )


def test_signed_proof_expiry_and_failing_replay_storage_are_denied(tmp_path) -> None:
    project = project_fixture(tmp_path)
    key = Ed25519PrivateKey.generate()
    now = time.time_ns() // 1_000_000
    bound = VerifiedLocalBinding(
        device_id=DEVICE,
        project_id=PROJECT,
        session_id=SESSION,
        operations=frozenset({"mcp_bridge"}),
        session_expires_unix_ms=now + 90_000,
    )
    args = '{"reference":"R9"}'

    def verify(proof, consume):
        return verify_generic_mcp_write_proof(
            proof,
            arguments_json=args,
            trusted_issuer_key=key.public_key(),
            verified=bound,
            operator_project=project,
            now_unix_ms=now,
            consume_once=consume,
        )

    _prevalidated_377_arg0 = signed_proof(key, args, deadline=now - 1)
    with pytest.raises(GenericMcpProofDeniedError):
        verify(_prevalidated_377_arg0, lambda *_: True)
    _prevalidated_379_arg0 = signed_proof(key, args)
    with pytest.raises(GenericMcpProofDeniedError):
        verify(_prevalidated_379_arg0, lambda *_: False)

    def crashed(*_: object) -> bool:
        raise OSError("replay ledger unavailable")

    _prevalidated_385_arg0 = signed_proof(key, args)
    with pytest.raises(GenericMcpProofDeniedError):
        verify(_prevalidated_385_arg0, crashed)
    _prevalidated_387_arg0 = signed_proof(key, args, changes={"extra": 42})
    with pytest.raises(GenericMcpProofDeniedError):
        verify(_prevalidated_387_arg0, lambda *_: True)


@pytest.mark.asyncio
async def test_local_bridge_validates_catalog_presence_json_limits_and_result_bounds(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Untrusted results and arguments must not turn native tool calls into unbounded IO."""
    from kicad_mcp.cloud_generic_mcp_bridge import GenericProjectMcpBridge
    from kicad_mcp.operating_modes import OperatingMode

    project = project_fixture(tmp_path)
    verified = VerifiedLocalBinding(
        device_id=DEVICE,
        project_id=PROJECT,
        session_id=SESSION,
        operations=frozenset({"mcp_bridge"}),
        session_expires_unix_ms=4_000_000_000_000,
    )
    _prevalidated_408_verified = VerifiedLocalBinding(
        device_id=DEVICE,
        project_id=PROJECT,
        session_id=SESSION,
        operations=frozenset({"project_summary"}),
        session_expires_unix_ms=4000000000000,
    )
    with pytest.raises(GenericMcpDeniedError):
        GenericProjectMcpBridge(
            verified=_prevalidated_408_verified,
            operator_project=project,
            current_authorization=lambda: True,
        )
    bridge = GenericProjectMcpBridge(
        verified=verified,
        operator_project=project,
        current_authorization=lambda: True,
        allow_native_write=True,
        now_ms=lambda: 3_000_000_000_000,
    )

    class Session:
        def __init__(self, *, include_write=True, result: object = None) -> None:
            self.include_write = include_write
            self.result = result if result is not None else {"isError": False, "content": []}
            self.invoked: list[str] = []

        async def list_tools(self):
            names = ["kicad_get_version"]
            if self.include_write:
                names.append("sch_add_symbol")
            return SimpleNamespace(
                tools=[
                    Tool(name=name, description="Local", inputSchema={"type": "object"})
                    for name in names
                ]
            )

        async def call_tool(self, name, arguments):
            self.invoked.append(name)
            return SimpleNamespace(model_dump=lambda **_: self.result)

    session = Session()
    monkeypatch.setattr(
        "kicad_mcp.cloud_generic_mcp_bridge.tool_required_mode",
        lambda _: OperatingMode.MANUFACTURING,
    )
    with pytest.raises(GenericMcpDeniedError):
        bridge._access_mode("kicad_get_version")
    monkeypatch.undo()

    async def invoke(session: Session, *, name="kicad_get_version", arguments=None):
        return await bridge.call_tool(
            session,
            project_id=PROJECT,
            session_id=SESSION,
            name=name,
            arguments={} if arguments is None else arguments,
            write_approved=True,
            not_after_unix_ms=4_000_000_000_000,
        )

    _prevalidated_469_arguments = {"n": float("nan")}
    with pytest.raises(GenericMcpDeniedError):
        await invoke(session, arguments=_prevalidated_469_arguments)
    with pytest.raises(GenericMcpDeniedError):
        await invoke(session, arguments={"big": ["x" * 15_000] * 3})
    _prevalidated_473_arg0 = Session(include_write=False)
    with pytest.raises(GenericMcpDeniedError):
        await invoke(_prevalidated_473_arg0, name="sch_add_symbol", arguments={})
    _prevalidated_475_arg0 = Session(result=["not-an-MCP-object"])
    with pytest.raises(GenericMcpDeniedError):
        await invoke(_prevalidated_475_arg0)
    _prevalidated_477_arg0 = Session(result={"content": [{"type": "text", "text": "x" * 525000}]})
    with pytest.raises(GenericMcpDeniedError, match="result_too_large"):
        await invoke(_prevalidated_477_arg0)
    assert session.invoked == []


@pytest.mark.asyncio
async def test_cloud_long_read_mcp_sdk_timeout_does_not_expand_signed_writes(tmp_path) -> None:
    """Native DRC/ERC may exceed the MCP SDK default despite the 75s Cloud budget."""
    from kicad_mcp.cloud_generic_mcp_bridge import GenericProjectMcpBridge

    project = project_fixture(tmp_path)
    bridge = GenericProjectMcpBridge(
        verified=VerifiedLocalBinding(
            device_id=DEVICE,
            project_id=PROJECT,
            session_id=SESSION,
            operations=frozenset({"mcp_bridge"}),
            session_expires_unix_ms=4_000_000_000_000,
        ),
        operator_project=project,
        current_authorization=lambda: True,
        allow_native_write=True,
        now_ms=lambda: 3_000_000_000_000,
    )

    class Session:
        def __init__(self) -> None:
            self.invocations: list[tuple[str, dict[str, object]]] = []

        async def list_tools(self):
            return SimpleNamespace(
                tools=[
                    Tool(name=name, description="local", inputSchema={"type": "object"})
                    for name in ("run_drc", "run_erc", "kicad_get_version", "sch_add_symbol")
                ]
            )

        async def call_tool(self, name, arguments, **kwargs: object):
            self.invocations.append((name, kwargs))
            return SimpleNamespace(
                model_dump=lambda **_: {"content": [{"type": "text", "text": "ok"}]}
            )

    session = Session()
    for name in ("run_drc", "run_erc", "kicad_get_version", "sch_add_symbol"):
        await bridge.call_tool(
            session,
            project_id=PROJECT,
            session_id=SESSION,
            name=name,
            arguments={},
            write_approved=True,
            not_after_unix_ms=4_000_000_000_000,
        )

    assert session.invocations == [
        ("run_drc", {"read_timeout_seconds": 70.0}),
        ("run_erc", {"read_timeout_seconds": 70.0}),
        ("kicad_get_version", {}),
        ("sch_add_symbol", {}),
    ]

    with pytest.raises(GenericMcpDeniedError):
        await bridge.call_tool(
            session,
            project_id=PROJECT,
            session_id=SESSION,
            name="sch_add_symbol",
            arguments={},
            write_approved=False,
            not_after_unix_ms=4_000_000_000_000,
        )
    assert len(session.invocations) == 4


@pytest.mark.parametrize(
    "scenario",
    [
        "unknown_tool",
        "bad_json",
        "missing_proof_consumer",
        "failed_activation",
        "activation_error_text",
        "revoked_at_open",
        "revoked_after_activation",
        "revoked_after_tool",
        "oversized_reply",
    ],
)
@pytest.mark.asyncio
async def test_owner_transport_denies_invalid_native_session_transitions(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    """Native worker startup, activation and response are independent authorization gates."""
    project = project_fixture(tmp_path)
    key = Ed25519PrivateKey.generate()
    state = {"allowed": True}

    class Worker:
        async def call_tool(self, name, arguments):
            if name == "kicad_set_project":
                if scenario == "revoked_after_activation":
                    state["allowed"] = False
                if scenario == "failed_activation":
                    return SimpleNamespace(isError=True, content=[])
                if scenario == "activation_error_text":
                    return SimpleNamespace(
                        isError=False,
                        content=[SimpleNamespace(type="text", text="E_PROJECT_NOT_FOUND")],
                    )
            elif scenario == "revoked_after_tool":
                state["allowed"] = False
            body = "x" * 70_000 if scenario == "oversized_reply" else "ok"
            return SimpleNamespace(
                isError=False,
                content=[SimpleNamespace(type="text", text=body)],
                model_dump=lambda **_: {
                    "isError": False,
                    "content": [{"type": "text", "text": body}],
                },
            )

        async def list_tools(self):
            return SimpleNamespace(
                tools=[Tool(name="kicad_get_version", inputSchema={"type": "object"})]
            )

    @asynccontextmanager
    async def worker(folder, *, profile, operating_mode):
        assert folder == tmp_path
        assert profile == "expert"
        if scenario == "revoked_at_open":
            state["allowed"] = False
        yield Worker()

    monkeypatch.setattr("kicad_mcp.cloud_generic_mcp_transport.project_stdio_worker", worker)
    service = GenericProjectMcpService(
        receipt=HandshakeReceipt(device_id=DEVICE, session_id=SESSION),
        local_project=lambda _: project,
        current_authorization=lambda: state["allowed"],
    )
    if scenario == "unknown_tool":
        request = frame("call", name="arbitrary_unsafe_command", args="{}")
    elif scenario == "bad_json":
        request = frame("call", name="kicad_get_version", args="{")
    elif scenario == "missing_proof_consumer":
        _prevalidated_555_receipt = HandshakeReceipt(device_id=DEVICE, session_id=SESSION)
        _prevalidated_555_trusted_issuer_key = key.public_key()
        with pytest.raises(GenericMcpTransportError):
            GenericProjectMcpService(
                receipt=_prevalidated_555_receipt,
                local_project=lambda _: project,
                current_authorization=lambda: True,
                allow_native_write=True,
                trusted_issuer_key=_prevalidated_555_trusted_issuer_key,
                consume_once=None,
            )
        return
    else:
        request = frame("call", name="kicad_get_version", args="{}")
    if scenario == "oversized_reply":
        # Oversized tool data fails as an explicit, bounded tool error.
        # The signed socket must remain usable for a subsequent request.
        result = await service.dispatch(request)
        assert result["ok"] is True
        assert result["result"]["isError"] is True
        assert "mcp_bridge_result_too_large" in result["result"]["content"][0]["text"]
        assert "x" * 100 not in result["result"]["content"][0]["text"]
        return
    with pytest.raises(GenericMcpTransportError):
        await service.dispatch(request)


@pytest.mark.asyncio
async def test_generic_catalog_exact_name_lookup_respects_registered_local_metadata(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = project_fixture(tmp_path)

    class Worker:
        async def call_tool(self, name, arguments):
            assert name == "kicad_set_project"
            return SimpleNamespace(isError=False, content=[])

        async def list_tools(self):
            return SimpleNamespace(
                tools=[
                    Tool(
                        name="kicad_get_version",
                        description="version",
                        inputSchema={"type": "object"},
                    )
                ]
            )

    @asynccontextmanager
    async def worker(folder, *, profile, operating_mode):
        assert folder == tmp_path
        assert profile == "expert"
        assert operating_mode == "readonly"
        yield Worker()

    monkeypatch.setattr("kicad_mcp.cloud_generic_mcp_transport.project_stdio_worker", worker)
    service = GenericProjectMcpService(
        receipt=HandshakeReceipt(device_id=DEVICE, session_id=SESSION),
        local_project=lambda _: project,
        current_authorization=lambda: True,
    )
    requested = frame("catalog")
    requested["toolName"] = "kicad_get_version"
    result = await service.dispatch(requested)
    assert [item["name"] for item in result["tools"]] == ["kicad_get_version"]
    requested["toolName"] = "sch_add_symbol"
    assert (await service.dispatch(requested))["tools"] == []


@pytest.mark.parametrize("name", ["run_drc", "run_erc", "kicad_get_server_info"])
@pytest.mark.asyncio
async def test_stalled_read_returns_bounded_error_and_preserves_signed_session(
    tmp_path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """A stalled first read must not consume the device pairing or block later reads."""
    import asyncio

    import kicad_mcp.cloud_generic_mcp_transport as transport

    project = project_fixture(tmp_path)
    status = {"calls": 0, "cancelled": 0, "closed": 0, "granted": True}
    monkeypatch.setattr(transport, "_READ_ONLY_MCP_CALL_BUDGET_SECONDS", 0.02)
    monkeypatch.setattr(transport, "_IPC_READINESS_BUDGET_SECONDS", 0.02, raising=False)

    class Worker:
        async def call_tool(self, tool, arguments, **_kwargs: object):
            if tool == "kicad_set_project":
                return SimpleNamespace(isError=False, content=[])
            assert tool == name
            status["calls"] += 1
            if status["calls"] == 1:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    status["cancelled"] += 1
                    raise
            return SimpleNamespace(
                model_dump=lambda **_: {
                    "isError": False,
                    "content": [{"type": "text", "text": "completed"}],
                }
            )

        async def list_tools(self):
            return SimpleNamespace(tools=[Tool(name=name, inputSchema={"type": "object"})])

    @asynccontextmanager
    async def worker(folder, *, profile, operating_mode):
        assert folder == tmp_path
        assert profile == "expert"
        assert operating_mode == "readonly"
        try:
            yield Worker()
        finally:
            status["closed"] += 1

    monkeypatch.setattr(transport, "project_stdio_worker", worker)
    service = GenericProjectMcpService(
        receipt=HandshakeReceipt(device_id=DEVICE, session_id=SESSION),
        local_project=lambda _: project,
        current_authorization=lambda: status["granted"],
    )
    sent: list[dict[str, object]] = []

    class Socket:
        async def send(self, value: str) -> None:
            sent.append(json.loads(value))

        async def recv(self) -> str:
            return json.dumps(
                {
                    "kind": "connector.mcp_ack",
                    "version": 1,
                    "sequence": 1,
                    "requestId": REQ,
                }
            )

    request = json.dumps(
        {
            "kind": "connector.mcp_request",
            "version": 1,
            "sequence": 1,
            "request": frame("call", name=name, args="{}"),
        }
    )
    first = await asyncio.wait_for(
        _serve_one_mcp_request(Socket(), service, request, expected_sequence=1),
        timeout=0.3,
    )
    assert sent[0]["kind"] == "connector.mcp_result"
    assert sent[0]["result"]["requestId"] == REQ
    assert first["ok"] is True
    assert first["result"]["isError"] is True
    assert first["result"]["structuredContent"]["reason"] == "local_mcp_read_timeout"
    assert "re-pair" in first["result"]["content"][0]["text"]
    assert status == {"calls": 1, "cancelled": 1, "closed": 1, "granted": True}

    second = await service.dispatch(frame("call", name=name, args="{}", request_id=OTHER_REQ))
    assert second["ok"] is True
    assert second["result"]["isError"] is False
    assert status["calls"] == 2
    assert status["closed"] == 2


@pytest.mark.asyncio
async def test_stalled_read_never_reports_recovery_after_grant_revoked(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    import kicad_mcp.cloud_generic_mcp_transport as transport

    project = project_fixture(tmp_path)
    status = {"granted": True}
    monkeypatch.setattr(transport, "_READ_ONLY_MCP_CALL_BUDGET_SECONDS", 0.02)

    class Worker:
        async def call_tool(self, name, arguments, **_kwargs: object):
            if name == "kicad_set_project":
                return SimpleNamespace(isError=False, content=[])
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                status["granted"] = False
                raise

        async def list_tools(self):
            return SimpleNamespace(tools=[Tool(name="run_drc", inputSchema={"type": "object"})])

    @asynccontextmanager
    async def worker(folder, *, profile, operating_mode):
        yield Worker()

    monkeypatch.setattr(transport, "project_stdio_worker", worker)
    service = GenericProjectMcpService(
        receipt=HandshakeReceipt(device_id=DEVICE, session_id=SESSION),
        local_project=lambda _: project,
        current_authorization=lambda: status["granted"],
    )
    request = frame("call", name="run_drc", args="{}")
    pending = asyncio.wait_for(service.dispatch(request), timeout=0.3)
    with pytest.raises(GenericMcpTransportError, match="mcp_bridge_request_denied"):
        await pending


@pytest.mark.parametrize("value", ["C:board.kicad_pcb", " /etc/passwd", " file:///tmp/file"])
def test_remote_path_rejects_drive_relative_and_padded_paths(value: str) -> None:
    assert not _safe_arguments({"path": value})


def test_hierarchical_net_names_allowed_only_for_reviewed_net_arguments() -> None:
    assert _safe_arguments({"filter_net": "/Power/VCC"}, tool_name="pcb_get_tracks")
    assert _safe_arguments({"net_name": "/Power/VCC"}, tool_name="pcb_add_track")
    assert not _safe_arguments({"path": "/Power/VCC"}, tool_name="pcb_get_tracks")
    assert not _safe_arguments({"filter_net": "/Power/VCC"}, tool_name="unreviewed_tool")
    assert not _safe_arguments({"nested": {"filter_net": "/Power/VCC"}}, tool_name="pcb_get_tracks")
    for value in [
        "//server/share",
        "/Power/../VCC",
        "/Power\\VCC",
        "/Power/C:secret",
        " /Power/VCC",
        "/Power/\x00VCC",
    ]:
        assert not _safe_arguments({"filter_net": value}, tool_name="pcb_get_tracks")
