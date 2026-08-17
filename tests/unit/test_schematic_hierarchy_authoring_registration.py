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
        sheet_pins: tuple[tuple[str, str], ...] = (),
    ) -> str:
        self.calls.append(("create_sheet", (name, filename, x_mm, y_mm, snap_to_grid, sheet_pins)))
        return "sheet"

    def move_sheet(self, name: str, x_mm: float, y_mm: float, snap_to_grid: bool) -> str:
        self.calls.append(("move_sheet", (name, x_mm, y_mm, snap_to_grid)))
        return "moved"

    def delete_sheet(self, name: str) -> str:
        self.calls.append(("delete_sheet", (name,)))
        return "deleted"

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

    def add_sheet_pin(
        self,
        sheet: str,
        name: str,
        pin_type: str,
        edge: str,
        position_along_edge: float,
    ) -> str:
        self.calls.append(("add_sheet_pin", (sheet, name, pin_type, edge, position_along_edge)))
        return "pin"

    def import_sheet_pins(self, sheet: str | None, grow_sheet: bool, dry_run: bool) -> str:
        self.calls.append(("import_sheet_pins", (sheet, grow_sheet, dry_run)))
        return "imported"

    def wire_sheet_pins(self, sheet: str | None, stub_mm: float, dry_run: bool) -> str:
        self.calls.append(("wire_sheet_pins", (sheet, stub_mm, dry_run)))
        return "wired"

    def spread_sheets(self, min_gap_mm: float | None, margin_mm: float, dry_run: bool) -> str:
        self.calls.append(("spread_sheets", (min_gap_mm, margin_mm, dry_run)))
        return "spread"


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
        "sch_move_sheet",
        "sch_delete_sheet",
        "sch_add_hierarchical_label",
        "sch_add_global_label",
        "sch_add_sheet_pin",
        "sch_import_sheet_pins",
        "sch_wire_sheet_pins",
        "sch_spread_sheets",
    }
    assert tools["sch_create_sheet"].description == (
        "Create a child schematic sheet and add it to the active top-level schematic.\n\n"
        "Optional ``sheet_pins`` is a list of ``[name, type]`` two-element arrays,\n"
        "laid out by the same rules as ``sch_import_sheet_pins``.\n"
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
    assert tools["sch_create_sheet"].parameters["properties"]["sheet_pins"]["default"] is None
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
        ("create_sheet", ("Power", "power", 10.0, 20.0, True, ())),
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
    with pytest.raises(ValidationError):
        tools["sch_create_sheet"].fn(
            name="Power",
            filename="power",
            x_mm=1.0,
            y_mm=2.0,
            sheet_pins=[("", "input")],
        )
    with pytest.raises(ValidationError):
        tools["sch_create_sheet"].fn(
            name="Power",
            filename="power",
            x_mm=1.0,
            y_mm=2.0,
            sheet_pins=[("VIN", "sideways")],
        )


def test_create_sheet_normalizes_host_supplied_pin_arrays_to_tuples() -> None:
    """A host sends ``[[name, type], ...]``; the service must still see tuples."""
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    tools["sch_create_sheet"].fn(
        name="Power",
        filename="power",
        x_mm=1.0,
        y_mm=2.0,
        sheet_pins=[["VIN", "input"], ["VOUT", "output"]],
    )

    assert service.calls[0][1][5] == (("VIN", "input"), ("VOUT", "output"))


def test_create_sheet_forwards_sheet_pins_as_a_tuple() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert (
        tools["sch_create_sheet"].fn(
            name="Power",
            filename="power",
            x_mm=1.0,
            y_mm=2.0,
            sheet_pins=[("VIN", "input"), ("VOUT", "output")],
        )
        == "sheet"
    )

    assert service.calls == [
        (
            "create_sheet",
            (
                "Power",
                "power",
                1.0,
                2.0,
                True,
                (("VIN", "input"), ("VOUT", "output")),
            ),
        )
    ]


def test_move_and_delete_sheet_tools_are_registered() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert {"sch_move_sheet", "sch_delete_sheet"} <= set(tools)
    assert tools["sch_move_sheet"].parameters["required"] == ["name", "x_mm", "y_mm"]
    assert tools["sch_move_sheet"].parameters["properties"]["snap_to_grid"]["default"] is True
    assert tools["sch_delete_sheet"].parameters["required"] == ["name"]


def test_move_sheet_forwards_its_arguments_verbatim() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert (
        tools["sch_move_sheet"].fn(name="Power", x_mm=10.0, y_mm=20.0, snap_to_grid=False)
        == "moved"
    )

    assert service.calls == [("move_sheet", ("Power", 10.0, 20.0, False))]


def test_move_sheet_defaults_to_snapping() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_move_sheet"].fn(name="Power", x_mm=1.0, y_mm=2.0) == "moved"

    assert service.calls == [("move_sheet", ("Power", 1.0, 2.0, True))]


def test_delete_sheet_forwards_its_name() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_delete_sheet"].fn(name="Power") == "deleted"

    assert service.calls == [("delete_sheet", ("Power",))]


def test_move_and_delete_sheet_reject_an_empty_name() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    with pytest.raises(ValidationError):
        tools["sch_move_sheet"].fn(name="", x_mm=1.0, y_mm=2.0)
    with pytest.raises(ValidationError):
        tools["sch_delete_sheet"].fn(name="")


def test_sheet_pin_tools_are_registered() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert {"sch_add_sheet_pin", "sch_import_sheet_pins"} <= set(tools)


def test_import_sheet_pins_defaults_to_every_sheet_and_growth() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_import_sheet_pins"].fn() == "imported"

    assert service.calls == [("import_sheet_pins", (None, True, False))]


def test_add_sheet_pin_forwards_its_arguments() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert (
        tools["sch_add_sheet_pin"].fn(
            sheet="02_mcu",
            name="VIN",
            pin_type="input",
            edge="left",
            position_along_edge=5.08,
        )
        == "pin"
    )

    assert service.calls == [("add_sheet_pin", ("02_mcu", "VIN", "input", "left", 5.08))]


def test_sheet_pin_input_rejects_an_unknown_type() -> None:
    from kicad_mcp.models.schematic import SheetPinInput

    with pytest.raises(ValidationError):
        SheetPinInput(
            sheet="s", name="n", pin_type="nonsense", edge="left", position_along_edge=0.0
        )


def test_sheet_pin_input_rejects_an_unknown_edge() -> None:
    from kicad_mcp.models.schematic import SheetPinInput

    with pytest.raises(ValidationError):
        SheetPinInput(
            sheet="s", name="n", pin_type="input", edge="sideways", position_along_edge=0.0
        )


def test_wiring_tools_are_registered() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert {"sch_wire_sheet_pins", "sch_spread_sheets"} <= set(tools)


def test_wire_sheet_pins_defaults_to_every_sheet_and_default_stub() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_wire_sheet_pins"].fn() == "wired"

    assert service.calls == [("wire_sheet_pins", (None, 2.54, False))]


def test_wire_sheet_pins_forwards_its_arguments_verbatim() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_wire_sheet_pins"].fn(sheet="02_mcu", stub_mm=5.08, dry_run=True) == "wired"

    assert service.calls == [("wire_sheet_pins", ("02_mcu", 5.08, True))]


def test_wire_sheet_pins_rejects_a_non_positive_stub() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    with pytest.raises(ValidationError):
        tools["sch_wire_sheet_pins"].fn(stub_mm=0.0)
    with pytest.raises(ValidationError):
        tools["sch_wire_sheet_pins"].fn(stub_mm=-2.54)


def test_spread_sheets_defaults_to_auto_gap_and_default_margin() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_spread_sheets"].fn() == "spread"

    assert service.calls == [("spread_sheets", (None, 2.54, False))]


def test_spread_sheets_forwards_its_arguments_verbatim() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_spread_sheets"].fn(min_gap_mm=25.4, margin_mm=5.08, dry_run=True) == "spread"

    assert service.calls == [("spread_sheets", (25.4, 5.08, True))]


def test_spread_sheets_rejects_a_negative_margin() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    with pytest.raises(ValidationError):
        tools["sch_spread_sheets"].fn(margin_mm=-1.0)


def test_spread_sheets_rejects_a_negative_min_gap() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    with pytest.raises(ValidationError):
        tools["sch_spread_sheets"].fn(min_gap_mm=-1.0)
