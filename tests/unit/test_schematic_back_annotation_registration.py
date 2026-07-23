from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.schematic_back_annotation import (
    SchematicBackAnnotationDependencies,
    register,
)


class FakeBackAnnotationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def set_hop_over(self, enabled: bool = True) -> str:
        self.calls.append(("set_hop_over", (enabled,)))
        return "hop"

    def list_swappable_pins(self, component_ref: str) -> str:
        self.calls.append(("list_swappable_pins", (component_ref,)))
        return "list"

    def swap_pins(self, component_ref: str, pin_a: str, pin_b: str) -> str:
        self.calls.append(("swap_pins", (component_ref, pin_a, pin_b)))
        return "pins"

    def swap_gates(self, component_ref: str, gate_a: int, gate_b: int) -> str:
        self.calls.append(("swap_gates", (component_ref, gate_a, gate_b)))
        return "gates"


def _registered() -> tuple[FastMCP, FakeBackAnnotationService]:
    server = FastMCP("schematic-back-annotation-test")
    service = FakeBackAnnotationService()
    register(server, SchematicBackAnnotationDependencies(service=service))  # type: ignore[arg-type]
    return server, service


def test_registration_preserves_names_descriptions_and_schema_defaults() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {
        "sch_set_hop_over",
        "sch_list_swappable_pins",
        "sch_swap_pins",
        "sch_swap_gates",
    }
    assert tools["sch_set_hop_over"].description == (
        "Toggle KiCad 10 hop-over display in the active project settings."
    )
    assert tools["sch_list_swappable_pins"].description == (
        "List candidate pins and units that can participate in a swap workflow."
    )
    assert tools["sch_swap_pins"].description == (
        "Record a pin-swap back-annotation intent for a component."
    )
    assert tools["sch_swap_gates"].description == (
        "Record a gate-swap back-annotation intent for a multi-unit component."
    )
    assert tools["sch_set_hop_over"].parameters["properties"]["enabled"]["default"] is True
    assert tools["sch_set_hop_over"].parameters.get("required") is None
    assert tools["sch_list_swappable_pins"].parameters["required"] == ["component_ref"]
    assert tools["sch_swap_pins"].parameters["required"] == [
        "component_ref",
        "pin_a",
        "pin_b",
    ]
    assert tools["sch_swap_gates"].parameters["required"] == [
        "component_ref",
        "gate_a",
        "gate_b",
    ]


def test_registration_preserves_headless_metadata() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    for name in tools:
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True
        assert metadata.requires_kicad_running is False


def test_registration_delegates_all_arguments_and_defaults() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_set_hop_over"].fn() == "hop"
    assert tools["sch_list_swappable_pins"].fn(component_ref="R1") == "list"
    assert tools["sch_swap_pins"].fn(component_ref="R1", pin_a="1", pin_b="2") == "pins"
    assert tools["sch_swap_gates"].fn(component_ref="U1", gate_a=1, gate_b=2) == "gates"

    assert service.calls == [
        ("set_hop_over", (True,)),
        ("list_swappable_pins", ("R1",)),
        ("swap_pins", ("R1", "1", "2")),
        ("swap_gates", ("U1", 1, 2)),
    ]
