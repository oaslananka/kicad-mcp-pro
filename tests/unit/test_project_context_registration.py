from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType
from typing import Any

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata

NAMES = ["kicad_set_project", "kicad_get_project_info"]


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.project_context")
    assert spec is not None, "Project context FastMCP adapter must be extracted"
    return importlib.import_module("kicad_mcp.tools.project_context")


class FakeProjectContextService:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def set_project(
        self,
        project_dir: str,
        pcb_file: str = "",
        sch_file: str = "",
        output_dir: str = "",
    ) -> str:
        self.calls.append(("set", project_dir, pcb_file, sch_file, output_dir))
        return "set-result"

    def get_project_info(self) -> str:
        self.calls.append(("get",))
        return "get-result"


def test_registration_preserves_names_defaults_metadata_and_delegation(tmp_path) -> None:
    adapter = _adapter()
    server = FastMCP("project-context-test")
    service = FakeProjectContextService()
    adapter.register(server, adapter.ProjectContextDependencies(service=service))

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == NAMES
    by_name = {tool.name: tool for tool in tools}

    project_dir = str(tmp_path / "demo")
    assert by_name["kicad_set_project"].fn(project_dir) == "set-result"
    assert by_name["kicad_get_project_info"].fn() == "get-result"
    assert service.calls == [("set", project_dir, "", "", ""), ("get",)]

    set_schema = by_name["kicad_set_project"].parameters
    assert set_schema["required"] == ["project_dir"]
    assert set_schema["properties"]["pcb_file"]["default"] == ""
    assert set_schema["properties"]["sch_file"]["default"] == ""
    assert set_schema["properties"]["output_dir"]["default"] == ""
    assert by_name["kicad_get_project_info"].parameters["properties"] == {}

    assert by_name["kicad_set_project"].description.startswith(
        "Set the active KiCad project directory and file paths."
    )
    assert by_name["kicad_get_project_info"].description.startswith(
        "Show the currently configured KiCad project paths."
    )
    for name in NAMES:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False
