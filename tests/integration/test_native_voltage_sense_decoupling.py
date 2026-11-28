"""Native CP2102N voltage-sense versus supply-decoupling acceptance (#1956)."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

import pytest
from defusedxml import ElementTree

from kicad_mcp.config import reset_config
from kicad_mcp.connection import reset_connection
from kicad_mcp.models.contract_verifier import extract_balanced_block
from kicad_mcp.tools.export_support import _run_cli
from kicad_mcp.tools.schematic import _build_connectivity_groups
from kicad_mcp.tools.validation import _evaluate_schematic_design_rule_gate

CP2102N = "Interface_USB:CP2102N-Axx-xQFN28"


def _embedded_symbol(path: Path, name: str, lib_id: str) -> str:
    text = path.read_text(encoding="utf-8")
    marker = f'(symbol "{name}"'
    return extract_balanced_block(text, text.index(marker)).replace(
        marker, f'(symbol "{lib_id}"', 1
    )


def _placed_symbol(root: str, lib_id: str, reference: str, value: str, x: float, y: float) -> str:
    return f"""(symbol (lib_id "{lib_id}") (at {x} {y} 0) (unit 1)
 (in_bom yes) (on_board yes) (dnp no) (uuid "{uuid.uuid4()}")
 (property "Reference" "{reference}" (at {x} {y} 0) (effects (font (size 1 1))))
 (property "Value" "{value}" (at {x} {y} 0) (effects (font (size 1 1))))
 (instances (project "sense" (path "/{root}" (reference "{reference}") (unit 1)))))"""


def _wire_label(name: str, x: float, y: float, end_x: float, end_y: float) -> str:
    return f"""(wire (pts (xy {x} {y}) (xy {end_x} {end_y}))
 (stroke (width 0) (type default)) (uuid "{uuid.uuid4()}"))
 (global_label "{name}" (shape input) (at {end_x} {end_y} 0)
 (effects (font (size 1 1))) (uuid "{uuid.uuid4()}"))"""


def _schematic(cp: str, resistor: str) -> str:
    root = str(uuid.uuid4())
    elements = [
        _placed_symbol(root, CP2102N, "U1", "CP2102N", 100.33, 100.33),
        _placed_symbol(root, "Device:R", "R1", "22.1k", 50.8, 83.82),
        _placed_symbol(root, "Device:R", "R2", "47.5k", 63.5, 83.82),
        _wire_label("VBUS_5V", 97.79, 67.31, 97.79, 62.23),
        _wire_label("VDD_3V3", 100.33, 67.31, 100.33, 62.23),
        _wire_label("VBUS_SENSE", 87.63, 85.09, 82.55, 85.09),
        _wire_label("GND", 100.33, 133.35, 100.33, 138.43),
        _wire_label("VBUS_5V", 50.8, 80.01, 50.8, 74.93),
        _wire_label("VBUS_SENSE", 50.8, 87.63, 50.8, 92.71),
        _wire_label("VBUS_SENSE", 63.5, 80.01, 63.5, 74.93),
        _wire_label("GND", 63.5, 87.63, 63.5, 92.71),
    ]
    return (
        f'(kicad_sch (version 20260101) (generator "eeschema") (uuid "{root}") (paper "A4")'
        f" (lib_symbols {cp} {resistor}) " + "\n".join(elements) + ")"
    )


def _assert_native_netlist(path: Path) -> None:
    xml = ElementTree.fromstring(path.read_bytes(), forbid_dtd=True)
    by_net = {
        net.get("name"): {(n.get("ref"), n.get("pin")) for n in net.findall("node")}
        for net in xml.findall("nets/net")
    }
    assert by_net["VBUS_5V"] == {("U1", "7"), ("R1", "1")}
    assert by_net["VBUS_SENSE"] == {("U1", "8"), ("R1", "2"), ("R2", "1")}
    assert by_net["GND"] == {("U1", "3"), ("U1", "29"), ("R2", "2")}
    assert by_net["VDD_3V3"] == {("U1", "6")}


def test_native_voltage_sense_divider_keeps_real_supply_warnings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = os.environ.get("KICAD_NATIVE_SENSE_CLI")
    data = os.environ.get("KICAD_NATIVE_SENSE_DATA")
    if not cli or not data:
        pytest.skip("Explicit native KiCad CLI and stock KiCad data directory required")
    symbols = Path(data).resolve(strict=True) / "symbols"
    cp_path, r_path = symbols / "Interface_USB.kicad_sym", symbols / "Device.kicad_sym"
    cp_bytes, r_bytes = cp_path.read_bytes(), r_path.read_bytes()
    cp = _embedded_symbol(cp_path, CP2102N.split(":")[1], CP2102N)
    resistor = _embedded_symbol(r_path, "R", "Device:R")
    project = tmp_path / "project"
    project.mkdir()
    sch = project / "sense.kicad_sch"
    sch.write_text(_schematic(cp, resistor), encoding="utf-8")
    sch.with_suffix(".kicad_pro").write_text("{}\n", encoding="utf-8")
    source = sch.read_bytes()
    for name in tuple(os.environ):
        if name.startswith(("KICAD_MCP_", "KICAD_API_")):
            monkeypatch.delenv(name)
    for key, value in {
        "KICAD_CONFIG_HOME": str(tmp_path / "config"),
        "KICAD_DOCUMENTS_HOME": str(tmp_path / "documents"),
        "KICAD_MCP_KICAD_CLI": str(Path(cli).resolve(strict=True)),
        "KICAD_MCP_PROJECT_DIR": str(project),
        "KICAD_MCP_WORKSPACE_ROOT": str(project),
        "KICAD_MCP_SYMBOL_LIBRARY_DIR": str(symbols),
        "KICAD_MCP_KICAD_SOCKET_PATH": str(tmp_path / "unbound.sock"),
        "KICAD_MCP_TELEMETRY_ENABLED": "false",
    }.items():
        monkeypatch.setenv(key, value)
    reset_config()
    reset_connection()
    code, version, stderr = _run_cli("version")
    assert code == 0, stderr
    assert version.strip().startswith("10."), version
    netlist = project / "sense.xml"
    code, stdout, stderr = _run_cli(
        "sch", "export", "netlist", "--format", "kicadxml", "--output", str(netlist), str(sch)
    )
    assert code == 0, stderr or stdout
    _assert_native_netlist(netlist)
    groups = _build_connectivity_groups(sch)
    pins = {
        name: {(pin["reference"], pin["pin"], pin["etype"]) for pin in net["pins"]}
        for net in groups
        for name in net["names"]
    }
    assert pins["VBUS_SENSE"] == {
        ("U1", "8", "input"),
        ("R1", "2", "passive"),
        ("R2", "1", "passive"),
    }
    assert ("U1", "7", "power_in") in pins["VBUS_5V"]
    assert ("U1", "6", "power_in") in pins["VDD_3V3"]
    gate = _evaluate_schematic_design_rule_gate()
    assert gate.status == "WARN"
    warnings = [item for item in gate.details if "[power_rail_decoupling]" in item]
    assert len(warnings) == 2, warnings
    assert any("'VBUS_5V'" in item for item in warnings)
    assert any("'VDD_3V3'" in item for item in warnings)
    assert not any("'VBUS_SENSE'" in item for item in warnings)
    assert sch.read_bytes() == source
    assert cp_path.read_bytes() == cp_bytes
    assert r_path.read_bytes() == r_bytes
