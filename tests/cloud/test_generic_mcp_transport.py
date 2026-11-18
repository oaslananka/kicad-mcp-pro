"""Project-scoped generic transport over the owner-signed Connector."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from mcp.types import Tool

from kicad_mcp.cloud_generic_mcp_transport import (
    GenericMcpTransportError,
    GenericProjectMcpService,
)
from kicad_mcp.cloud_outbound_handshake import HandshakeReceipt
from kicad_mcp.cloud_readonly_boundary import OperatorProject

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"
REQ = "44444444-4444-4444-8444-444444444444"


class FakeWorker:
    calls = []

    async def list_tools(self) -> SimpleNamespace:
        return SimpleNamespace(
            tools=[
                Tool(
                    name="kicad_get_version",
                    description="version",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="sch_add_symbol",
                    description="symbol",
                    inputSchema={"type": "object", "properties": {}},
                ),
            ]
        )

    async def call_tool(self, name, arguments) -> SimpleNamespace:
        self.calls.append((name, arguments))
        return SimpleNamespace(
            model_dump=lambda **_: {"content": [{"type": "text", "text": "ok"}], "isError": False},
            isError=False,
            content=[SimpleNamespace(type="text", text="ok")],
        )


@pytest.mark.asyncio
async def test_bound_mcp_catalog_and_read_call(tmp_path, monkeypatch) -> None:
    async def worker(folder, *, profile, operating_mode):
        assert folder == tmp_path
        assert profile == "expert"
        assert operating_mode == "readonly"
        return FakeWorker()

    @asynccontextmanager
    async def entered(folder, *, profile, operating_mode):
        yield await worker(folder, profile=profile, operating_mode=operating_mode)

    monkeypatch.setattr("kicad_mcp.cloud_generic_mcp_transport.project_stdio_worker", entered)
    project = OperatorProject(
        device_id=DEVICE, project_id=PROJECT, directory=tmp_path, filename_stem="temp"
    )
    service = GenericProjectMcpService(
        receipt=HandshakeReceipt(device_id=DEVICE, session_id=SESSION),
        local_project=lambda id: project if id == PROJECT else None,
        current_authorization=lambda: True,
        allow_native_write=False,
    )
    # Owner-selected target files are local; the AI never supplies these paths.
    (tmp_path / "temp.kicad_pro").write_text("{}", encoding="utf8")
    (tmp_path / "temp.kicad_pcb").write_text("(kicad_pcb)", encoding="utf8")
    FakeWorker.calls.clear()
    catalog = await service.dispatch(
        {
            "kind": "connector.mcp_request",
            "version": 1,
            "requestId": REQ,
            "projectId": PROJECT,
            "method": "catalog",
            "offset": 0,
        }
    )
    assert catalog["ok"] is True
    assert [t["name"] for t in catalog["tools"]] == ["kicad_get_version"]
    result = await service.dispatch(
        {
            "kind": "connector.mcp_request",
            "version": 1,
            "requestId": REQ,
            "projectId": PROJECT,
            "method": "call",
            "toolName": "kicad_get_version",
            "argumentsJson": "{}",
        }
    )
    assert result["ok"] is True
    assert result["result"]["content"][0]["text"] == "ok"
    activations = [
        (name, params) for name, params in FakeWorker.calls if name == "kicad_set_project"
    ]
    assert len(activations) == 2
    assert activations[0][1] == {
        "project_dir": str(tmp_path.resolve()),
        "pcb_file": "temp.kicad_pcb",
    }


@pytest.mark.asyncio
async def test_cross_project_rejected_before_worker_start(tmp_path) -> None:
    service = GenericProjectMcpService(
        receipt=HandshakeReceipt(device_id=DEVICE, session_id=SESSION),
        local_project=lambda id: None,
        current_authorization=lambda: True,
    )
    with pytest.raises(GenericMcpTransportError):
        await service.dispatch(
            {
                "kind": "connector.mcp_request",
                "version": 1,
                "requestId": REQ,
                "projectId": PROJECT,
                "method": "catalog",
                "offset": 0,
            }
        )


@pytest.mark.asyncio
async def test_write_without_owner_opt_in_is_rejected_before_worker(tmp_path) -> None:
    project = OperatorProject(
        device_id=DEVICE, project_id=PROJECT, directory=tmp_path, filename_stem="temp"
    )
    service = GenericProjectMcpService(
        receipt=HandshakeReceipt(device_id=DEVICE, session_id=SESSION),
        local_project=lambda id: project,
        current_authorization=lambda: True,
    )
    with pytest.raises(GenericMcpTransportError):
        await service.dispatch(
            {
                "kind": "connector.mcp_request",
                "version": 1,
                "requestId": REQ,
                "projectId": PROJECT,
                "method": "call",
                "toolName": "sch_add_symbol",
                "argumentsJson": "{}",
            }
        )


@pytest.mark.asyncio
async def test_existing_signed_socket_can_carry_one_generic_request_and_ack() -> None:
    import json

    from kicad_mcp.cloud_managed_read_transport import _serve_one_mcp_request

    class Socket:
        sent = []

        async def send(self, value):
            self.sent.append(json.loads(value))

        async def recv(self):
            return json.dumps(
                {"kind": "connector.mcp_ack", "version": 1, "sequence": 1, "requestId": REQ}
            )

    class Service:
        called = False

        async def dispatch(self, frame):
            self.called = True
            return {
                "kind": "connector.mcp_result",
                "version": 1,
                "requestId": frame["requestId"],
                "projectId": PROJECT,
                "method": "catalog",
                "ok": True,
                "tools": [],
                "nextOffset": None,
            }

    service = Service()
    sock = Socket()
    request = {
        "kind": "connector.mcp_request",
        "version": 1,
        "requestId": REQ,
        "projectId": PROJECT,
        "method": "catalog",
        "offset": 0,
    }
    wire = json.dumps(
        {"kind": "connector.mcp_request", "version": 1, "sequence": 1, "request": request}
    )
    await _serve_one_mcp_request(sock, service, wire, expected_sequence=1)
    assert service.called is True
    assert sock.sent[0]["kind"] == "connector.mcp_result"
    assert sock.sent[0]["sequence"] == 1


@pytest.mark.asyncio
async def test_ambiguous_project_folder_rejected_before_worker_dispatch(tmp_path) -> None:
    from kicad_mcp.cloud_generic_mcp_transport import _owner_project_files

    (tmp_path / "temp.kicad_pro").write_text("{}", encoding="utf8")
    (tmp_path / "temp.kicad_pcb").write_text("(kicad_pcb)", encoding="utf8")
    (tmp_path / "different.kicad_pro").write_text("{}", encoding="utf8")
    project = OperatorProject(
        device_id=DEVICE, project_id=PROJECT, directory=tmp_path, filename_stem="temp"
    )
    with pytest.raises(GenericMcpTransportError):
        _owner_project_files(project)


def test_missing_project_schematic_and_board_fails_closed(tmp_path) -> None:
    from kicad_mcp.cloud_generic_mcp_transport import _owner_project_files

    (tmp_path / "temp.kicad_pro").write_text("{}", encoding="utf8")
    project = OperatorProject(
        device_id=DEVICE, project_id=PROJECT, directory=tmp_path, filename_stem="temp"
    )
    with pytest.raises(GenericMcpTransportError):
        _owner_project_files(project)


def test_pcb_writer_cannot_target_another_live_gui_board(tmp_path, monkeypatch) -> None:
    import kicad_mcp.connection as connection
    from kicad_mcp.cloud_generic_mcp_transport import _require_owner_live_pcb

    project = OperatorProject(
        device_id=DEVICE, project_id=PROJECT, directory=tmp_path, filename_stem="temp"
    )
    wrong = SimpleNamespace(
        name="customer.kicad_pcb", get_project=lambda: SimpleNamespace(path=str(tmp_path))
    )
    monkeypatch.setattr(connection, "get_board", lambda: wrong)
    with pytest.raises(GenericMcpTransportError):
        _require_owner_live_pcb(project)
    correct = SimpleNamespace(
        name="temp.kicad_pcb", get_project=lambda: SimpleNamespace(path=str(tmp_path))
    )
    monkeypatch.setattr(connection, "get_board", lambda: correct)
    _require_owner_live_pcb(project)


@pytest.mark.parametrize("stem", ["clean-led-kicad10", "x-chip", "R0", "rev2026"])
def test_owner_project_accepts_safe_digit_and_x_stems(tmp_path, stem) -> None:
    from kicad_mcp.cloud_generic_mcp_transport import _owner_project_files

    (tmp_path / f"{stem}.kicad_pro").write_text("{}", encoding="utf8")
    (tmp_path / f"{stem}.kicad_pcb").write_text("(kicad_pcb)", encoding="utf8")
    project = OperatorProject(
        device_id=DEVICE, project_id=PROJECT, directory=tmp_path, filename_stem=stem
    )
    result = _owner_project_files(project)
    assert result["pcb_file"] == f"{stem}.kicad_pcb"


@pytest.mark.parametrize(
    "stem", [".", "..", "bad/path", r"bad\path", "bad:path", "bad" + chr(0) + "path", "trailing."]
)
def test_owner_project_rejects_unsafe_stems(tmp_path, stem) -> None:
    from kicad_mcp.cloud_generic_mcp_transport import _validated_owner_stem

    with pytest.raises(GenericMcpTransportError):
        _validated_owner_stem(stem)


def _oversized_mcp_reply(*, duplicate_text: bool = True) -> dict:
    structured = {
        "summary": "DRC reported 17 actionable finding(s).",
        "text": "DRC summary:\n- Violations: 17",
        "verdict": "FAIL",
        "metadata": {"actionable_violations": 17},
        "findings": [
            {"id": f"drc-{i}", "evidence": "verified-geometry-" + "x" * 1400} for i in range(24)
        ],
    }
    text = json.dumps(structured) if duplicate_text else "UNIQUE IMPORTANT DETAILS " + "x" * 80000
    return {
        "kind": "connector.mcp_result",
        "version": 1,
        "requestId": REQ,
        "projectId": PROJECT,
        "method": "call",
        "ok": True,
        "result": {
            "content": [{"type": "text", "text": text}],
            "structuredContent": structured,
            "isError": False,
            "resultType": "complete",
        },
    }


def test_cloud_duplicate_structured_drc_result_preserves_complete_findings() -> None:
    from kicad_mcp.cloud_generic_mcp_transport import _fit_cloud_mcp_response

    original = _oversized_mcp_reply()
    assert len(json.dumps(original).encode("utf8")) > 60_000
    result = _fit_cloud_mcp_response(original)
    assert len(json.dumps(result, ensure_ascii=False).encode("utf8")) <= 60_000
    assert result["ok"] is True
    assert result["result"]["isError"] is False
    assert result["result"]["structuredContent"] == original["result"]["structuredContent"]
    assert len(result["result"]["structuredContent"]["findings"]) == 24
    assert "DRC summary" in result["result"]["content"][0]["text"]
    assert result["result"]["content"] != original["result"]["content"]
    assert original["result"]["content"][0]["text"].startswith('{"summary":')


def test_cloud_oversized_unique_text_returns_bounded_explicit_error() -> None:
    from kicad_mcp.cloud_generic_mcp_transport import _fit_cloud_mcp_response

    original = _oversized_mcp_reply(duplicate_text=False)
    result = _fit_cloud_mcp_response(original)
    assert result["ok"] is True
    assert result["result"]["isError"] is True
    assert "mcp_bridge_result_too_large" in result["result"]["content"][0]["text"]
    assert "UNIQUE IMPORTANT DETAILS" not in json.dumps(result)
    assert "structuredContent" not in result["result"]
    assert len(json.dumps(result).encode("utf8")) <= 60_000


def test_cloud_extremely_large_structured_drc_returns_explicit_error() -> None:
    from kicad_mcp.cloud_generic_mcp_transport import _fit_cloud_mcp_response

    original = _oversized_mcp_reply()
    original["result"]["structuredContent"]["findings"].append(
        {"id": "oversized", "evidence": "s" * 75_000}
    )
    original["result"]["content"][0]["text"] = json.dumps(original["result"]["structuredContent"])
    result = _fit_cloud_mcp_response(original)
    assert result["result"]["isError"] is True
    assert "mcp_bridge_result_too_large" in result["result"]["content"][0]["text"]
    assert len(json.dumps(result).encode("utf8")) <= 60_000


def test_cloud_small_mcp_result_remains_unchanged() -> None:
    from kicad_mcp.cloud_generic_mcp_transport import _fit_cloud_mcp_response

    original = _oversized_mcp_reply()
    original["result"]["structuredContent"]["findings"] = []
    original["result"]["content"][0]["text"] = json.dumps(original["result"]["structuredContent"])
    assert _fit_cloud_mcp_response(original) == original


@pytest.mark.parametrize("case", ["malformed", "nonduplicate", "extra_metadata"])
def test_cloud_pre_redaction_keeps_unique_or_unverified_text(case: str) -> None:
    """Never shorten unproven text before local-path redaction."""
    from kicad_mcp.cloud_generic_mcp_bridge import _compact_redundant_json_before_redaction

    structured = {"summary": "Known DRC result", "evidence": "x" * 65_000}
    if case == "malformed":
        content = {"type": "text", "text": "{invalid json"}
    elif case == "nonduplicate":
        content = {"type": "text", "text": json.dumps({"extra": "unique finding"})}
    else:
        content = {
            "type": "text",
            "text": json.dumps(structured),
            "source": "extra unique metadata",
        }
    original = {"content": [content], "structuredContent": structured, "isError": False}
    assert len(json.dumps(original).encode("utf8")) > 60_000
    assert _compact_redundant_json_before_redaction(original) is original


@pytest.mark.parametrize(
    ("summary", "expected"),
    [
        ("DRC result with findings", "DRC result with findings"),
        (None, "Full findings are available in structuredContent."),
    ],
)
def test_cloud_pre_redaction_compaction_uses_safe_human_fallback(
    summary: str | None, expected: str
) -> None:
    """Absent human text must not remove the complete structured findings."""
    from kicad_mcp.cloud_generic_mcp_bridge import _compact_redundant_json_before_redaction

    structured = {"text": "", "evidence": "x" * 38_000}
    if summary is not None:
        structured["summary"] = summary
    original = {
        "content": [{"type": "text", "text": json.dumps(structured)}],
        "structuredContent": structured,
        "isError": False,
    }
    assert len(json.dumps(original).encode("utf8")) > 60_000
    reduced = _compact_redundant_json_before_redaction(original)
    assert reduced["content"] == [{"type": "text", "text": expected}]
    assert reduced["structuredContent"] == structured
    assert reduced["isError"] is False
    assert len(json.dumps(reduced).encode("utf8")) < 60_000


def test_cloud_oversized_invalid_text_type_fails_as_bounded_read_error() -> None:
    """Bad MCP text shapes cannot be mistaken for a redundant report."""
    from kicad_mcp.cloud_generic_mcp_transport import _fit_cloud_mcp_response

    original = _oversized_mcp_reply()
    original["result"]["structuredContent"]["findings"].append(
        {"id": "too-large", "evidence": "e" * 55_000}
    )
    original["result"]["content"][0]["text"] = 123
    result = _fit_cloud_mcp_response(original)
    assert result["result"]["isError"] is True
    assert "mcp_bridge_result_too_large" in result["result"]["content"][0]["text"]
    assert len(json.dumps(result).encode("utf8")) < 60_000


def test_cloud_oversized_catalog_still_fails_closed() -> None:
    """Only bounded tool-call results may use duplicate-text compaction."""
    from kicad_mcp.cloud_generic_mcp_transport import _fit_cloud_mcp_response

    original = _oversized_mcp_reply()
    original["method"] = "catalog"
    with pytest.raises(GenericMcpTransportError, match="mcp_bridge_result_too_large"):
        _fit_cloud_mcp_response(original)


def test_cloud_oversized_unrepresentable_write_remains_outcome_unknown() -> None:
    from kicad_mcp.cloud_generic_mcp_transport import _fit_cloud_mcp_response

    original = _oversized_mcp_reply(duplicate_text=False)
    with pytest.raises(GenericMcpTransportError, match="mcp_bridge_result_too_large"):
        _fit_cloud_mcp_response(original, write_approved=True)


@pytest.mark.asyncio
async def test_cloud_oversized_drc_result_survives_signed_ack(tmp_path, monkeypatch) -> None:
    """The real service/WS handoff must preserve all findings and ACK the call."""
    from kicad_mcp.cloud_managed_read_transport import _serve_one_mcp_request

    original = _oversized_mcp_reply()
    project = OperatorProject(
        device_id=DEVICE, project_id=PROJECT, directory=tmp_path, filename_stem="temp"
    )
    (tmp_path / "temp.kicad_pro").write_text("{}", encoding="utf8")
    (tmp_path / "temp.kicad_pcb").write_text("(kicad_pcb)", encoding="utf8")

    class Worker:
        async def list_tools(self):
            return SimpleNamespace(tools=[Tool(name="run_drc", inputSchema={"type": "object"})])

        async def call_tool(self, name, arguments):
            if name == "kicad_set_project":
                return SimpleNamespace(isError=False, content=[])
            assert name == "run_drc"
            assert arguments == {"save_report": False}
            return SimpleNamespace(model_dump=lambda **_: original["result"])

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

    class Socket:
        def __init__(self) -> None:
            self.sent = []

        async def send(self, value):
            self.sent.append(json.loads(value))

        async def recv(self):
            return json.dumps(
                {"kind": "connector.mcp_ack", "version": 1, "sequence": 1, "requestId": REQ}
            )

    socket = Socket()
    request = {
        "kind": "connector.mcp_request",
        "version": 1,
        "requestId": REQ,
        "projectId": PROJECT,
        "method": "call",
        "toolName": "run_drc",
        "argumentsJson": '{"save_report":false}',
    }
    wire = json.dumps(
        {"kind": "connector.mcp_request", "version": 1, "sequence": 1, "request": request}
    )
    result = await _serve_one_mcp_request(socket, service, wire, expected_sequence=1)
    assert result["ok"] is True
    assert result["result"]["isError"] is False
    assert result["result"]["structuredContent"] == original["result"]["structuredContent"]
    assert len(result["result"]["structuredContent"]["findings"]) == 24
    assert len(json.dumps(socket.sent[0], ensure_ascii=False).encode("utf8")) < 65_536
    assert socket.sent[0]["result"]["result"]["content"][0]["text"].startswith("DRC summary")
