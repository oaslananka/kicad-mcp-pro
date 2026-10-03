from __future__ import annotations

import importlib
import importlib.util
from types import ModuleType

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.manufacturing_panelization")
    assert spec is not None, "Panelization adapter module must be extracted"
    return importlib.import_module("kicad_mcp.tools.manufacturing_panelization")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def panelize(self, **kwargs: object) -> str:
        self.calls.append(dict(kwargs))
        return "panelized"


def test_registration_preserves_public_tool_contract_and_delegates() -> None:
    adapter = _adapter()
    server = FastMCP("manufacturing-panelization-registration")
    service = FakeService()

    adapter.register(server, adapter.ManufacturingPanelizationDependencies(service=service))

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["mfg_panelize"]
    tool = tools[0]
    assert list(tool.parameters["properties"]) == [
        "layout",
        "rows",
        "cols",
        "spacing_mm",
        "frame_width_mm",
        "output_path",
        "dry_run",
        "confirm",
    ]
    assert tool.parameters["properties"]["layout"]["default"] == "grid"
    assert tool.parameters["properties"]["rows"]["default"] == 2
    assert tool.parameters["properties"]["dry_run"]["default"] is True
    metadata = get_tool_metadata("mfg_panelize")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False

    result = tool.fn(
        layout="vcut",
        rows=3,
        cols=4,
        spacing_mm=1.0,
        frame_width_mm=7.0,
        output_path="panel/custom.kicad_pcb",
        dry_run=False,
        confirm=True,
    )
    assert result == "panelized"
    assert service.calls == [
        {
            "layout": "vcut",
            "rows": 3,
            "cols": 4,
            "spacing_mm": 1.0,
            "frame_width_mm": 7.0,
            "output_path": "panel/custom.kicad_pcb",
            "dry_run": False,
            "confirm": True,
        }
    ]
