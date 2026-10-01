from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from mcp.server.mcpserver import MCPServer
from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[2]


def test_mcp_sdk_v2_dependency_range_and_lock_are_reviewed() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    uv_lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    requirement = next(
        Requirement(dependency)
        for dependency in pyproject["project"]["dependencies"]
        if Requirement(dependency).name == "mcp"
    )
    assert requirement.extras == {"cli"}
    assert str(requirement.specifier) == "<3.0.0,>=2.2.0"

    locked = {
        package["name"].lower(): Version(package["version"])
        for package in uv_lock["package"]
        if package["name"].lower() in {"mcp", "mcp-types"}
    }
    assert Version("2.2.0") <= locked["mcp"] < Version("3.0.0")
    assert locked["mcp-types"] == locked["mcp"]


def test_custom_runtime_requirement_metadata_moves_to_meta(sample_project: Path) -> None:
    _ = sample_project
    from kicad_mcp.server import build_server

    server = build_server("pcb")
    server.filter_runtime_tools = False
    tools = {tool.name: tool for tool in server.list_tools_sync()}

    live_tool = tools["pcb_get_pads"]
    assert live_tool.annotations is not None
    assert "requiresKiCadRunning" not in live_tool.annotations.model_dump(
        by_alias=True,
        exclude_none=True,
    )
    assert live_tool.meta is not None
    assert live_tool.meta["requiresKiCadRunning"] is True

    headless_tool = tools["pcb_get_board_summary"]
    assert not (headless_tool.meta or {}).get("requiresKiCadRunning", False)


@pytest.mark.anyio
async def test_sdk_v2_mcpserver_keeps_high_level_tool_surface() -> None:
    server = MCPServer("surface-contract")

    @server.tool(structured_output=True)
    def echo(value: str) -> dict[str, str]:
        return {"value": value}

    tools = await server.list_tools()
    assert [tool.name for tool in tools] == ["echo"]
    assert tools[0].output_schema is not None

    result = await server.call_tool("echo", {"value": "ok"})
    assert result.is_error is False
    assert result.structured_content == {"value": "ok"}
