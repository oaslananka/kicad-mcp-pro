from __future__ import annotations

from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.schematic_hierarchy_authoring import (
    SchematicHierarchyAuthoringDependencies,
    register,
)


class FakeHierarchyAuthoringService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def create_sheet(
        self,
        name: str,
        filename: str,
        x_mm: float,
        y_mm: float,
        snap_to_grid: bool,
    ) -> str:
        self.calls.append(("create_sheet", (name, filename, x_mm, y_mm, snap_to_grid)))
        return "sheet"

    def add_hierarchical_label(
        self,
        text: str,
        x_mm: float,
        y_mm: float,
        shape: str,
        rotation: int,
        snap_to_grid: bool,
        justify: str | None,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        self.calls.append(
            (
                "add_hierarchical_label",
                (text, x_mm, y_mm, shape, rotation, snap_to_grid, justify, sheet, sheet_file),
            )
        )
        return "hierarchical"

    def add_global_label(
        self,
        text: str,
        x_mm: float,
        y_mm: float,
        shape: str,
        rotation: int,
        snap_to_grid: bool,
        justify: str | None,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        self.calls.append(
            (
                "add_global_label",
                (text, x_mm, y_mm, shape, rotation, snap_to_grid, justify, sheet, sheet_file),
            )
        )
        return "global"


def _registered() -> tuple[FastMCP, FakeHierarchyAuthoringService]:
    server = FastMCP("schematic-hierarchy-authoring-test")
    service = FakeHierarchyAuthoringService()
    register(server, SchematicHierarchyAuthoringDependencies(service=service))  # type: ignore[arg-type]
    return server, service


def test_registration_preserves_names_descriptions_and_defaults() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {
        "sch_create_sheet",
        "sch_add_hierarchical_label",
        "sch_add_global_label",
    }
    assert tools["sch_create_sheet"].description == (
        "Create a child schematic sheet and add it to the active top-level schematic."
    )
    label_description = (
        "Add a {kind} label, preserving the requested shape and rotation.\n\n"
        "By default the text is justified away from the directional icon based\n"
        "on ``rotation`` (0=left, 90=bottom, 180=right, 270=top) so it doesn't\n"
        'render on top of the icon. Pass ``justify`` to override, or "none" to\n'
        "force KiCad's centered default.\n"
    )
    assert tools["sch_add_hierarchical_label"].description == label_description.format(
        kind="hierarchical"
    )
    assert tools["sch_add_global_label"].description == label_description.format(kind="global")

    assert tools["sch_create_sheet"].parameters["required"] == [
        "name",
        "filename",
        "x_mm",
        "y_mm",
    ]
    assert tools["sch_create_sheet"].parameters["properties"]["snap_to_grid"]["default"] is True
    for name, shape in (
        ("sch_add_hierarchical_label", "input"),
        ("sch_add_global_label", "bidirectional"),
    ):
        parameters = tools[name].parameters
        assert parameters.get("required") is None
        assert parameters["properties"]["text"]["default"] is None
        assert parameters["properties"]["name"]["default"] is None
        assert parameters["properties"]["x_mm"]["default"] == 0.0
        assert parameters["properties"]["y_mm"]["default"] == 0.0
        assert parameters["properties"]["shape"]["default"] == shape
        assert parameters["properties"]["rotation"]["default"] == 0
        assert parameters["properties"]["snap_to_grid"]["default"] is True
        assert parameters["properties"]["justify"]["default"] is None
        assert parameters["properties"]["sheet"]["default"] is None
        assert parameters["properties"]["sheet_file"]["default"] is None


def test_registration_preserves_no_headless_metadata() -> None:
    server, _service = _registered()
    for tool in server._tool_manager.list_tools():
        assert get_tool_metadata(tool.name) is None


def test_registration_delegates_sheet_and_label_aliases() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert (
        tools["sch_create_sheet"].fn(
            name="Power",
            filename="power",
            x_mm=10.0,
            y_mm=20.0,
        )
        == "sheet"
    )
    assert (
        tools["sch_add_hierarchical_label"].fn(
            name="OUT",
            x_mm=1.0,
            y_mm=2.0,
            shape="output",
            rotation=90,
            snap_to_grid=False,
            justify="left",
            sheet="Power",
        )
        == "hierarchical"
    )
    assert (
        tools["sch_add_global_label"].fn(
            text="VCC",
            x_mm=3.0,
            y_mm=4.0,
            shape="passive",
            rotation=180,
            sheet_file="child.kicad_sch",
        )
        == "global"
    )

    assert service.calls == [
        ("create_sheet", ("Power", "power", 10.0, 20.0, True)),
        (
            "add_hierarchical_label",
            ("OUT", 1.0, 2.0, "output", 90, False, "left", "Power", None),
        ),
        (
            "add_global_label",
            ("VCC", 3.0, 4.0, "passive", 180, True, None, None, "child.kicad_sch"),
        ),
    ]


def test_registration_preserves_missing_label_and_pydantic_validation() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    with pytest.raises(ValueError, match="Either text or name parameter is required"):
        tools["sch_add_hierarchical_label"].fn()
    with pytest.raises(ValueError, match="Either text or name parameter is required"):
        tools["sch_add_global_label"].fn()
    with pytest.raises(ValidationError):
        tools["sch_create_sheet"].fn(name="", filename="power", x_mm=1.0, y_mm=2.0)
    with pytest.raises(ValidationError):
        tools["sch_add_global_label"].fn(text="VCC", shape="sideways")
