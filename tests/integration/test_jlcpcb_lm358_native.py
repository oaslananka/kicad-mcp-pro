"""JLCPCB #1314: verify real LM358 A/B/power units against KiCad netlist."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from defusedxml.ElementTree import parse

from kicad_mcp.config import reset_config
from kicad_mcp.server import build_server
from kicad_mcp.tools.export_support import _run_cli
from tests.conftest import call_tool_text

_PIN_NETS = {
    "1": "OUT_A",
    "2": "IN_A_NEG",
    "3": "IN_A_POS",
    "7": "OUT_B",
    "6": "IN_B_NEG",
    "5": "IN_B_POS",
    "8": "VCC",
    "4": "VEE",
}


@pytest.mark.anyio
async def test_lm358_three_units_preserve_pin_nets_in_native_export(
    sample_project,
    mock_kicad,
    monkeypatch,
    tmp_path,
) -> None:
    cli = shutil.which("kicad-cli")
    symbols_path = "/usr/share/kicad/symbols"
    if not cli or not (Path(symbols_path) / "Amplifier_Operational.kicad_sym").is_file():
        pytest.skip("requires installed KiCad official symbols and native CLI")
    monkeypatch.setenv("KICAD_MCP_SYMBOL_LIBRARY_DIR", symbols_path)
    # Use the actual executable through the application's validated CLI runner,
    # not the sample project's stub executable.
    monkeypatch.setenv("KICAD_MCP_KICAD_CLI", cli)
    reset_config()
    symbols = [
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
    symbols += [
        {
            "library": "Device",
            "symbol_name": "R",
            "reference": f"R{i}",
            "value": "10k",
            "x_mm": 50.8 + 25.4 * i,
            "y_mm": 101.6,
        }
        for i in range(1, 5)
    ]
    nets = [
        {"name": name, "endpoints": [f"U1.{pin}", f"R{(i // 2) + 1}.{(i % 2) + 1}"]}
        for i, (pin, name) in enumerate(_PIN_NETS.items())
    ]
    result = await call_tool_text(
        build_server("schematic"), "sch_build_circuit", {"symbols": symbols, "nets": nets}
    )
    assert "Generated 16 collision-safe terminal stub(s)" in result
    assert "WARNING" not in result
    output = tmp_path / "lm358.xml"
    code, stdout, stderr = _run_cli(
        "sch",
        "export",
        "netlist",
        "--format",
        "kicadxml",
        "-o",
        str(output),
        str(sample_project / "demo.kicad_sch"),
        timeout=30,
    )
    assert code == 0, f"native KiCad export failed: {stdout} {stderr}"
    tree = parse(output)
    graph = {
        node.attrib["pin"]: net.attrib["name"]
        for net in tree.findall(".//nets/net")
        for node in net.findall("node")
        if node.attrib["ref"] == "U1"
    }
    assert graph == _PIN_NETS
