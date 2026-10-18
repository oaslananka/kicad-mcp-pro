"""End-to-end no-short regression for `sch_build_circuit` (issue #198).

The unit tests in ``test_schematic_netlist_safe_default.py`` prove the builder
*dispatches* to the collision-safe planner by default. This module proves the
**rendered schematic** of a non-trivial netlist — a power rail shared across
several parts plus a fanned-out signal — contains no long routed wires, the
exact geometry that KiCad merges into silent shorts. The collision-safe planner
emits only short ``5.08 mm`` per-pin stubs and connects everything by named
terminals, so every wire in the default output must stay at stub length.
"""

from __future__ import annotations

import re

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text

# The collision-safe planner stubs each pin outward by exactly 5.08 mm; allow a
# small tolerance for grid/rounding noise. Anything longer is a routed star wire.
_MAX_SAFE_STUB_MM = 5.08 + 0.01

_WIRE_SEGMENT = re.compile(
    r"\(wire\s*\(pts\s*\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s*\(xy\s+([-\d.]+)\s+([-\d.]+)\)",
    re.DOTALL,
)

# Three resistors on a row. R*.1 fan out to a shared signal net, R*.2 share the
# GND rail — under the old routed-wire planner the SIG_A and GND stars would
# cross between the parts and could merge by geometry into a short.
_SHARED_RAIL_SYMBOLS = [
    {
        "library": "Device",
        "symbol_name": "R",
        "reference": ref,
        "value": "10k",
        "footprint": "Resistor_SMD:R_0805",
        "x_mm": x,
        "y_mm": 60.0,
    }
    for ref, x in (("R1", 50.8), ("R2", 76.2), ("R3", 101.6))
]
_SHARED_RAIL_NETS = [
    {"name": "SIG_A", "endpoints": ["R1.1", "R2.1", "R3.1"]},
    {"name": "GND", "endpoints": ["R1.2", "R2.2", "R3.2"]},
]


def _wire_lengths(schematic: str) -> list[float]:
    lengths: list[float] = []
    for x1, y1, x2, y2 in _WIRE_SEGMENT.findall(schematic):
        lengths.append(((float(x2) - float(x1)) ** 2 + (float(y2) - float(y1)) ** 2) ** 0.5)
    return lengths


