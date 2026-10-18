"""JLCPCB #1314: native XL4015 + LM358 schematic netlist intention check.

Article-derived minimal equivalent, NOT the unavailable exact article input:
real KiCad XL4015 and LM358 symbols (all 3 op-amp units) and nineteen
resistor terminal probes. All 16 intended nets carry two numbered endpoints.
ISENSE and ISET are intentionally assigned to distinct LM358 input pins.

No DRC/manufacturing or circuit-function claims follow from this topology.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from defusedxml.ElementTree import parse

from kicad_mcp.config import reset_config
from kicad_mcp.server import build_server
from kicad_mcp.tools.export_support import _run_cli
from tests.conftest import call_tool_text

# Schematic pin names are intentionally compared by (ref, pin), not by ERC.
_SOURCE_NETS = [
    ("U1", "1", "CC_OUT"),
    ("U1", "2", "CC_NEG"),
    ("U1", "3", "ISENSE"),
    ("U1", "7", "CV_OUT"),
    ("U1", "6", "CV_NEG"),
    ("U1", "5", "ISET"),
    ("U1", "8", "AMP_VCC"),
    ("U1", "4", "GND"),
    ("U2", "1", "BUCK_GND"),
    ("U2", "2", "FB"),
    ("U2", "3", "SW"),
    ("U2", "4", "VC"),
    ("U2", "5", "VIN"),
]
_EXTRA_NETS = ["VOUT", "VREF", "LED_CC"]
EXPECTED = {
    **{
        name: frozenset({(ref, pin), (f"R{i}", "1")})
        for i, (ref, pin, name) in enumerate(_SOURCE_NETS, 1)
    },
    **{
        name: frozenset({(f"R{i}", "1"), (f"R{i + 3}", "1")})
        for i, name in enumerate(_EXTRA_NETS, 14)
    },
}


def _symbols() -> list[dict[str, str | float | int]]:
    symbols: list[dict[str, str | float | int]] = [
        {
            "library": "Amplifier_Operational",
            "symbol_name": "LM358",
            "reference": "U1",
            "value": "LM358",
            "x_mm": x,
            "y_mm": 50.8,
            "unit": unit,
        }
        for unit, x in [(1, 50.8), (2, 101.6), (3, 152.4)]
    ]
    symbols.append(
        {
            "library": "Regulator_Switching",
            "symbol_name": "XL4015",
            "reference": "U2",
            "value": "XL4015",
            "x_mm": 50.8,
            "y_mm": 88.9,
        }
    )
    symbols += [
        {
            "library": "Device",
            "symbol_name": "R",
            "reference": f"R{i}",
            "value": "10k",
            "x_mm": 50.8 + ((i - 1) % 6) * 25.4,
            "y_mm": 114.3 + ((i - 1) // 6) * 25.4,
        }
        for i in range(1, 20)
    ]
    return symbols


@pytest.mark.anyio
@pytest.mark.parametrize("short_isense_and_iset", [False, True])
async def test_xl4015_16_nets_match_native_pin_graph(
    sample_project,
    mock_kicad,
    monkeypatch,
    tmp_path,
    short_isense_and_iset: bool,
) -> None:
    cli = shutil.which("kicad-cli")
    symbols_path = Path("/usr/share/kicad/symbols")
    if not cli or any(
        not (symbols_path / f"{lib}.kicad_sym").is_file()
        for lib in ["Amplifier_Operational", "Regulator_Switching", "Device"]
    ):
        pytest.skip("requires installed official KiCad symbols and native CLI")
    monkeypatch.setenv("KICAD_MCP_SYMBOL_LIBRARY_DIR", str(symbols_path))
    monkeypatch.setenv("KICAD_MCP_KICAD_CLI", cli)
    reset_config()

    nets = [
        {
            "name": "ISENSE" if short_isense_and_iset and name == "ISET" else name,
            "endpoints": [f"{ref}.{pin}", f"R{i}.1"],
        }
        for i, (ref, pin, name) in enumerate(_SOURCE_NETS, 1)
    ]
    nets.extend(
        {"name": name, "endpoints": [f"R{i}.1", f"R{i + 3}.1"]}
        for i, name in enumerate(_EXTRA_NETS, 14)
    )
    result = await call_tool_text(
        build_server("schematic"),
        "sch_build_circuit",
        {"symbols": _symbols(), "nets": nets},
    )
    assert "WARNING" not in result, result
    xml = tmp_path / "xl4015-16net.xml"
    code, stdout, stderr = _run_cli(
        "sch",
        "export",
        "netlist",
        "--format",
        "kicadxml",
        "-o",
        str(xml),
        str(sample_project / "demo.kicad_sch"),
        timeout=45,
    )
    assert code == 0, f"KiCad XML export failed: {stdout} {stderr}"

    graph = {
        net.attrib["name"]: frozenset(
            (node.attrib["ref"], node.attrib["pin"]) for node in net.findall("node")
        )
        for net in parse(xml).findall(".//nets/net")
        if not net.attrib["name"].startswith("unconnected-")
    }
    if short_isense_and_iset:
        # Negative control: intended-net comparison must catch a merged net,
        # independently of whatever ERC concludes about that same schematic.
        assert graph != EXPECTED
        assert "ISET" not in graph
        assert {("U1", "3"), ("U1", "5")} <= graph["ISENSE"]
    else:
        assert len(graph) == len(EXPECTED) == 16
        assert graph == EXPECTED
        assert graph["ISENSE"].isdisjoint(graph["ISET"])
