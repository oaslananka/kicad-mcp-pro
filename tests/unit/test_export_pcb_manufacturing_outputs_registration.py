from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.export_pcb_manufacturing_outputs")
    assert spec is not None, "PCB manufacturing outputs adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.export_pcb_manufacturing_outputs")


class FakePcbManufacturingOutputsService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object]] = []

    def export_pick_and_place(self, format: str = "csv", variant_name: str | None = None) -> str:
        self.calls.append(("pick", format, variant_name))
        return f"raw:pick:{format}:{variant_name}"

    def export_ipc2581(self, variant_name: str | None = None) -> str:
        self.calls.append(("ipc2581", variant_name, None))
        return f"raw:ipc2581:{variant_name}"

    def export_odb(self, variant_name: str | None = None) -> str:
        self.calls.append(("odb", variant_name, None))
        return f"raw:odb:{variant_name}"


def _registered() -> tuple[FastMCP, FakePcbManufacturingOutputsService]:
    adapter = _adapter()
    server = FastMCP("export-pcb-manufacturing-outputs-test")
    service = FakePcbManufacturingOutputsService()
    adapter.register(
        server,
        adapter.ExportPcbManufacturingOutputsDependencies(
            service=service,
            add_low_level_notice=lambda value: f"notice::{value}",
        ),
    )
    return server, service


def test_registration_preserves_exact_names_schemas_descriptions_and_metadata() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert list(tools) == ["export_pick_and_place", "export_ipc2581", "export_odb"]
    assert tools["export_pick_and_place"].description == (
        "Export pick and place (CPL) data for the active PCB.\n\n"
        "Parameters\n----------\n"
        "format : str\n"
        "    Output format (e.g. ``csv``, ``ascii``).\n"
        "variant : str | None\n"
        "    Optional design variant name. When set, exports variant-specific\n"
        "    pick-and-place data (component population, value, footprint\n"
        "    overrides). Uses the active variant when omitted.\n"
    )
    assert tools["export_ipc2581"].description == "Export the active PCB to IPC-2581 format."
    assert tools["export_odb"].description == "Export the active PCB to ODB++ format."
    assert tools["export_pick_and_place"].parameters == {
        "properties": {
            "format": {"default": "csv", "title": "Format", "type": "string"},
            "variant": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
                "default": None,
                "title": "Variant",
            },
        },
        "title": "export_pick_and_placeArguments",
        "type": "object",
    }
    assert tools["export_ipc2581"].parameters == {
        "properties": {},
        "title": "export_ipc2581Arguments",
        "type": "object",
    }
    assert tools["export_odb"].parameters == {
        "properties": {},
        "title": "export_odbArguments",
        "type": "object",
    }
    for name in tools:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False


def test_registration_preserves_notice_defaults_and_public_delegation() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["export_pick_and_place"].fn() == "notice::raw:pick:csv:None"
    assert tools["export_pick_and_place"].fn("ascii", "lite") == "notice::raw:pick:ascii:lite"
    assert tools["export_ipc2581"].fn() == "notice::raw:ipc2581:None"
    assert tools["export_odb"].fn() == "notice::raw:odb:None"
    assert service.calls == [
        ("pick", "csv", None),
        ("pick", "ascii", "lite"),
        ("ipc2581", None, None),
        ("odb", None, None),
    ]


def test_export_composition_root_preserves_manufacturing_output_registration_order() -> None:
    from kicad_mcp.tools.export import register as register_export

    server = FastMCP("export-pcb-manufacturing-order-test")
    register_export(server)
    names = [tool.name for tool in server._tool_manager.list_tools()]
    relevant = [
        name
        for name in names
        if name
        in {
            "export_3d_render",
            "export_pick_and_place",
            "export_ipc2581",
            "export_odb",
            "export_svg",
        }
    ]
    assert relevant == [
        "export_3d_render",
        "export_pick_and_place",
        "export_ipc2581",
        "export_odb",
        "export_svg",
    ]
