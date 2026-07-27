# pyright: reportPrivateUsage=false

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from kicad_mcp.models.verdict import VerdictReport
from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.pcb_board_inspection import PcbBoardInspectionDependencies, register


class FakeBoardInspectionService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def get_board_summary(self) -> VerdictReport:
        self.calls.append(("summary", None))
        return VerdictReport(text="summary")

    def get_tracks(
        self,
        *,
        page: int = 1,
        page_size: int = 100,
        filter_layer: str = "",
        filter_net: str = "",
    ) -> str:
        self.calls.append(("tracks", (page, page_size, filter_layer, filter_net)))
        return "tracks"

    def get_vias(self) -> str:
        self.calls.append(("vias", None))
        return "vias"

    def get_footprints(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        filter_layer: str = "",
    ) -> str:
        self.calls.append(("footprints", (page, page_size, filter_layer)))
        return "footprints"


def test_registration_preserves_contract_metadata_and_forwarding() -> None:
    server = FastMCP("pcb-board-inspection-test")
    service = FakeBoardInspectionService()
    register(server, PcbBoardInspectionDependencies(service=service))
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
    assert set(tools) == {
        "pcb_get_board_summary",
        "pcb_get_tracks",
        "pcb_get_vias",
        "pcb_get_footprints",
    }
    assert tools["pcb_get_board_summary"].description == "Summarize the current board."
    assert tools["pcb_get_tracks"].description == "List board tracks."
    assert tools["pcb_get_vias"].description == "List board vias."
    assert tools["pcb_get_footprints"].description == "List board footprints."
    assert tools["pcb_get_board_summary"].parameters["properties"] == {}
    assert tools["pcb_get_vias"].parameters["properties"] == {}
    assert tools["pcb_get_tracks"].parameters["properties"] == {
        "page": {"default": 1, "title": "Page", "type": "integer"},
        "page_size": {"default": 100, "title": "Page Size", "type": "integer"},
        "filter_layer": {"default": "", "title": "Filter Layer", "type": "string"},
        "filter_net": {"default": "", "title": "Filter Net", "type": "string"},
    }
    assert tools["pcb_get_footprints"].parameters["properties"] == {
        "page": {"default": 1, "title": "Page", "type": "integer"},
        "page_size": {"default": 50, "title": "Page Size", "type": "integer"},
        "filter_layer": {"default": "", "title": "Filter Layer", "type": "string"},
    }
    summary_schema = tools["pcb_get_board_summary"].output_schema
    assert summary_schema is not None
    assert summary_schema["title"] == "VerdictReport"

    assert tools["pcb_get_board_summary"].fn().text == "summary"
    assert tools["pcb_get_tracks"].fn(2, 25, "F_Cu", "GND") == "tracks"
    assert tools["pcb_get_vias"].fn() == "vias"
    assert tools["pcb_get_footprints"].fn(3, 10, "B_Cu") == "footprints"
    assert service.calls == [
        ("summary", None),
        ("tracks", (2, 25, "F_Cu", "GND")),
        ("vias", None),
        ("footprints", (3, 10, "B_Cu")),
    ]

    for name in tools:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False
