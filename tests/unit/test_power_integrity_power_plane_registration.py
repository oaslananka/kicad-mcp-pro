from __future__ import annotations

import importlib
import inspect
from typing import Any, cast

from mcp.server.mcpserver import MCPServer as FastMCP

from kicad_mcp.models.power_integrity import PowerPlaneInput


class FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[PowerPlaneInput, object]] = []

    def generate(self, payload: PowerPlaneInput, backend: object) -> str:
        self.calls.append((payload, backend))
        return "power-plane-result"


def test_registration_preserves_signature_docstring_and_delegation() -> None:
    adapter = importlib.import_module("kicad_mcp.tools.power_integrity_power_plane")
    server = FastMCP("pi-power-plane-registration")
    service = FakeService()
    backend = object()
    adapter.register(
        server,
        cast(Any, service),
        backend_factory=lambda: cast(Any, backend),
    )

    tools = server._tool_manager.list_tools()
    assert [tool.name for tool in tools] == ["pdn_generate_power_plane"]
    tool = tools[0]
    assert str(inspect.signature(tool.fn)) == (
        "(net_name: 'str', layer: 'str', clearance_mm: 'float' = 0.5) -> 'str'"
    )
    assert tool.fn.__doc__ == "Generate a rectangular copper plane on the requested copper layer."

    assert tool.fn("3V3", "F_Cu") == "power-plane-result"
    assert len(service.calls) == 1
    payload, used_backend = service.calls[0]
    assert payload.net_name == "3V3"
    assert payload.layer == "F_Cu"
    assert payload.clearance_mm == 0.5
    assert used_backend is backend
