from __future__ import annotations

import importlib
import importlib.util
import inspect
from types import ModuleType

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata


def _adapter() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.tools.routing_time_domain_tuning")
    assert spec is not None
    return importlib.import_module("kicad_mcp.tools.routing_time_domain_tuning")


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def tune(
        self,
        net_or_group: str,
        target_delay_ps: float,
        tolerance_ps: float = 10.0,
        layer: str | None = None,
    ) -> str:
        self.calls.append((net_or_group, target_delay_ps, tolerance_ps, layer))
        return "delegated"


def test_registration_preserves_signature_metadata_and_delegation() -> None:
    adapter = _adapter()
    server = FastMCP("routing-time-domain-registration")
    service = FakeService()

    adapter.register(
        server,
        adapter.RoutingTimeDomainTuningDependencies(service=service),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["route_tune_time_domain"]

    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(net_or_group: 'str', target_delay_ps: 'float', "
        "tolerance_ps: 'float' = 10.0, layer: 'str | None' = None) -> 'str'"
    )
    assert "one concrete net; wildcards are rejected" in (tool.fn.__doc__ or "")
    metadata = get_tool_metadata("route_tune_time_domain")
    assert metadata is not None
    assert metadata.headless_compatible is True
    assert metadata.requires_kicad_running is False

    assert tool.fn("USB_D+", 120.0, 8.0, "F.Cu") == "delegated"
    assert service.calls == [("USB_D+", 120.0, 8.0, "F.Cu")]
