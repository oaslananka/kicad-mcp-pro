# pyright: reportPrivateUsage=false
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.pcb_file_inspection import (
    PcbFileInspectionDependencies,
    register,
)


class FakeFileInspectionService:
    def footprint_layers_for(self, reference: str) -> str:
        return f"layers:{reference}"

    def visual_qa(self) -> str:
        return "visual-qa"


def _registered() -> FastMCP:
    server = FastMCP("pcb-file-inspection-test")
    register(
        server,
        PcbFileInspectionDependencies(service=FakeFileInspectionService()),
    )
    return server


def test_registration_preserves_exact_public_names_and_schemas() -> None:
    tools = {tool.name: tool for tool in _registered()._tool_manager.list_tools()}

    assert set(tools) == {"pcb_get_footprint_layers", "pcb_visual_qa"}
    assert tools["pcb_get_footprint_layers"].parameters["required"] == ["reference"]
    assert tools["pcb_get_footprint_layers"].parameters["properties"] == {
        "reference": {"title": "Reference", "type": "string"}
    }
    assert tools["pcb_visual_qa"].parameters["properties"] == {}


def test_registration_preserves_headless_metadata_and_forwarding() -> None:
    tools = {tool.name: tool for tool in _registered()._tool_manager.list_tools()}

    assert tools["pcb_get_footprint_layers"].fn(reference="R1") == "layers:R1"
    assert tools["pcb_visual_qa"].fn() == "visual-qa"
    for name in tools:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
