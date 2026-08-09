from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.export_netlist import ExportNetlistDependencies, register
from kicad_mcp.tools.metadata import get_tool_metadata


class FakeNetlistService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def export(self, format_name: str = "kicad") -> str:
        self.calls.append(format_name)
        return f"raw:{format_name}"


def _registered() -> tuple[FastMCP, FakeNetlistService]:
    server = FastMCP("export-netlist-test")
    service = FakeNetlistService()
    register(
        server,
        ExportNetlistDependencies(
            service=service,
            add_low_level_notice=lambda value: f"notice::{value}",
        ),
    )
    return server, service


def test_registration_preserves_exact_names_schemas_and_descriptions() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert list(tools) == ["export_netlist", "export_spice_netlist"]
    assert tools["export_netlist"].description == "Export a KiCad schematic netlist."
    assert tools["export_netlist"].parameters == {
        "properties": {"format": {"default": "kicad", "title": "Format", "type": "string"}},
        "title": "export_netlistArguments",
        "type": "object",
    }
    assert tools["export_spice_netlist"].description == "Export a SPICE netlist."
    assert tools["export_spice_netlist"].parameters == {
        "properties": {},
        "title": "export_spice_netlistArguments",
        "type": "object",
    }


def test_registration_preserves_metadata_notice_and_delegation() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["export_netlist"].fn("cadstar") == "notice::raw:cadstar"
    assert tools["export_spice_netlist"].fn() == "notice::raw:spice"
    assert service.calls == ["cadstar", "spice"]
    for name in ("export_netlist", "export_spice_netlist"):
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False


def test_export_composition_root_preserves_netlist_registration_order() -> None:
    from kicad_mcp.tools.export import register as register_export

    server = FastMCP("export-netlist-order-test")
    register_export(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [
        name
        for name in names
        if name in {"export_bom", "export_netlist", "export_spice_netlist", "export_pcb_pdf"}
    ]
    assert relevant == ["export_bom", "export_netlist", "export_spice_netlist", "export_pcb_pdf"]
