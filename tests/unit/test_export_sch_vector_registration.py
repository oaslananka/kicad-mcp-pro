from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.export_sch_vector")
    assert spec is not None, "schematic vector export adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.export_sch_vector")


class FakeSchVectorService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def export_svg(self) -> str:
        self.calls.append("svg")
        return "raw:svg"

    def export_dxf(self) -> str:
        self.calls.append("dxf")
        return "raw:dxf"


def _registered() -> tuple[FastMCP, FakeSchVectorService]:
    adapter = _adapter()
    server = FastMCP("export-sch-vector-test")
    service = FakeSchVectorService()
    adapter.register(
        server,
        adapter.ExportSchVectorDependencies(
            service=service,
            add_low_level_notice=lambda value: f"notice::{value}",
        ),
    )
    return server, service


def test_registration_preserves_exact_names_schemas_descriptions_and_metadata() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert list(tools) == ["export_sch_svg", "export_sch_dxf"]
    assert tools["export_sch_svg"].description == "Export the schematic to SVG when supported."
    assert tools["export_sch_dxf"].description == "Export the schematic to DXF when supported."
    assert tools["export_sch_svg"].parameters == {
        "properties": {},
        "title": "export_sch_svgArguments",
        "type": "object",
    }
    assert tools["export_sch_dxf"].parameters == {
        "properties": {},
        "title": "export_sch_dxfArguments",
        "type": "object",
    }
    for name in tools:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False


def test_registration_preserves_notice_and_public_delegation() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["export_sch_svg"].fn() == "notice::raw:svg"
    assert tools["export_sch_dxf"].fn() == "notice::raw:dxf"
    assert service.calls == ["svg", "dxf"]


def test_export_composition_root_preserves_vector_registration_order() -> None:
    from kicad_mcp.tools.export import register as register_export

    server = FastMCP("export-sch-vector-order-test")
    register_export(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [
        name
        for name in names
        if name in {"export_sch_pdf", "export_sch_svg", "export_sch_dxf", "export_sch_python_bom"}
    ]
    assert relevant == [
        "export_sch_pdf",
        "export_sch_svg",
        "export_sch_dxf",
        "export_sch_python_bom",
    ]
