# pyright: reportPrivateUsage=false

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.pcb_origin_management import PcbOriginDependencies, register


class FakeOriginService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[float, ...]]] = []

    def set_origin(self, x_mm: float, y_mm: float) -> str:
        self.calls.append(("set_origin", (x_mm, y_mm)))
        return "set"

    def get_origin(self) -> str:
        self.calls.append(("get_origin", ()))
        return "get"


def _registered() -> tuple[FastMCP, FakeOriginService]:
    server = FastMCP("pcb-origin-management-test")
    service = FakeOriginService()
    register(server, PcbOriginDependencies(service=service))
    return server, service


def test_registration_preserves_exact_names_and_schemas() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {"pcb_set_origin", "pcb_get_origin"}
    assert tools["pcb_set_origin"].parameters == {
        "properties": {
            "x_mm": {"title": "X Mm", "type": "number"},
            "y_mm": {"title": "Y Mm", "type": "number"},
        },
        "required": ["x_mm", "y_mm"],
        "title": "pcb_set_originArguments",
        "type": "object",
    }
    assert tools["pcb_get_origin"].parameters["properties"] == {}
    assert "required" not in tools["pcb_get_origin"].parameters


def test_registration_preserves_descriptions_metadata_and_forwarding() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["pcb_set_origin"].description.startswith(
        "Set the board origin (drill origin) in millimeters."
    )
    assert tools["pcb_get_origin"].description.startswith(
        "Get the current board origin (drill origin) in millimeters."
    )
    assert tools["pcb_set_origin"].fn(1.25, -2.5) == "set"
    assert tools["pcb_get_origin"].fn() == "get"
    assert service.calls == [("set_origin", (1.25, -2.5)), ("get_origin", ())]

    set_metadata = get_tool_metadata("pcb_set_origin")
    get_metadata = get_tool_metadata("pcb_get_origin")
    assert set_metadata is not None
    assert set_metadata.requires_kicad_running is True
    assert set_metadata.headless_compatible is False
    assert get_metadata is not None
    assert get_metadata.headless_compatible is True
    assert get_metadata.requires_kicad_running is False
