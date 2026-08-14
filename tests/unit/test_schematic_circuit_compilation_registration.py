# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.schematic_circuit_compilation import (
    SchematicCircuitCompilationDependencies,
    register,
)


class FakeCircuitCompilationService:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def analyze(
        self,
        symbols: list[dict[str, Any]] | None = None,
        wires: list[dict[str, Any]] | None = None,
        labels: list[dict[str, Any]] | None = None,
        power_symbols: list[dict[str, Any]] | None = None,
        nets: list[dict[str, Any]] | None = None,
        snap_to_grid: bool = True,
        auto_layout: bool = False,
        unsafe_routed_wires: bool = False,
    ) -> str:
        self.calls.append(
            (
                "analyze",
                {
                    "symbols": symbols,
                    "wires": wires,
                    "labels": labels,
                    "power_symbols": power_symbols,
                    "nets": nets,
                    "snap_to_grid": snap_to_grid,
                    "auto_layout": auto_layout,
                    "unsafe_routed_wires": unsafe_routed_wires,
                },
            )
        )
        return "analysis"

    def build(
        self,
        symbols: list[dict[str, Any]] | None = None,
        wires: list[dict[str, Any]] | None = None,
        labels: list[dict[str, Any]] | None = None,
        power_symbols: list[dict[str, Any]] | None = None,
        nets: list[dict[str, Any]] | None = None,
        snap_to_grid: bool = True,
        auto_layout: bool = False,
        unsafe_routed_wires: bool = False,
    ) -> str:
        self.calls.append(
            (
                "build",
                {
                    "symbols": symbols,
                    "wires": wires,
                    "labels": labels,
                    "power_symbols": power_symbols,
                    "nets": nets,
                    "snap_to_grid": snap_to_grid,
                    "auto_layout": auto_layout,
                    "unsafe_routed_wires": unsafe_routed_wires,
                },
            )
        )
        return "built"


def _registered() -> tuple[FastMCP, FakeCircuitCompilationService]:
    server = FastMCP("schematic-circuit-compilation-test")
    service = FakeCircuitCompilationService()
    register(server, SchematicCircuitCompilationDependencies(service=service))  # type: ignore[arg-type]
    return server, service


def test_registration_preserves_names_descriptions_and_schemas() -> None:
    server, _service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}

    assert set(tools) == {"sch_analyze_net_compilation", "sch_build_circuit"}
    assert tools["sch_analyze_net_compilation"].description == (
        "Preview how netlist-aware schematic compilation will resolve endpoints and wires.\n\n"
        "Mirrors ``sch_build_circuit``: by default nets resolve to collision-safe\n"
        "terminal stubs; pass ``unsafe_routed_wires=True`` to preview routed Manhattan\n"
        "wire segments instead.\n"
    )
    assert tools["sch_build_circuit"].description == (
        "Build (overwrite) the active schematic from structured symbol, wire, and label inputs.\n\n"
        "IMPORTANT: This tool **replaces** the entire schematic content.  Any symbols\n"
        "already placed in the schematic will be lost.  To add symbols to an existing\n"
        "schematic without erasing it use ``sch_add_symbol`` / ``sch_add_wire`` /\n"
        "``sch_add_label`` instead.\n\n"
        "Coordinates are snapped to the 1.27 mm / 50 mil grid by default.  When no coordinates\n"
        "are provided for a symbol, set ``auto_layout=True`` so the placement engine\n"
        "assigns non-overlapping positions automatically.\n\n"
        "When ``nets`` are provided, the builder is connection-aware. By default it\n"
        "uses the **collision-safe** strategy: each pin endpoint gets a short stub plus\n"
        "a same-named terminal (a global label for signal nets, a power symbol for\n"
        "power nets), so nets connect *by name* and can never short by crossing wire\n"
        "geometry.  Nets that cannot resolve to a routable pin endpoint raise a clear\n"
        "error (or are surfaced as warnings) instead of silently producing a\n"
        "disconnected schematic.\n\n"
        "Each net may set an optional ``scope`` to control the emitted terminal\n"
        'label kind: ``"global"`` (default when omitted, connects across the whole\n'
        'design), ``"local"`` (sheet-local label), or ``"hierarchical"`` (with an\n'
        "optional ``shape`` of input/output/bidirectional for sheet-pin wiring).\n\n"
        "Set ``unsafe_routed_wires=True`` only if you explicitly want routed Manhattan\n"
        "wire segments between pins.  That star-routing can cross unrelated pins or\n"
        "labels and KiCad will merge them by geometry, so it can introduce silent\n"
        "shorts on non-trivial netlists — prefer the default terminal strategy.\n\n"
        "Each symbol may carry an optional ``properties`` mapping (``dict[str, str]``);\n"
        "every key/value is written verbatim as an additional schematic symbol field,\n"
        "alongside the standard fields — handy for order numbers such as\n"
        '``{"MPN": "...", "Mouser": "...", "LCSC": "..."}`` without a second\n'
        "``sch_update_properties`` pass.  Keys colliding with the standard\n"
        "Reference/Value/Footprint/Datasheet fields are ignored in favour of the\n"
        "dedicated ``reference``/``value``/``footprint`` inputs (those always win).\n\n"
        "Recommended workflow:\n"
        "  1. Call ``sch_find_free_placement(count=N)`` to obtain safe coordinates.\n"
        "  2. Pass those coordinates in the ``symbols`` list.\n"
        "  3. OR set ``auto_layout=True`` and omit coordinates entirely.\n"
    )

    for name, tool in tools.items():
        properties = tool.parameters["properties"]
        assert set(properties) == {
            "symbols",
            "wires",
            "labels",
            "power_symbols",
            "nets",
            "snap_to_grid",
            "auto_layout",
            "unsafe_routed_wires",
        }
        assert properties["symbols"]["default"] is None
        assert properties["snap_to_grid"]["default"] is True
        assert properties["auto_layout"]["default"] is False
        assert properties["unsafe_routed_wires"]["default"] is False
        assert tool.parameters["title"] == f"{name}Arguments"
        assert tool.fn_metadata.output_schema["title"] == f"{name}Output"


def test_registration_preserves_default_annotations_and_metadata() -> None:
    server, _service = _registered()

    for tool in server._tool_manager.list_tools():
        assert tool.annotations is None
        assert get_tool_metadata(tool.name) is None


def test_registration_delegates_exact_arguments() -> None:
    server, service = _registered()
    tools = {tool.name: tool for tool in server._tool_manager.list_tools()}
    kwargs = {
        "symbols": [{"reference": "R1"}],
        "wires": [{"x1_mm": 0}],
        "labels": [{"name": "NET"}],
        "power_symbols": [{"name": "GND"}],
        "nets": [{"name": "NET"}],
        "snap_to_grid": False,
        "auto_layout": True,
        "unsafe_routed_wires": True,
    }

    assert tools["sch_analyze_net_compilation"].fn(**kwargs) == "analysis"
    assert tools["sch_build_circuit"].fn(**kwargs) == "built"
    assert service.calls == [("analyze", kwargs), ("build", kwargs)]
