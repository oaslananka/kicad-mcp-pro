from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.export_sch_pdf")
    assert spec is not None, "schematic PDF export adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.export_sch_pdf")


class FakeSchPdfService:
    def __init__(self) -> None:
        self.calls = 0

    def export(self) -> str:
        self.calls += 1
        return "raw:schematic-pdf"


def _registered() -> tuple[FastMCP, FakeSchPdfService]:
    adapter = _adapter()
    server = FastMCP("export-sch-pdf-test")
    service = FakeSchPdfService()
    adapter.register(
        server,
        adapter.ExportSchPdfDependencies(
            service=service,
            add_low_level_notice=lambda value: f"notice::{value}",
        ),
    )
    return server, service


def test_registration_preserves_exact_name_schema_description_and_metadata() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert list(tools) == ["export_sch_pdf"]
    assert tools["export_sch_pdf"].description == "Export the schematic to PDF."
    assert tools["export_sch_pdf"].parameters == {
        "properties": {},
        "title": "export_sch_pdfArguments",
        "type": "object",
    }
    metadata = get_tool_metadata("export_sch_pdf")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False


def test_registration_preserves_notice_and_public_delegation() -> None:
    server, service = _registered()
    tool = server._tool_manager.list_tools()[0]

    assert tool.fn() == "notice::raw:schematic-pdf"
    assert service.calls == 1


def test_export_composition_root_preserves_sch_pdf_registration_order() -> None:
    from kicad_mcp.tools.export import register as register_export

    server = FastMCP("export-sch-pdf-order-test")
    register_export(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [
        name for name in names if name in {"export_pcb_pdf", "export_sch_pdf", "export_sch_svg"}
    ]
    assert relevant == ["export_pcb_pdf", "export_sch_pdf", "export_sch_svg"]