@pytest.mark.anyio
async def test_default_build_circuit_emits_no_routed_wires(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_build_circuit",
        {"symbols": _SHARED_RAIL_SYMBOLS, "nets": _SHARED_RAIL_NETS},
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")

    # The default path must use the collision-safe terminal planner.
    assert "collision-safe" in result
    assert "unsafe routed mode" not in result

    # Every wire is a short stub — no star routing that could merge nets.
    lengths = _wire_lengths(schematic)
    assert lengths, "expected per-pin stub wires in the default output"
    assert max(lengths) <= _MAX_SAFE_STUB_MM, (
        f"a wire longer than a stub ({max(lengths):.2f} mm) implies routed star "
        "geometry that KiCad can merge into a short"
    )

    # Connectivity is carried by named terminals: a GND power symbol per pin and
    # a SIG_A global label per pin, so SIG_A and GND can never merge geometrically.
    assert schematic.count('(lib_id "power:GND")') == 3
    assert schematic.count('(global_label "SIG_A"') == 3


@pytest.mark.anyio
async def test_build_circuit_scope_selects_label_kind(sample_project, mock_kicad) -> None:
    """Per-net ``scope`` selects the emitted terminal label kind end-to-end."""
    server = build_server("schematic")
    nets = [
        {
            "name": "SIG_A",
            "endpoints": ["R1.1", "R2.1", "R3.1"],
            "scope": "hierarchical",
            "shape": "input",
        },
        {"name": "SIG_B", "endpoints": ["R1.2", "R2.2", "R3.2"], "scope": "local"},
    ]
    await call_tool_text(
        server,
        "sch_build_circuit",
        {"symbols": _SHARED_RAIL_SYMBOLS, "nets": nets},
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")

    # Hierarchical scope emits hierarchical labels carrying the requested shape;
    # no global label for SIG_A survives.
    assert schematic.count('(hierarchical_label "SIG_A"') == 3
    assert "(shape input)" in schematic
    assert '(global_label "SIG_A"' not in schematic
    # Local scope emits plain sheet-local labels (not global) for the SIG_B net.
    assert schematic.count('(label "SIG_B"') == 3
    assert '(global_label "SIG_B"' not in schematic


@pytest.mark.anyio
async def test_build_circuit_defaults_to_global_label_without_scope(
    sample_project, mock_kicad
) -> None:
    """Regression: omitting ``scope`` still emits global labels (unchanged default)."""
    server = build_server("schematic")
    await call_tool_text(
        server,
        "sch_build_circuit",
        {"symbols": _SHARED_RAIL_SYMBOLS, "nets": _SHARED_RAIL_NETS},
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")

    assert schematic.count('(global_label "SIG_A"') == 3
    assert '(hierarchical_label "SIG_A"' not in schematic
    assert '(label "SIG_A"' not in schematic


@pytest.mark.anyio
async def test_build_circuit_rejects_invalid_scope(sample_project, mock_kicad) -> None:
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": _SHARED_RAIL_SYMBOLS,
            "nets": [{"name": "SIG_A", "endpoints": ["R1.1"], "scope": "sheet"}],
        },
    )

    assert "Invalid net scope" in result


@pytest.mark.anyio
async def test_unsafe_opt_in_still_routes_wires(sample_project, mock_kicad) -> None:
    """The routed planner remains reachable, but only behind the explicit flag."""
    server = build_server("schematic")
    result = await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": _SHARED_RAIL_SYMBOLS,
            "nets": _SHARED_RAIL_NETS,
            "unsafe_routed_wires": True,
        },
    )

    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    lengths = _wire_lengths(schematic)

    assert "unsafe routed mode" in result
    # The opt-in path routes real spans between parts, so at least one wire is
    # longer than a collision-safe stub — the very geometry the default avoids.
    assert any(length > _MAX_SAFE_STUB_MM for length in lengths)


@pytest.mark.anyio
async def test_three_unit_opamp_nets_resolve_each_pin_instead_of_last_unit(
    sample_project, mock_kicad
) -> None:
    """A dual op-amp and its power unit share U1 without losing earlier pins (#1314)."""
    pins = ("1", "2", "3", "7", "6", "5", "8", "4")
    symbols = [
        {
            "library": "MultiUnit",
            "symbol_name": "DualChild",
            "reference": "U1",
            "value": "DualChild",
            "x_mm": x,
            "y_mm": 50.8,
            "unit": unit,
        }
        for unit, x in ((1, 50.8), (2, 101.6), (3, 152.4))
    ]
    symbols.extend(
        {
            "library": "Device",
            "symbol_name": "R",
            "reference": f"R{i}",
            "value": "10k",
            "x_mm": 50.8 + 25.4 * i,
            "y_mm": 101.6,
        }
        for i in range(1, 5)
    )
    nets = [
        {
            "name": f"PIN_{pin}",
            "endpoints": [f"U1.{pin}", f"R{index // 2 + 1}.{index % 2 + 1}"],
        }
        for index, pin in enumerate(pins)
    ]
    result = await call_tool_text(
        build_server("schematic"), "sch_build_circuit", {"symbols": symbols, "nets": nets}
    )
    assert "Generated 16 collision-safe terminal stub(s)" in result
    assert "WARNING" not in result
    schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")
    for pin in pins:
        assert schematic.count(f'(global_label "PIN_{pin}"') >= 2


@pytest.mark.anyio
async def test_reused_reference_with_conflicting_pin_coordinates_fails_closed(
    sample_project, mock_kicad
) -> None:
    """Two distinct physical positions cannot claim the same reference and pad."""
    result = await call_tool_text(
        build_server("schematic"),
        "sch_analyze_net_compilation",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "x_mm": 50.8,
                    "y_mm": 50.8,
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "x_mm": 101.6,
                    "y_mm": 50.8,
                },
            ],
            "nets": [{"name": "SIGNAL", "endpoints": ["R1.1", "R1.2"]}],
        },
    )
    assert "Ambiguous pin R1.1" in result
