from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.project_discovery import ProjectDiscoveryDependencies, register


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def list_recent_projects(self) -> str:
        self.calls.append(("recent",))
        return "recent-result"

    def scan_directory(self, path: str) -> str:
        self.calls.append(("scan", path))
        return "scan-result"


def test_registration_preserves_order_contract_and_delegation(tmp_path: Path) -> None:
    mcp = FastMCP("project-discovery-test")
    service = FakeService()
    register(mcp, ProjectDiscoveryDependencies(service=service))
    tools = mcp._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["kicad_list_recent_projects", "kicad_scan_directory"]
    by_name = {tool.name: tool for tool in tools}
    assert by_name["kicad_list_recent_projects"].fn() == "recent-result"
    target = str(tmp_path)
    assert by_name["kicad_scan_directory"].fn(target) == "scan-result"
    assert service.calls == [("recent",), ("scan", target)]
    assert by_name["kicad_list_recent_projects"].parameters["properties"] == {}
    assert by_name["kicad_scan_directory"].parameters["required"] == ["path"]
    assert (
        by_name["kicad_scan_directory"].description
        == "Scan a directory and report any KiCad project files it contains."
    )
