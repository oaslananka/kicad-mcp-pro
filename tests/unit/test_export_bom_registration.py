from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.export_bom")
    assert spec is not None, "BOM export adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.export_bom")


class FakeBomService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def export(self, format: str = "csv", variant_name: str | None = None) -> str:
        self.calls.append((format, variant_name))
        return "raw:bom"


def _registered() -> tuple[FastMCP, FakeBomService]:
    adapter = _adapter()
    server = FastMCP("export-bom-test")
    service = FakeBomService()
    adapter.register(
        server,
        adapter.ExportBomDependencies(
            service=service,
            add_low_level_notice=lambda value: f"notice::{value}",
        ),
    )
    return server, service


def test_registration_preserves_exact_name_schema_description_and_metadata() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert list(tools) == ["export_bom"]
    assert tools["export_bom"].description == "Export a bill of materials."
    assert tools["export_bom"].parameters == {
        "properties": {"format": {"default": "csv", "title": "Format", "type": "string"}},
        "title": "export_bomArguments",
        "type": "object",
    }
    metadata = get_tool_metadata("export_bom")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False


def test_registration_preserves_notice_and_public_delegation() -> None:
    server, service = _registered()
    tool = server._tool_manager.list_tools()[0]

    assert tool.fn(format="xml") == "notice::raw:bom"
    assert service.calls == [("xml", None)]


def test_export_composition_root_preserves_bom_registration_order() -> None:
    from kicad_mcp.tools.export import register as register_export

    server = FastMCP("export-bom-order-test")
    register_export(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [name for name in names if name in {"export_drill", "export_bom", "export_netlist"}]
    assert relevant == ["export_drill", "export_bom", "export_netlist"]
