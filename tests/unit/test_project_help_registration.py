from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata

NAMES = ["kicad_help"]


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.project_help")
    assert spec is not None, "Project help FastMCP adapter must be extracted"
    return importlib.import_module("kicad_mcp.tools.project_help")


class FakeProjectHelpService:
    def __init__(self) -> None:
        self.calls = 0

    def help_text(self) -> str:
        self.calls += 1
        return "help-result"


def test_registration_preserves_names_defaults_metadata_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("project-help-test")
    service = FakeProjectHelpService()
    adapter.register(server, adapter.ProjectHelpDependencies(service=service))

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == NAMES
    by_name = {tool.name: tool for tool in tools}

    assert by_name["kicad_help"].fn() == "help-result"
    assert service.calls == 1

    assert by_name["kicad_help"].parameters["properties"] == {}
    assert by_name["kicad_help"].description.startswith(
        "Show a concise startup guide and all tool categories."
    )

    metadata = get_tool_metadata("kicad_help")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False
