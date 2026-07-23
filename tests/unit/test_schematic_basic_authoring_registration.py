from __future__ import annotations

from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from pydantic import ValidationError

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.schematic_basic_authoring import (
    SchematicBasicAuthoringDependencies,
    register,
)


class FakeBasicAuthoringService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def add_symbol(
        self,
        library: str,
        symbol_name: str,
        x_mm: float,
        y_mm: float,
        reference: str,
        value: str,
        footprint: str,
        rotation: int,
        snap_to_grid: bool,
        unit: int,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        args = (
            library,
            symbol_name,
            x_mm,
            y_mm,
            reference,
            value,
            footprint,
            rotation,
            snap_to_grid,
            unit,
            sheet,
            sheet_file,
        )
        self.calls.append(("add_symbol", args))
        return "symbol"

    def add_wire(
        self,
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        snap_to_grid: bool,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        args = (x1_mm, y1_mm, x2_mm, y2_mm, snap_to_grid, sheet, sheet_file)
        self.calls.append(("add_wire", args))
        return "wire"

    def add_label(
        self,
        name: str,
        x_mm: float,
        y_mm: float,
        rotation: int,
        snap_to_grid: bool,
        justify: str | None,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        args = (name, x_mm, y_mm, rotation, snap_to_grid, justify, sheet, sheet_file)
        self.calls.append(("add_label", args))
        return "label"

    def add_power_symbol(
        self,
        name: str,
        x_mm: float,
        y_mm: float,
        rotation: int,
        snap_to_grid: bool,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        args = (name, x_mm, y_mm, rotation, snap_to_grid, sheet, sheet_file)
        self.calls.append(("add_power_symbol", args))
        return "power"

    def add_bus(
        self,
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        snap_to_grid: bool,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        args = (x1_mm, y1_mm, x2_mm, y2_mm, snap_to_grid, sheet, sheet_file)
        self.calls.append(("add_bus", args))
        return "bus"

    def add_bus_wire_entry(
        self,
        x_mm: float,
        y_mm: float,
        direction: str,
        snap_to_grid: bool,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        args = (x_mm, y_mm, direction, snap_to_grid, sheet, sheet_file)
        self.calls.append(("add_bus_wire_entry", args))
        return "bus-entry"

    def add_no_connect(
        self,
        x_mm: float,
        y_mm: float,
        snap_to_grid: bool,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        args = (x_mm, y_mm, snap_to_grid, sheet, sheet_file)
        self.calls.append(("add_no_connect", args))
        return "no-connect"


def _registered() -> tuple[FastMCP, FakeBasicAuthoringService]:
    server = FastMCP("schematic-basic-authoring-test")
    service = FakeBasicAuthoringService()
    register(server, SchematicBasicAuthoringDependencies(service=service))
    return server, service


def test_registration_preserves_names_descriptions_and_schema_defaults() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {
        "sch_add_symbol",
        "sch_add_component",
        "sch_add_wire",
        "sch_add_label",
        "sch_add_power_symbol",
        "sch_add_bus",
        "sch_add_bus_wire_entry",
        "sch_add_no_connect",
    }
    assert tools["sch_add_symbol"].description == (
        "Add a schematic symbol at an absolute coordinate.\n\n"
        "Coordinates snap to the 1.27 mm / 50 mil schematic grid by default; set\n"
        "snap_to_grid=False only when an exact off-grid coordinate is intentional."
    )
    assert tools["sch_add_component"].description == (
        "Add a schematic component through the hybrid IPC reload path."
    )
    assert tools["sch_add_wire"].description == (
        "Add a schematic wire, snapping endpoints to the 1.27 mm / 50 mil grid by default."
    )
    assert tools["sch_add_label"].description == (
        "Add a schematic label, snapping its anchor to the 1.27 mm / 50 mil grid by default.\n\n"
        '``justify`` overrides KiCad\'s centered default (e.g. "left", "right",\n'
        '"top", "bottom", "left top"); local labels have no directional icon so\n'
        "centered text is usually correct and this is rarely needed."
    )
    assert tools["sch_add_power_symbol"].description == (
        "Add a power symbol, snapping its anchor to the 1.27 mm / 50 mil grid by default."
    )
    assert tools["sch_add_bus"].description == (
        "Add a schematic bus, snapping endpoints to the 1.27 mm / 50 mil grid by default."
    )
    assert tools["sch_add_bus_wire_entry"].description == (
        "Add a bus wire entry marker.\n\nSnaps its anchor to the 1.27 mm / 50 mil grid by default."
    )
    assert tools["sch_add_no_connect"].description == (
        "Add a no-connect marker, snapping it to the 1.27 mm / 50 mil grid by default."
    )
    assert tools["sch_add_symbol"].parameters["required"] == [
        "library",
        "symbol_name",
        "x_mm",
        "y_mm",
        "reference",
        "value",
    ]
    assert tools["sch_add_symbol"].parameters["properties"]["footprint"]["default"] == ""
    assert tools["sch_add_symbol"].parameters["properties"]["rotation"]["default"] == 0
    assert tools["sch_add_symbol"].parameters["properties"]["snap_to_grid"]["default"] is True
    assert tools["sch_add_symbol"].parameters["properties"]["unit"]["default"] == 1
    assert tools["sch_add_label"].parameters.get("required") is None
    assert tools["sch_add_label"].parameters["properties"]["name"]["default"] is None
    assert tools["sch_add_label"].parameters["properties"]["text"]["default"] is None
    assert tools["sch_add_power_symbol"].parameters["required"] == ["name", "x_mm", "y_mm"]
    assert tools["sch_add_bus"].parameters["required"] == [
        "x1_mm",
        "y1_mm",
        "x2_mm",
        "y2_mm",
    ]
    assert tools["sch_add_bus"].parameters["properties"]["snap_to_grid"]["default"] is True
    assert tools["sch_add_bus_wire_entry"].parameters["required"] == ["x_mm", "y_mm"]
    assert tools["sch_add_bus_wire_entry"].parameters["properties"]["direction"]["default"] == (
        "up_right"
    )
    assert tools["sch_add_no_connect"].parameters["required"] == ["x_mm", "y_mm"]


def test_registration_preserves_headless_metadata() -> None:
    _server, _service = _registered()

    assert get_tool_metadata("sch_add_symbol") is not None
    assert get_tool_metadata("sch_add_symbol").headless_compatible is True  # type: ignore[union-attr]
    assert get_tool_metadata("sch_add_component") is not None
    assert get_tool_metadata("sch_add_component").headless_compatible is True  # type: ignore[union-attr]
    assert get_tool_metadata("sch_add_wire") is None
    assert get_tool_metadata("sch_add_label") is None
    assert get_tool_metadata("sch_add_power_symbol") is None
    assert get_tool_metadata("sch_add_bus") is None
    assert get_tool_metadata("sch_add_bus_wire_entry") is None
    assert get_tool_metadata("sch_add_no_connect") is None


def test_registration_delegates_symbol_and_component_with_defaults() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    kwargs = {
        "library": "Device",
        "symbol_name": "R",
        "x_mm": 10.0,
        "y_mm": 20.0,
        "reference": "R1",
        "value": "10k",
    }
    assert tools["sch_add_symbol"].fn(**kwargs) == "symbol"
    assert tools["sch_add_component"].fn(**kwargs) == "symbol"
    expected = (
        "Device",
        "R",
        10.0,
        20.0,
        "R1",
        "10k",
        "",
        0,
        True,
        1,
        None,
        None,
    )
    assert service.calls == [("add_symbol", expected), ("add_symbol", expected)]


def test_registration_delegates_wire_label_alias_and_power_symbol() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert (
        tools["sch_add_wire"].fn(
            x1_mm=1.0,
            y1_mm=2.0,
            x2_mm=3.0,
            y2_mm=4.0,
            snap_to_grid=False,
            sheet="Power",
            sheet_file=None,
        )
        == "wire"
    )
    assert (
        tools["sch_add_label"].fn(
            name=None,
            text="VCC",
            x_mm=5.0,
            y_mm=6.0,
            rotation=90,
            snap_to_grid=False,
            justify="left",
            sheet=None,
            sheet_file="child.kicad_sch",
        )
        == "label"
    )
    assert (
        tools["sch_add_power_symbol"].fn(
            name="VCC",
            x_mm=7.0,
            y_mm=8.0,
            rotation=180,
            snap_to_grid=True,
            sheet=None,
            sheet_file=None,
        )
        == "power"
    )
    assert service.calls == [
        ("add_wire", (1.0, 2.0, 3.0, 4.0, False, "Power", None)),
        ("add_label", ("VCC", 5.0, 6.0, 90, False, "left", None, "child.kicad_sch")),
        ("add_power_symbol", ("VCC", 7.0, 8.0, 180, True, None, None)),
    ]


def test_registration_preserves_label_missing_value_and_pydantic_validation() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    with pytest.raises(ValueError, match="Either name or text parameter is required"):
        tools["sch_add_label"].fn()
    with pytest.raises(ValidationError):
        tools["sch_add_symbol"].fn(
            library="",
            symbol_name="R",
            x_mm=1.0,
            y_mm=2.0,
            reference="R1",
            value="10k",
        )


def test_registration_delegates_connectivity_primitives_and_defaults() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert (
        tools["sch_add_bus"].fn(
            x1_mm=1.0,
            y1_mm=2.0,
            x2_mm=3.0,
            y2_mm=4.0,
            sheet="Signals",
        )
        == "bus"
    )
    assert (
        tools["sch_add_bus_wire_entry"].fn(
            x_mm=5.0,
            y_mm=6.0,
            direction="down_left",
            snap_to_grid=False,
            sheet_file="child.kicad_sch",
        )
        == "bus-entry"
    )
    assert tools["sch_add_no_connect"].fn(x_mm=7.0, y_mm=8.0) == "no-connect"
    assert service.calls == [
        ("add_bus", (1.0, 2.0, 3.0, 4.0, True, "Signals", None)),
        (
            "add_bus_wire_entry",
            (5.0, 6.0, "down_left", False, None, "child.kicad_sch"),
        ),
        ("add_no_connect", (7.0, 8.0, True, None, None)),
    ]


def test_registration_preserves_bus_entry_direction_validation() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    with pytest.raises(ValidationError):
        tools["sch_add_bus_wire_entry"].fn(
            x_mm=1.0,
            y_mm=2.0,
            direction="sideways",
        )
