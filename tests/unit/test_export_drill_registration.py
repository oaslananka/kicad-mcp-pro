from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.export_drill")
    assert spec is not None, "drill export adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.export_drill")


class FakeDrillService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []

    def export(self, output_subdir: str = "gerber", variant_name: str | None = None) -> str:
        self.calls.append((output_subdir, variant_name))
        return f"raw:{output_subdir}:{variant_name}"


def _registered() -> tuple[FastMCP, FakeDrillService]:
    adapter = _adapter()
    server = FastMCP("export-drill-test")
    service = FakeDrillService()
    adapter.register(
        server,
        adapter.ExportDrillDependencies(
            service=service,
            add_low_level_notice=lambda value: f"notice::{value}",
        ),
    )
    return server, service


def test_registration_preserves_exact_name_schema_description_and_metadata() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert list(tools) == ["export_drill"]
    assert tools["export_drill"].description == "Export drill files."
    assert tools["export_drill"].parameters == {
        "properties": {
            "output_subdir": {
                "default": "gerber",
                "title": "Output Subdir",
                "type": "string",
            }
        },
        "title": "export_drillArguments",
        "type": "object",
    }
    metadata = get_tool_metadata("export_drill")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False


def test_registration_preserves_notice_and_public_delegation() -> None:
    server, service = _registered()
    tool = server._tool_manager.list_tools()[0]

    assert tool.fn("fab") == "notice::raw:fab:None"
    assert service.calls == [("fab", None)]


def test_export_composition_root_preserves_drill_registration_order() -> None:
    from kicad_mcp.tools.export import register as register_export

    server = FastMCP("export-drill-order-test")
    register_export(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [name for name in names if name in {"export_gerber", "export_drill", "export_bom"}]
    assert relevant == ["export_gerber", "export_drill", "export_bom"]
