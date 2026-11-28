"""Native KiCad 10 grouped physical-pin contract acceptance (#1955)."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from defusedxml import ElementTree

from kicad_mcp.config import reset_config
from kicad_mcp.connection import reset_connection
from kicad_mcp.models.contract_verifier import extract_balanced_block, parse_symbol_pins
from kicad_mcp.server import build_server
from kicad_mcp.tools.export_support import _run_cli
from tests.conftest import tool_text

LIB_ID = "RF_Module:ESP32-WROOM-32E"
GROUND = {"1", "15", "38", "39"}


def _schematic(block: str) -> str:
    root = uuid.uuid4()
    return f"""(kicad_sch (version 20260101) (generator "eeschema") (uuid "{root}") (paper "A4")
 (lib_symbols {block})
 (symbol (lib_id "{LIB_ID}") (at 100.33 100.33 0) (unit 1)
  (in_bom yes) (on_board yes) (dnp no) (uuid "{uuid.uuid4()}")
  (property "Reference" "U1" (at 100.33 65 0) (effects (font (size 1 1))))
  (property "Value" "ESP32-WROOM-32E" (at 100.33 67 0) (effects (font (size 1 1))))
  (property "Footprint" "{LIB_ID}" (at 100.33 100.33 0) (effects (font (size 1 1))))
  (instances (project "probe" (path "/{root}" (reference "U1") (unit 1)))))
 (wire (pts (xy 100.33 135.89) (xy 100.33 140.97))
  (stroke (width 0) (type default)) (uuid "{uuid.uuid4()}"))
 (global_label "GND" (shape input) (at 100.33 140.97 270)
  (effects (font (size 1 1))) (uuid "{uuid.uuid4()}"))
 )"""


def _native_pin_members(netlist: Path) -> tuple[set[str], set[str]]:
    xml = ElementTree.fromstring(netlist.read_bytes(), forbid_dtd=True)
    assert {node.get("ref") for node in xml.findall("components/comp")} == {"U1"}
    all_pins = set()
    ground = set()
    for net in xml.findall("nets/net"):
        for node in net.findall("node"):
            if node.get("ref") != "U1":
                continue
            pin = node.get("pin")
            assert pin is not None
            assert pin not in all_pins
            all_pins.add(pin)
            if net.get("name") == "GND":
                ground.add(pin)
                assert node.get("pintype") == "power_in"
    return all_pins, ground


@pytest.mark.anyio
async def test_native_grouped_ground_matches_physical_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cli = os.environ.get("KICAD_NATIVE_GROUPED_PIN_CLI")
    data = os.environ.get("KICAD_NATIVE_GROUPED_PIN_DATA")
    if not cli or not data:
        pytest.skip("Explicit native KiCad CLI and stock KiCad data directory required")
    root = Path(data).resolve(strict=True)
    library = root / "symbols/RF_Module.kicad_sym"
    footprint = root / "footprints/RF_Module.pretty/ESP32-WROOM-32E.kicad_mod"
    library_bytes = library.read_bytes()
    footprint_bytes = footprint.read_bytes()
    text = library_bytes.decode("utf-8")
    marker = '(symbol "ESP32-WROOM-32E"'
    block = extract_balanced_block(text, text.index(marker)).replace(
        marker, f'(symbol "{LIB_ID}"', 1
    )
    assert '(number "[1,15,38,39]"' in block
    # Resolve the actual registered tool against a disposable copy of the stock
    # footprint so negative checks cannot write to the installed library.
    private_libraries = tmp_path / "footprints"
    private_footprint = private_libraries / "RF_Module.pretty" / footprint.name
    private_footprint.parent.mkdir(parents=True)
    private_footprint.write_bytes(footprint_bytes)
    project = tmp_path / "project"
    project.mkdir()
    sch = project / "probe.kicad_sch"
    sch.write_text(_schematic(block), encoding="utf-8")
    sch.with_suffix(".kicad_pro").write_text("{}\n", encoding="utf-8")
    for name in tuple(os.environ):
        if name.startswith(("KICAD_MCP_", "KICAD_API_")):
            monkeypatch.delenv(name)
    for key, value in {
        "KICAD_CONFIG_HOME": str(tmp_path / "config"),
        "KICAD_DOCUMENTS_HOME": str(tmp_path / "documents"),
        "KICAD_MCP_KICAD_CLI": str(Path(cli).resolve(strict=True)),
        "KICAD_MCP_PROJECT_DIR": str(project),
        "KICAD_MCP_WORKSPACE_ROOT": str(project),
        "KICAD_MCP_FOOTPRINT_LIBRARY_DIR": str(private_libraries),
        "KICAD_MCP_KICAD_SOCKET_PATH": str(tmp_path / "unbound.sock"),
        "KICAD_MCP_OPERATING_MODE": "write",
        "KICAD_MCP_FILTER_RUNTIME_TOOLS": "false",
        "KICAD_MCP_TELEMETRY_ENABLED": "false",
    }.items():
        monkeypatch.setenv(key, value)
    reset_config()
    reset_connection()
    code, version, stderr = _run_cli("version")
    assert code == 0, stderr
    assert version.strip().startswith("10."), version
    netlist = project / "probe.xml"
    code, stdout, stderr = _run_cli(
        "sch", "export", "netlist", "--format", "kicadxml", "--output", str(netlist), str(sch)
    )
    assert code == 0, stderr or stdout
    native_pins, native_ground = _native_pin_members(netlist)
    assert native_ground == GROUND
    assert native_pins == {str(n) for n in range(1, 40)}
    pins = parse_symbol_pins(block)
    assert {pin.number for pin in pins} == native_pins
    assert {pin.number for pin in pins if pin.name == "GND"} == native_ground
    server = build_server("full")
    result = await server.call_tool("lib_verify_component_contract", {"reference": "U1"})
    report = json.loads(tool_text(result))
    assert report["status"] == "PASS", report
    assert {f["code"]: f["level"] for f in report["findings"]}["pin_pad_numbers"] == "PASS"
    assert any(f["message"] == "Pin count matches pad count (39)." for f in report["findings"])
    # An equal-count footprint with the wrong member must still fail numbering.
    footprint_text = footprint_bytes.decode("utf-8")
    assert '(pad "39"' in footprint_text
    private_footprint.write_text(footprint_text.replace('(pad "39"', '(pad "99"'), encoding="utf-8")
    wrong = json.loads(
        tool_text(await server.call_tool("lib_verify_component_contract", {"reference": "U1"}))
    )
    assert wrong["status"] == "FAIL", wrong
    findings = {finding["message"]: finding["level"] for finding in wrong["findings"]}
    assert findings["Pin count matches pad count (39)."] == "PASS"
    assert findings["Pins with no matching pad: 39."] == "FAIL"
    assert findings["Pads with no matching pin: 99."] == "WARN"

    # Removing the whole physical pad number (including repeated copper shapes)
    # must also fail. Only the disposable library is mutated.
    from kicad_mcp.utils.sexpr import iter_root_children

    missing = footprint_text
    blocks = [
        value
        for name, value in iter_root_children(footprint_text)
        if name == "pad" and value.startswith('(pad "39"')
    ]
    assert blocks
    for pad in blocks:
        missing = missing.replace(pad, "", 1)
    private_footprint.write_text(missing, encoding="utf-8")
    absent = json.loads(
        tool_text(await server.call_tool("lib_verify_component_contract", {"reference": "U1"}))
    )
    assert absent["status"] == "FAIL", absent
    findings = {finding["message"]: finding["level"] for finding in absent["findings"]}
    assert findings["Symbol has 39 pins but footprint has 38 connectable pads."] == "FAIL"
    assert findings["Pins with no matching pad: 39."] == "FAIL"
    assert library.read_bytes() == library_bytes
    assert footprint.read_bytes() == footprint_bytes
