from __future__ import annotations

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from kicad_mcp.tools.schematic_destructive_edit import (
    SchematicDestructiveEditDependencies,
    register,
)


class FakeDestructiveEditService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def delete_wire(self, wire_id: str) -> str:
        self.calls.append(("delete_wire", (wire_id,)))
        return "wire-deleted"

    def delete_symbol(self, reference: str) -> str:
        self.calls.append(("delete_symbol", (reference,)))
        return "symbol-deleted"

    def delete_label(self, name: str, x_mm: float, y_mm: float) -> str:
        self.calls.append(("delete_label", (name, x_mm, y_mm)))
        return "label-deleted"

    def move_label(
        self,
        name: str,
        x_mm: float,
        y_mm: float,
        new_x_mm: float,
        new_y_mm: float,
        new_rotation: int | None,
        snap_to_grid: bool,
    ) -> str:
        self.calls.append(
            (
                "move_label",
                (name, x_mm, y_mm, new_x_mm, new_y_mm, new_rotation, snap_to_grid),
            )
        )
        return "label-moved"

    def modify_label(
        self,
        name: str,
        x_mm: float,
        y_mm: float,
        justify: str,
    ) -> str:
        self.calls.append(("modify_label", (name, x_mm, y_mm, justify)))
        return "label-modified"


def _registered() -> tuple[FastMCP, FakeDestructiveEditService]:
    server = FastMCP("schematic-destructive-edit-test")
    service = FakeDestructiveEditService()
    register(server, SchematicDestructiveEditDependencies(service=service))
    return server, service


def test_registration_preserves_names_descriptions_and_schemas() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {
        "sch_delete_wire",
        "sch_delete_symbol",
        "sch_delete_label",
        "sch_move_label",
        "sch_modify_label",
    }
    assert tools["sch_delete_wire"].description == (
        "Remove a specific wire segment using its UUID or unique UUID prefix."
    )
    assert tools["sch_delete_symbol"].description == (
        "Remove a placed symbol and any directly attached wire segments."
    )
    assert tools["sch_delete_label"].description == (
        "Delete label(s) (local/global/hierarchical) matching ``name`` at the\n"
        "given coordinate. Use sch_get_labels() to find exact names/positions."
    )
    assert tools["sch_move_label"].description == (
        "Move the label matching ``name`` at (x_mm, y_mm) to a new coordinate,\n"
        "optionally re-rotating it. snap_to_grid defaults to False so the anchor\n"
        "can land exactly on a pin/wire endpoint."
    )
    assert tools["sch_modify_label"].description == (
        "Set the text justification of an existing label (local/global/\n"
        "hierarchical) matching ``name`` at (x_mm, y_mm). Use sch_get_labels()\n"
        "to find exact names/positions.\n\n"
        "Global and hierarchical labels carry a directional icon at their\n"
        "anchor; KiCad centers unjustified text on that anchor, which overlaps\n"
        'the icon. Pass "left", "right", "top", "bottom", or a combination like\n'
        '"left top" to move the text clear of the icon, or "none" to restore\n'
        "KiCad's centered default.\n"
    )
    assert tools["sch_delete_wire"].parameters["required"] == ["wire_id"]
    assert tools["sch_delete_symbol"].parameters["required"] == ["reference"]
    assert tools["sch_delete_label"].parameters["required"] == ["name", "x_mm", "y_mm"]
    assert tools["sch_move_label"].parameters["required"] == [
        "name",
        "x_mm",
        "y_mm",
        "new_x_mm",
        "new_y_mm",
    ]
    assert tools["sch_move_label"].parameters["properties"]["new_rotation"]["default"] is None
    assert tools["sch_move_label"].parameters["properties"]["snap_to_grid"]["default"] is False
    assert tools["sch_modify_label"].parameters["required"] == [
        "name",
        "x_mm",
        "y_mm",
        "justify",
    ]


def test_registration_delegates_exact_arguments() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_delete_wire"].fn("abc") == "wire-deleted"
    assert tools["sch_delete_symbol"].fn("R1") == "symbol-deleted"
    assert tools["sch_delete_label"].fn("VCC", 1.0, 2.0) == "label-deleted"
    assert tools["sch_move_label"].fn("VCC", 1.0, 2.0, 3.0, 4.0, 90, True) == ("label-moved")
    assert tools["sch_modify_label"].fn("VCC", 3.0, 4.0, "left top") == ("label-modified")
    assert service.calls == [
        ("delete_wire", ("abc",)),
        ("delete_symbol", ("R1",)),
        ("delete_label", ("VCC", 1.0, 2.0)),
        ("move_label", ("VCC", 1.0, 2.0, 3.0, 4.0, 90, True)),
        ("modify_label", ("VCC", 3.0, 4.0, "left top")),
    ]


def test_registration_preserves_pydantic_validation() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    with pytest.raises(ValidationError):
        tools["sch_delete_wire"].fn("")
    with pytest.raises(ValidationError):
        tools["sch_delete_symbol"].fn("")
    with pytest.raises(ValidationError):
        tools["sch_modify_label"].fn("VCC", 1.0, 2.0, "diagonal")
