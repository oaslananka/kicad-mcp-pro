"""Generic, project-bound local MCP bridge acceptance."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from mcp.types import Tool

from kicad_mcp.cloud_generic_mcp_bridge import GenericMcpDeniedError, GenericProjectMcpBridge
from kicad_mcp.cloud_readonly_boundary import OperatorProject, VerifiedLocalBinding

DEVICE = "11111111-1111-4111-8111-111111111111"
PROJECT = "22222222-2222-4222-8222-222222222222"
SESSION = "33333333-3333-4333-8333-333333333333"


def bridge(tmp_path, *, edit=False, authorized=lambda: True) -> GenericProjectMcpBridge:
    (tmp_path / "board.kicad_pro").write_text("{}", encoding="utf8")
    return GenericProjectMcpBridge(
        verified=VerifiedLocalBinding(
            device_id=DEVICE,
            project_id=PROJECT,
            session_id=SESSION,
            operations=frozenset({"mcp_bridge"}),
            session_expires_unix_ms=4000000000000,
        ),
        operator_project=OperatorProject(
            device_id=DEVICE,
            project_id=PROJECT,
            directory=tmp_path,
            filename_stem="board",
        ),
        current_authorization=authorized,
        allow_native_write=edit,
        profile="expert",
        now_ms=lambda: 3000000000000,
    )


class FakeSession:
    def __init__(self) -> None:
        self.calls = []

    async def list_tools(self) -> SimpleNamespace:
        return SimpleNamespace(
            tools=[
                Tool(
                    name="kicad_get_version",
                    description="Read version",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="sch_add_symbol",
                    description="Add a symbol",
                    inputSchema={"type": "object", "properties": {"reference": {"type": "string"}}},
                ),
                Tool(
                    name="export_manufacturing_package",
                    description="Manufacturing",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="variant_export_manufacturing_package",
                    description="Hidden manufacturing export",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="kicad_set_project",
                    description="Switch project",
                    inputSchema={"type": "object", "properties": {}},
                ),
                Tool(
                    name="unexpected_external_tool",
                    description="Unregistered",
                    inputSchema={"type": "object", "properties": {}},
                ),
            ]
        )

    async def call_tool(self, name, arguments) -> SimpleNamespace:
        self.calls.append((name, arguments))
        return SimpleNamespace(
            model_dump=lambda **_: {"content": [{"type": "text", "text": "ok"}], "isError": False}
        )


@pytest.mark.asyncio
async def test_catalog_reuses_registered_local_tools_and_excludes_manufacturing(tmp_path) -> None:
    session = FakeSession()
    local = bridge(tmp_path, edit=True)
    catalog = await local.list_tools(session, project_id=PROJECT, session_id=SESSION)
    assert [t["name"] for t in catalog] == ["kicad_get_version", "sch_add_symbol"]
    assert catalog[1]["inputSchema"]["properties"]["reference"]["type"] == "string"
    assert catalog[0]["accessMode"] == "readonly"
    assert catalog[1]["accessMode"] == "write"


@pytest.mark.asyncio
async def test_project_session_and_revocation_fail_closed(tmp_path) -> None:
    local = bridge(tmp_path)
    session = FakeSession()
    with pytest.raises(GenericMcpDeniedError):
        await local.list_tools(
            session, project_id="99999999-9999-4999-8999-999999999999", session_id=SESSION
        )
    revoked = bridge(tmp_path, authorized=lambda: False)
    with pytest.raises(GenericMcpDeniedError):
        await revoked.list_tools(session, project_id=PROJECT, session_id=SESSION)


@pytest.mark.asyncio
async def test_read_tool_works_and_write_requires_owner_proof(tmp_path) -> None:
    session = FakeSession()
    local = bridge(tmp_path, edit=True)
    result = await local.call_tool(
        session,
        project_id=PROJECT,
        session_id=SESSION,
        name="kicad_get_version",
        arguments={},
        write_approved=False,
    )
    assert result["content"][0]["text"] == "ok"
    with pytest.raises(GenericMcpDeniedError):
        await local.call_tool(
            session,
            project_id=PROJECT,
            session_id=SESSION,
            name="sch_add_symbol",
            arguments={"reference": "R1"},
            write_approved=False,
        )
    with pytest.raises(GenericMcpDeniedError):
        await local.call_tool(
            session,
            project_id=PROJECT,
            session_id=SESSION,
            name="export_manufacturing_package",
            arguments={},
            write_approved=True,
        )
    with pytest.raises(GenericMcpDeniedError):
        await local.call_tool(
            session,
            project_id=PROJECT,
            session_id=SESSION,
            name="kicad_set_project",
            arguments={"path": "../other"},
            write_approved=True,
        )
    with pytest.raises(GenericMcpDeniedError):
        await local.call_tool(
            session,
            project_id=PROJECT,
            session_id=SESSION,
            name="variant_export_manufacturing_package",
            arguments={},
            write_approved=True,
        )
    assert session.calls == [("kicad_get_version", {})]


@pytest.mark.asyncio
async def test_valid_approved_write_uses_original_name_and_arguments(tmp_path) -> None:
    session = FakeSession()
    local = bridge(tmp_path, edit=True)
    result = await local.call_tool(
        session,
        project_id=PROJECT,
        session_id=SESSION,
        name="sch_add_symbol",
        arguments={"reference": "R2"},
        write_approved=True,
        not_after_unix_ms=4_000_000_000_000,
    )
    assert result["isError"] is False
    assert session.calls == [("sch_add_symbol", {"reference": "R2"})]

    with pytest.raises(GenericMcpDeniedError, match="deadline_expired"):
        await local.call_tool(
            session,
            project_id=PROJECT,
            session_id=SESSION,
            name="sch_add_symbol",
            arguments={"reference": "R3"},
            write_approved=True,
            not_after_unix_ms=3_000_000_000_000,
        )
    assert session.calls == [("sch_add_symbol", {"reference": "R2"})]


def test_project_worker_can_choose_existing_expert_write_profile(tmp_path) -> None:
    from kicad_mcp.project.stdio_worker import project_worker_parameters

    options = project_worker_parameters(tmp_path, profile="expert", operating_mode="write")
    assert options.env["KICAD_MCP_PROFILE"] == "expert"
    assert options.env["KICAD_MCP_OPERATING_MODE"] == "write"
    assert options.env["KICAD_MCP_PROJECT_DIR"] == str(tmp_path.resolve())
    with pytest.raises(ValueError):
        project_worker_parameters(tmp_path, profile="unknown", operating_mode="experimental")


@pytest.mark.asyncio
async def test_explicit_paths_outside_owner_project_are_rejected(tmp_path) -> None:
    session = FakeSession()
    local = bridge(tmp_path, edit=True)
    with pytest.raises(GenericMcpDeniedError):
        await local.call_tool(
            session,
            project_id=PROJECT,
            session_id=SESSION,
            name="sch_add_symbol",
            arguments={"reference": "R3", "path": "C:\\Users\\secret\\other.kicad_sch"},
            write_approved=True,
        )
    with pytest.raises(GenericMcpDeniedError):
        await local.call_tool(
            session,
            project_id=PROJECT,
            session_id=SESSION,
            name="sch_add_symbol",
            arguments={"reference": "R3", "output": "../another/board.kicad_pcb"},
            write_approved=True,
        )


@pytest.mark.asyncio
async def test_private_windows_paths_redacted_from_generic_result(tmp_path) -> None:
    local = bridge(tmp_path)

    class PathSession(FakeSession):
        async def call_tool(self, name, arguments) -> SimpleNamespace:
            return SimpleNamespace(
                model_dump=lambda **_: {
                    "content": [
                        {"type": "text", "text": "C:\\Users\\Admin\\Secret\\board.kicad_pcb"}
                    ],
                    "structuredContent": {"path": str(tmp_path / "board.kicad_pcb")},
                }
            )

    value = await local.call_tool(
        PathSession(),
        project_id=PROJECT,
        session_id=SESSION,
        name="kicad_get_version",
        arguments={},
        write_approved=False,
    )
    assert "C:\\Users" not in str(value)
    assert str(tmp_path) not in str(value)
    assert "[local-path]" in str(value)
