"""Project-scoped generic transport over the owner-signed Connector."""

from __future__ import annotations

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
