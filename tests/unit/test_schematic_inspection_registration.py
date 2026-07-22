from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.schematic_inspection import (
    SchematicInspectionDependencies,
    register,
)
from kicad_mcp.utils.cache import clear_ttl_cache


class FakeInspectionService:
    def __init__(self) -> None:
        self.symbol_calls = 0
        self.paths: list[Path] = []

    def symbols(self, path: Path) -> str:
        self.symbol_calls += 1
        self.paths.append(path)
        return "symbols"

    def wires(self, path: Path) -> str:
        self.paths.append(path)
        return "wires"

    def labels(self, path: Path) -> str:
        self.paths.append(path)
        return "labels"

    def net_names(self, path: Path) -> str:
        self.paths.append(path)
        return "net-names"

    def population_status(self, reference: str | None = None, sheet: str | None = None) -> str:
        return f"population:{reference}:{sheet}"

    def pin_positions(
        self,
        library: str,
        symbol_name: str,
        x_mm: float,
        y_mm: float,
        rotation: int = 0,
        unit: int = 1,
    ) -> str:
        return f"pins:{library}:{symbol_name}:{x_mm}:{y_mm}:{rotation}:{unit}"

    def power_flags(self, path: Path) -> str:
        self.paths.append(path)
        return "power-flags"


def _registered() -> tuple[FastMCP, FakeInspectionService]:
    clear_ttl_cache()
    server = FastMCP("schematic-inspection-test")
    service = FakeInspectionService()
    dependencies = SchematicInspectionDependencies(
        resolve_target=lambda sheet=None, sheet_file=None: SimpleNamespace(
            path=Path(sheet_file or sheet or "root.kicad_sch")
        ),
        active_schematic_file=lambda: Path("active.kicad_sch"),
        service=service,
    )
    register(server, dependencies)
    return server, service


def test_registration_preserves_exact_public_names_and_input_schemas() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {
        "sch_get_symbols",
        "sch_get_wires",
        "sch_get_labels",
        "sch_get_net_names",
        "sch_get_population_status",
        "sch_get_pin_positions",
        "sch_check_power_flags",
    }
    assert tools["sch_get_symbols"].parameters["properties"] == {
        "sheet": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "default": None,
            "title": "Sheet",
        },
        "sheet_file": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
            "default": None,
            "title": "Sheet File",
        },
    }
    assert tools["sch_get_pin_positions"].parameters["required"] == [
        "library",
        "symbol_name",
        "x_mm",
        "y_mm",
    ]
    assert tools["sch_get_pin_positions"].parameters["properties"]["rotation"]["default"] == 0
    assert tools["sch_get_pin_positions"].parameters["properties"]["unit"]["default"] == 1


def test_registration_preserves_target_adaptation_and_symbol_cache() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert tools["sch_get_symbols"].fn(sheet="child", sheet_file=None) == "symbols"
    assert tools["sch_get_symbols"].fn(sheet="child", sheet_file=None) == "symbols"
    assert service.symbol_calls == 1
    assert service.paths == [Path("child")]
    assert tools["sch_get_wires"].fn(sheet=None, sheet_file="child.kicad_sch") == "wires"
    assert tools["sch_check_power_flags"].fn() == "power-flags"
    assert service.paths[-2:] == [Path("child.kicad_sch"), Path("active.kicad_sch")]


def test_registration_preserves_headless_metadata_and_argument_forwarding() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    population_metadata = get_tool_metadata("sch_get_population_status")
    assert population_metadata is not None
    assert population_metadata.headless_compatible is True
    assert tools["sch_get_population_status"].fn(reference="R1", sheet="power") == (
        "population:R1:power"
    )
    assert (
        tools["sch_get_pin_positions"].fn(
            library="Device",
            symbol_name="R",
            x_mm=10.0,
            y_mm=20.0,
            rotation=90,
            unit=2,
        )
        == "pins:Device:R:10.0:20.0:90:2"
    )
