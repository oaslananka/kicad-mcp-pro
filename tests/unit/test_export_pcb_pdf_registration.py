from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.export_pcb_pdf")
    assert spec is not None, "PCB PDF export adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.export_pcb_pdf")


class FakePcbPdfService:
    def __init__(self) -> None:
        self.calls: list[list[str] | None] = []

    def export(self, layers: list[str] | None = None) -> str:
        self.calls.append(layers)
        return f"raw:{layers!r}"


def _registered() -> tuple[FastMCP, FakePcbPdfService]:
    adapter = _adapter()
    server = FastMCP("export-pcb-pdf-test")
    service = FakePcbPdfService()
    adapter.register(
        server,
        adapter.ExportPcbPdfDependencies(
            service=service,
            add_low_level_notice=lambda value: f"notice::{value}",
        ),
    )
    return server, service


def test_registration_preserves_exact_name_schema_description_and_metadata() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert list(tools) == ["export_pcb_pdf"]
    assert tools["export_pcb_pdf"].description == "Export the PCB to PDF."
    assert tools["export_pcb_pdf"].parameters == {
        "properties": {
            "layers": {
                "anyOf": [
                    {"items": {"type": "string"}, "type": "array"},
                    {"type": "null"},
                ],
                "default": None,
                "title": "Layers",
            }
        },
        "title": "export_pcb_pdfArguments",
        "type": "object",
    }
    metadata = get_tool_metadata("export_pcb_pdf")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False


def test_registration_preserves_notice_and_public_delegation() -> None:
    server, service = _registered()
    tool = server._tool_manager.list_tools()[0]

    assert tool.fn(["B.Cu"]) == "notice::raw:['B.Cu']"
    assert service.calls == [["B.Cu"]]


def test_export_composition_root_preserves_pcb_pdf_registration_order() -> None:
    from kicad_mcp.tools.export import register as register_export

    server = FastMCP("export-pcb-pdf-order-test")
    register_export(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [
        name
        for name in names
        if name in {"export_spice_netlist", "export_pcb_pdf", "export_sch_pdf"}
    ]
    assert relevant == ["export_spice_netlist", "export_pcb_pdf", "export_sch_pdf"]
