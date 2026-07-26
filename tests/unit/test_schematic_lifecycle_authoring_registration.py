# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.schematic_lifecycle_authoring import (
    SchematicLifecycleAuthoringDependencies,
    register,
)


class FakeLifecycleService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def add_jumper(
        self,
        x_mm: float,
        y_mm: float,
        pins: int = 2,
        open_by_default: bool = True,
        snap_to_grid: bool = True,
    ) -> str:
        self.calls.append(
            (
                "add_jumper",
                {
                    "x_mm": x_mm,
                    "y_mm": y_mm,
                    "pins": pins,
                    "open_by_default": open_by_default,
                    "snap_to_grid": snap_to_grid,
                },
            )
        )
        return "jumper"

    def annotate(self, start_number: int = 1, order: str = "alpha") -> str:
        self.calls.append(("annotate", {"start_number": start_number, "order": order}))
        return "annotated"

    def reload(self) -> str:
        self.calls.append(("reload", {}))
        return "reloaded"


def _registered() -> tuple[FastMCP, FakeLifecycleService]:
    server = FastMCP("schematic-lifecycle-test")
    service = FakeLifecycleService()
    register(server, SchematicLifecycleAuthoringDependencies(service=service))  # type: ignore[arg-type]
    return server, service


def test_registration_preserves_names_descriptions_and_schemas() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {"sch_add_jumper", "sch_annotate", "sch_reload"}
    assert tools["sch_add_jumper"].description == "Add a jumper symbol to the schematic."
    assert tools["sch_annotate"].description == "Renumber schematic references sequentially."
    assert tools["sch_reload"].description == "Ask KiCad to reload the active schematic."
    assert tools["sch_add_jumper"].parameters == {
        "properties": {
            "x_mm": {"title": "X Mm", "type": "number"},
            "y_mm": {"title": "Y Mm", "type": "number"},
            "pins": {"default": 2, "title": "Pins", "type": "integer"},
            "open_by_default": {
                "default": True,
                "title": "Open By Default",
                "type": "boolean",
            },
            "snap_to_grid": {
                "default": True,
                "title": "Snap To Grid",
                "type": "boolean",
            },
        },
        "required": ["x_mm", "y_mm"],
        "title": "sch_add_jumperArguments",
        "type": "object",
    }
    assert tools["sch_annotate"].parameters == {
        "properties": {
            "start_number": {
                "default": 1,
                "title": "Start Number",
                "type": "integer",
            },
            "order": {"default": "alpha", "title": "Order", "type": "string"},
        },
        "title": "sch_annotateArguments",
        "type": "object",
    }
    assert tools["sch_reload"].parameters == {
        "properties": {},
        "title": "sch_reloadArguments",
        "type": "object",
    }
    for name, tool in tools.items():
        assert tool.output_schema == {
            "properties": {"result": {"title": "Result", "type": "string"}},
            "required": ["result"],
            "title": f"{name}Output",
            "type": "object",
        }
        assert tool.annotations is None


def test_registration_preserves_metadata() -> None:
    server, _service = _registered()
    metadata = {tool.name: get_tool_metadata(tool.name) for tool in server._tool_manager.list_tools()}

    jumper = metadata["sch_add_jumper"]
    assert jumper is not None
    assert jumper.headless_compatible is True
    assert jumper.requires_kicad_running is False
    assert metadata["sch_annotate"] is None
    assert metadata["sch_reload"] is None


def test_registration_delegates_exact_arguments() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert (
        tools["sch_add_jumper"].fn(
            x_mm=10.0,
            y_mm=20.0,
            pins=3,
            open_by_default=False,
            snap_to_grid=False,
        )
        == "jumper"
    )
    assert tools["sch_annotate"].fn(start_number=10, order="sheet") == "annotated"
    assert tools["sch_reload"].fn() == "reloaded"
    assert service.calls == [
        (
            "add_jumper",
            {
                "x_mm": 10.0,
                "y_mm": 20.0,
                "pins": 3,
                "open_by_default": False,
                "snap_to_grid": False,
            },
        ),
        ("annotate", {"start_number": 10, "order": "sheet"}),
        ("reload", {}),
    ]
