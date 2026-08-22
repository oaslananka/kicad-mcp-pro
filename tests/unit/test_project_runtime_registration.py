from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.project_runtime import ProjectRuntimeDependencies, register


class FakeRuntimeService:
    def __init__(self) -> None:
        self.calls = 0

    def version_info(self) -> str:
        self.calls += 1
        return "runtime-result"


def test_registration_preserves_version_tool_contract_and_delegation() -> None:
    mcp = FastMCP("project-runtime-test")
    service = FakeRuntimeService()

    register(mcp, ProjectRuntimeDependencies(service=service))

    tools = mcp._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["kicad_get_version"]
    tool = tools[0]
    assert tool.fn() == "runtime-result"
    assert service.calls == 1
    assert tool.parameters["properties"] == {}
    assert tool.parameters.get("required") is None
    assert tool.description == "Get KiCad version information and current connection status."
