from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.export_sch_python_bom")
    assert spec is not None, "schematic Python BOM adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.export_sch_python_bom")


class FakeSchPythonBomService:
    def __init__(self) -> None:
        self.calls = 0

    def export(self, output_file: str = "") -> str:
        self.calls += 1
        assert output_file == ""
        return "raw:python-bom"


def _registered() -> tuple[FastMCP, FakeSchPythonBomService]:
    adapter = _adapter()
    server = FastMCP("export-sch-python-bom-test")
    service = FakeSchPythonBomService()
    adapter.register(
        server,
        adapter.ExportSchPythonBomDependencies(
            service=service,
            add_low_level_notice=lambda value: f"notice::{value}",
        ),
    )
    return server, service


def test_registration_preserves_exact_name_schema_description_and_metadata() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert list(tools) == ["export_sch_python_bom"]
    assert tools["export_sch_python_bom"].description == (
        "Export the schematic BOM using KiCad's Python BOM engine."
    )
    assert tools["export_sch_python_bom"].parameters == {
        "properties": {},
        "title": "export_sch_python_bomArguments",
        "type": "object",
    }
    metadata = get_tool_metadata("export_sch_python_bom")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False


def test_registration_preserves_notice_and_public_delegation() -> None:
    server, service = _registered()
    tool = server._tool_manager.list_tools()[0]

    assert tool.fn() == "notice::raw:python-bom"
    assert service.calls == 1


def test_export_composition_root_preserves_python_bom_registration_order() -> None:
    from kicad_mcp.tools.export import register as register_export

    server = FastMCP("export-sch-python-bom-order-test")
    register_export(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [
        name
        for name in names
        if name in {"export_sch_dxf", "export_sch_python_bom", "export_3d_step"}
    ]
    assert relevant == ["export_sch_dxf", "export_sch_python_bom", "export_3d_step"]
