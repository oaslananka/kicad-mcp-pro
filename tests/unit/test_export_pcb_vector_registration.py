from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.export_pcb_vector")
    assert spec is not None, "PCB vector export adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.export_pcb_vector")


class FakePcbVectorService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def export_svg(self, layer: str = "F.Cu") -> str:
        self.calls.append(("svg", layer))
        return f"raw:svg:{layer}"

    def export_dxf(self, layer: str = "Edge.Cuts") -> str:
        self.calls.append(("dxf", layer))
        return f"raw:dxf:{layer}"


def _registered() -> tuple[FastMCP, FakePcbVectorService]:
    adapter = _adapter()
    server = FastMCP("export-pcb-vector-test")
    service = FakePcbVectorService()
    adapter.register(
        server,
        adapter.ExportPcbVectorDependencies(
            service=service,
            add_low_level_notice=lambda value: f"notice::{value}",
        ),
    )
    return server, service


def test_registration_preserves_exact_names_schemas_descriptions_and_metadata() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert list(tools) == ["export_svg", "export_dxf"]
    assert tools["export_svg"].description == "Export a board layer to SVG when supported."
    assert tools["export_dxf"].description == "Export a board layer to DXF when supported."
    assert tools["export_svg"].parameters == {
        "properties": {"layer": {"default": "F.Cu", "title": "Layer", "type": "string"}},
        "title": "export_svgArguments",
        "type": "object",
    }
    assert tools["export_dxf"].parameters == {
        "properties": {"layer": {"default": "Edge.Cuts", "title": "Layer", "type": "string"}},
        "title": "export_dxfArguments",
        "type": "object",
    }
    for name in tools:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False


def test_registration_preserves_notice_defaults_and_delegation() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["export_svg"].fn() == "notice::raw:svg:F.Cu"
    assert tools["export_dxf"].fn() == "notice::raw:dxf:Edge.Cuts"
    assert tools["export_svg"].fn("B.Cu") == "notice::raw:svg:B.Cu"
    assert tools["export_dxf"].fn("F.SilkS") == "notice::raw:dxf:F.SilkS"
    assert service.calls == [
        ("svg", "F.Cu"),
        ("dxf", "Edge.Cuts"),
        ("svg", "B.Cu"),
        ("dxf", "F.SilkS"),
    ]


def test_export_composition_root_preserves_pcb_vector_registration_order() -> None:
    from kicad_mcp.tools.export import register as register_export

    server = FastMCP("export-pcb-vector-order-test")
    register_export(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [
        name
        for name in names
        if name in {"export_odb", "export_svg", "export_dxf", "get_board_stats"}
    ]
    assert relevant == ["export_odb", "export_svg", "export_dxf", "get_board_stats"]
