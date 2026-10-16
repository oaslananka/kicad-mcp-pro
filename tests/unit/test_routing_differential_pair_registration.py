from __future__ import annotations

import importlib
import importlib.util
import inspect
from pathlib import Path
from types import ModuleType

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.routing_differential_pair")
    assert spec is not None
    return importlib.import_module("kicad_mcp.tools.routing_differential_pair")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def set_pair(
        self,
        net_p: str,
        net_n: str,
        layer: str = "F_Cu",
        width_mm: float = 0.2,
        gap_mm: float = 0.2,
        length_tolerance_mm: float = 0.1,
    ) -> str:
        self.calls.append((net_p, net_n, layer, width_mm, gap_mm, length_tolerance_mm))
        return "delegated"


def test_dependency_factory_wires_late_bound_callbacks() -> None:
    adapter = _adapter()
    net_calls: list[str] = []
    write_calls: list[tuple[str, str]] = []
    deps = adapter.dependencies(
        list_board_net_names=lambda: net_calls.append("nets") or {"USB_DP", "USB_DN"},
        write_rule=lambda name, body: write_calls.append((name, body)) or Path("demo.kicad_dru"),
    )
    result = deps.service.set_pair("USB_DP", "USB_DN")
    assert net_calls == ["nets"]
    assert write_calls
    assert write_calls[0][0] == "Differential pair USB_DP USB_DN"
    assert "demo.kicad_dru" in result


def test_registration_preserves_signature_metadata_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("routing-differential-pair-registration")
    service = FakeService()
    adapter.register(server, adapter.RoutingDifferentialPairDependencies(service=service))
    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["route_differential_pair"]
    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(net_p: 'str', net_n: 'str', layer: 'str' = 'F_Cu', "
        "width_mm: 'float' = 0.2, gap_mm: 'float' = 0.2, "
        "length_tolerance_mm: 'float' = 0.1) -> 'str'"
    )
    assert "Write differential-pair routing constraints" in (tool.fn.__doc__ or "")
    metadata = get_tool_metadata("route_differential_pair")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False
    assert tool.fn("USB_DP", "USB_DN", "B_Cu", 0.16, 0.18, 0.12) == "delegated"
    assert service.calls == [("USB_DP", "USB_DN", "B_Cu", 0.16, 0.18, 0.12)]
