from __future__ import annotations

import importlib
import importlib.util
import inspect
from pathlib import Path
from types import ModuleType

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.routing_net_class_rules")
    assert spec is not None
    return importlib.import_module("kicad_mcp.tools.routing_net_class_rules")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def set_rules(
        self,
        net_class: str,
        width_mm: float,
        clearance_mm: float,
        via_diameter_mm: float,
        via_drill_mm: float,
    ) -> str:
        self.calls.append((net_class, width_mm, clearance_mm, via_diameter_mm, via_drill_mm))
        return "delegated"


def test_dependency_factory_wires_rule_writer() -> None:
    adapter = _adapter()
    calls: list[tuple[str, str]] = []
    deps = adapter.dependencies(
        lambda name, body: calls.append((name, body)) or Path("demo.kicad_dru")
    )

    result = deps.service.set_rules("high_speed", 0.18, 0.15, 0.45, 0.2)

    assert calls
    assert calls[0][0] == "Net class high_speed"
    assert "demo.kicad_dru" in result


def test_registration_preserves_signature_metadata_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("routing-net-class-rules-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.RoutingNetClassRuleDependencies(service=service),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["route_set_net_class_rules"]

    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(net_class: 'str', width_mm: 'float', clearance_mm: 'float', "
        "via_diameter_mm: 'float', via_drill_mm: 'float') -> 'str'"
    )
    assert "Write net-class routing constraints" in (tool.fn.__doc__ or "")
    metadata = get_tool_metadata("route_set_net_class_rules")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False

    assert tool.fn("high_speed", 0.18, 0.15, 0.45, 0.2) == "delegated"
    assert service.calls == [("high_speed", 0.18, 0.15, 0.45, 0.2)]
