from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.schematic_layout_inspection import (
    SchematicLayoutInspectionDependencies,
    register,
)


class FakeLayoutInspectionService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def bounding_boxes(self) -> str:
        self.calls.append(("bounding_boxes", ()))
        return "boxes"

    def free_placement(
        self,
        count: int,
        cell_width_mm: float,
        cell_height_mm: float,
        keepout_regions: list[tuple[float, float, float, float]] | None,
    ) -> str:
        self.calls.append(
            (
                "free_placement",
                (count, cell_width_mm, cell_height_mm, keepout_regions),
            )
        )
        return "free"


def _registered() -> tuple[FastMCP, FakeLayoutInspectionService]:
    server = FastMCP("schematic-layout-inspection-test")
    service = FakeLayoutInspectionService()
    register(server, SchematicLayoutInspectionDependencies(service=service))  # type: ignore[arg-type]
    return server, service


def test_registration_preserves_names_descriptions_and_schemas() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {"sch_get_bounding_boxes", "sch_find_free_placement"}
    assert tools["sch_get_bounding_boxes"].description == (
        "Return the estimated bounding box of every symbol in the active schematic.\n\n"
        "Use this before calling sch_add_symbol or sch_build_circuit to understand\n"
        "which areas of the schematic sheet are already occupied.  The bounding boxes\n"
        "are heuristic estimates (KiCad does not expose exact extents via the file API)\n"
        "but are conservative enough to avoid overlap in practice.\n\n"
        "Returns:\n"
        "    A table of all symbols with their centre position and estimated\n"
        "    bounding-box corners (x_min, y_min, x_max, y_max) in mm, plus an\n"
        "    occupied-area summary.\n"
    )
    assert tools["sch_find_free_placement"].description == (
        "Find N collision-free placement coordinates for new symbols.\n\n"
        "Reads the current schematic, builds an occupancy grid from all existing\n"
        "symbols, and returns ``count`` coordinate pairs that do not overlap with\n"
        "any placed symbol.  Call this before sch_add_symbol to get safe (x, y)\n"
        "values.\n\n"
        "Args:\n"
        "    count: Number of free coordinate slots to return (default 1, max 64).\n"
        "    cell_width_mm: Grid cell width in mm (default 25.4 — one 10-mil grid unit).\n"
        "    cell_height_mm: Grid cell height in mm (default 17.78).\n"
        "    keepout_regions: Optional rectangular keepouts as\n"
        "        ``[(x_min, y_min, x_max, y_max), ...]`` in mm.\n\n"
        "Returns:\n"
        "    A list of (x_mm, y_mm) coordinate pairs, one per requested slot.\n"
    )
    assert tools["sch_get_bounding_boxes"].parameters == {
        "properties": {},
        "title": "sch_get_bounding_boxesArguments",
        "type": "object",
    }
    free = tools["sch_find_free_placement"].parameters
    assert free.get("required") is None
    assert free["properties"]["count"]["default"] == 1
    assert free["properties"]["cell_width_mm"]["default"] == 25.4
    assert free["properties"]["cell_height_mm"]["default"] == 17.78
    tuple_schema = free["properties"]["keepout_regions"]["anyOf"][0]["items"]
    assert tuple_schema["minItems"] == 4
    assert tuple_schema["maxItems"] == 4
    assert len(tuple_schema["prefixItems"]) == 4


def test_registration_preserves_headless_metadata() -> None:
    server, _service = _registered()

    for tool in server._tool_manager.list_tools():
        metadata = get_tool_metadata(tool.name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False


def test_registration_delegates_defaults_and_explicit_arguments() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_get_bounding_boxes"].fn() == "boxes"
    assert tools["sch_find_free_placement"].fn() == "free"
    keepouts = [(1.0, 2.0, 3.0, 4.0)]
    assert (
        tools["sch_find_free_placement"].fn(
            count=3,
            cell_width_mm=20.0,
            cell_height_mm=10.0,
            keepout_regions=keepouts,
        )
        == "free"
    )
    assert service.calls == [
        ("bounding_boxes", ()),
        ("free_placement", (1, 25.4, 17.78, None)),
        ("free_placement", (3, 20.0, 10.0, keepouts)),
    ]
