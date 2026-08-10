from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.export_pcb_3d_pdf")
    assert spec is not None, "PCB 3D PDF adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.export_pcb_3d_pdf")


class FakePcb3dPdfService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def export(self, output_path: str = "") -> str:
        self.calls.append(output_path)
        return "raw:3d-pdf"


def _registered() -> tuple[FastMCP, FakePcb3dPdfService]:
    adapter = _adapter()
    server = FastMCP("export-pcb-3d-pdf-test")
    service = FakePcb3dPdfService()
    adapter.register(
        server,
        adapter.ExportPcb3dPdfDependencies(
            service=service,
            add_low_level_notice=lambda value: f"notice::{value}",
        ),
    )
    return server, service


def test_registration_preserves_exact_name_schema_description_and_metadata() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert list(tools) == ["pcb_export_3d_pdf"]
    assert tools["pcb_export_3d_pdf"].description == (
        "Export the PCB to a 3D PDF.\n\n"
        "Parameters\n----------\n"
        "output_path : str\n"
        "    Output file name (relative to the export output directory)."
    )
    assert tools["pcb_export_3d_pdf"].parameters == {
        "properties": {"output_path": {"default": "", "title": "Output Path", "type": "string"}},
        "title": "pcb_export_3d_pdfArguments",
        "type": "object",
    }
    metadata = get_tool_metadata("pcb_export_3d_pdf")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False


def test_registration_preserves_notice_and_delegation() -> None:
    server, service = _registered()
    tool = server._tool_manager.list_tools()[0]

    assert tool.fn(output_path="custom.pdf") == "notice::raw:3d-pdf"
    assert service.calls == ["custom.pdf"]


def test_export_root_preserves_3d_pdf_registration_order() -> None:
    from kicad_mcp.tools.export import register as register_export

    server = FastMCP("export-pcb-3d-pdf-order-test")
    register_export(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [
        name for name in names if name in {"export_ps", "pcb_export_3d_pdf", "export_3d_render"}
    ]
    assert relevant == ["export_ps", "pcb_export_3d_pdf", "export_3d_render"]
