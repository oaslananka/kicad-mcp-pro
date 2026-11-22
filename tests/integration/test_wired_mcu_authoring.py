"""Deterministic, native-library MCU authoring regression; not a model-prompt trial."""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

import pytest
from defusedxml.ElementTree import parse

from kicad_mcp.config import get_config, reset_config
from kicad_mcp.models.contract_verifier import extract_balanced_block
from kicad_mcp.server import build_server
from kicad_mcp.tools.export_support import _run_cli
from kicad_mcp.tools.schematic import get_pin_positions
from tests.conftest import call_tool_text

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/schematic_authoring/wroom32e.json"
LIBRARIES = ("RF_Module", "Device", "Switch", "Connector_Generic", "power")
REGULATED_FIXTURE = FIXTURE.with_name("wroom32e_regulator_gpio.json")


def _seed(folder: Path, libraries: Path, library_names: tuple[str, ...]) -> Path:
    folder.mkdir()
    (folder / "demo.kicad_pro").write_text('{"meta":{"version":1}}', encoding="utf-8")
    schematic = folder / "demo.kicad_sch"
    schematic.write_text(
        '(kicad_sch (version 20250316) (generator "kicad-mcp-pro") '
        '(uuid "b2c3d4e5-0000-4000-8000-000000000001") (paper "A4") '
        '(lib_symbols) (sheet_instances (path "/" (page "1"))) (embedded_fonts no))\n',
        encoding="utf-8",
    )
    entries = "\n".join(
        f' (lib (name "{name}")(type "KiCad")'
        f'(uri "{(libraries / (name + ".kicad_sym")).as_posix()}")'
        '(options "")(descr ""))'
        for name in library_names
    )
    (folder / "sym-lib-table").write_text(f"(sym_lib_table\n{entries}\n)\n", encoding="utf-8")
    return schematic


def _mcu_pins(source: Path) -> dict[str, tuple[float, float]]:
    text = source.read_text(encoding="utf-8")
    for match in re.finditer(r"(?m)^\t\(symbol\s*\n", text):
        block = extract_balanced_block(text, match.start() + 1)
        if '(property "Reference" "U1"' in block:
            at = re.search(r"\(at ([\d.]+) ([\d.]+) (\d+)\)", block)
            assert at is not None
            x, y, rotation = map(float, at.groups())
            return get_pin_positions("RF_Module", "ESP32-WROOM-32E", x, y, int(rotation), 1)
    raise AssertionError("MCU missing from generated schematic")


def _arguments(plan: dict, wired: bool) -> dict:
    if wired:
        return {key: plan[key] for key in ("symbols", "wires", "labels", "power_symbols")}
    return {
        "symbols": [
            {key: value for key, value in symbol.items() if key not in {"x_mm", "y_mm"}}
            for symbol in plan["symbols"]
        ],
        "nets": [
            {"name": name, "endpoints": pins, "scope": "local"}
            for name, pins in plan["nets"].items()
        ],
        "auto_layout": True,
        "max_paper": "A4",
    }


async def _build(
    folder: Path, libraries: Path, wired: bool, fixture: Path, library_names: tuple[str, ...]
) -> Path:
    source = _seed(folder, libraries, library_names)
    plan = json.loads(fixture.read_text(encoding="utf-8"))
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(folder)})
    get_config().symbol_library_dir = libraries
    result = await call_tool_text(server, "sch_build_circuit", _arguments(plan, wired))
    assert "Sheet replaced" in result, result
    assert "WARNING" not in result, result
    used_pins = {
        endpoint.removeprefix("U1.")
        for endpoints in plan["nets"].values()
        for endpoint in endpoints
        if endpoint.startswith("U1.")
    }
    for pin, (x, y) in _mcu_pins(source).items():
        if pin not in used_pins:
            await call_tool_text(server, "sch_add_no_connect", {"x_mm": x, "y_mm": y})
    title = (
        "ESP32-WROOM-32E regulated GPIO fixture"
        if fixture == REGULATED_FIXTURE
        else "ESP32-WROOM-32E fixture"
    )
    await call_tool_text(server, "sch_set_title_block_info", {"title": title, "rev": "A"})
    if wired and fixture == REGULATED_FIXTURE:
        # A clean ERC/netlist does not prove readable power-input symbols.
        # Prevent the J1/GND overlap found in a real native SVG review.
        qa = json.loads(await call_tool_text(server, "sch_visual_qa", {}))
        assert qa["status"] == "PASS", qa
        assert all(sheet["status"] == "PASS" for sheet in qa["sheets"]), qa
    return source


def _signature(xml: Path) -> tuple[set[frozenset[str]], set[tuple[str, str, str]]]:
    root = parse(xml)
    nets = {
        frozenset(f"{node.attrib['ref']}.{node.attrib['pin']}" for node in net.findall("node"))
        for net in root.findall("./nets/net")
    }
    components = {
        (comp.attrib["ref"], comp.findtext("value", ""), comp.findtext("footprint", ""))
        for comp in root.findall("./components/comp")
    }
    return nets, components


def _expected_nets(fixture: Path) -> set[frozenset[str]]:
    plan = json.loads(fixture.read_text(encoding="utf-8"))
    expected = {
        frozenset(pin for pin in pins if not pin.startswith("#")) for pins in plan["nets"].values()
    }
    expected.remove(next(net for net in expected if "U1.[1,15,38,39]" in net))
    expected.add(
        frozenset(
            {
                pin
                for pin in plan["nets"]["GND"]
                if not pin.startswith("#") and not pin.startswith("U1.")
            }
            | {f"U1.{pin}" for pin in (1, 15, 38, 39)}
        )
    )
    used = {pin for net in expected for pin in net}
    expected.update(frozenset({f"U1.{pin}"}) for pin in range(1, 40) if f"U1.{pin}" not in used)
    return expected


def _export(source: Path) -> tuple[set[frozenset[str]], set[tuple[str, str, str]]]:
    before = source.read_bytes()
    folder = source.parent
    for args in (
        ("sch", "erc", "--exit-code-violations", "-o", str(folder / "erc.rpt")),
        ("sch", "export", "svg", "-o", str(folder) + os.sep),
        ("sch", "export", "netlist", "--format", "kicadxml", "-o", str(folder / "netlist.xml")),
    ):
        code, stdout, stderr = _run_cli(*args, str(source), timeout=60)
        assert code == 0, (args, stdout, stderr)
    assert source.read_bytes() == before
    assert (folder / "demo.svg").stat().st_size > 1000
    return _signature(folder / "netlist.xml")


@pytest.mark.parametrize(
    ("fixture", "library_names", "component_count"),
    [
        (FIXTURE, LIBRARIES, 12),
        (REGULATED_FIXTURE, (*LIBRARIES, "Regulator_Linear"), 15),
    ],
    ids=["mcu-direct-power", "mcu-regulator-gpio"],
)
@pytest.mark.anyio
async def test_wired_mcu_matches_label_only_native_connectivity(
    tmp_path,
    monkeypatch,
    mock_kicad,
    fixture: Path,
    library_names: tuple[str, ...],
    component_count: int,
) -> None:
    libraries = Path(os.environ.get("KICAD_WIRED_NATIVE_SYMBOL_DIR", "/usr/share/kicad/symbols"))
    if not all((libraries / f"{name}.kicad_sym").is_file() for name in library_names):
        pytest.skip("Requires KiCad 10 symbol libraries; set KICAD_WIRED_NATIVE_SYMBOL_DIR")
    monkeypatch.setenv("KICAD_MCP_SYMBOL_LIBRARY_DIR", str(libraries))
    reset_config()
    wired = await _build(tmp_path / "wired", libraries, True, fixture, library_names)
    baseline = await _build(tmp_path / "label-only", libraries, False, fixture, library_names)
    labels_wired = wired.read_text(encoding="utf-8").count("(label ")
    labels_baseline = baseline.read_text(encoding="utf-8").count("(label ")
    assert labels_wired < labels_baseline
    if fixture == FIXTURE:
        assert (labels_wired, labels_baseline) == (10, 15)
    assert len(_expected_nets(fixture)) == (38 if fixture == REGULATED_FIXTURE else 37)
    cli = os.environ.get("KICAD_WIRED_NATIVE_CLI") or shutil.which("kicad-cli")
    if not cli:
        pytest.skip("Both layouts generated; native export requires KiCad CLI")
    monkeypatch.setenv("KICAD_MCP_KICAD_CLI", cli)
    reset_config()
    actual, components = _export(wired)
    comparison, other_components = _export(baseline)
    assert actual == _expected_nets(fixture)
    assert comparison == actual
    assert components == other_components
    assert len(components) == component_count


def test_regulated_gpio_fixture_models_real_power_and_interface_blocks() -> None:
    fixture = FIXTURE.with_name("wroom32e_regulator_gpio.json")
    plan = json.loads(fixture.read_text(encoding="utf-8"))
    refs = {symbol["reference"]: symbol for symbol in plan["symbols"]}
    assert refs["U2"]["library"] == "Regulator_Linear"
    assert refs["U2"]["symbol_name"] == "AMS1117-3.3"
    assert refs["J3"]["symbol_name"] == "Conn_01x02"
    assert refs["J3"]["value"] == "Conn_01x02", "Keep functional GPIO names on nets, not Value"
    assert {"J1.1", "U2.3", "C1.1"} <= set(plan["nets"]["+5V"])
    assert {"U2.2", "U1.2", "C2.1", "C4.1"} <= set(plan["nets"]["+3V3"])
    assert {"U2.1", "C1.2", "C2.2", "C4.2"} <= set(plan["nets"]["GND"])
    assert set(plan["nets"]["GPIO_A"]) == {"U1.26", "J3.1"}
    assert set(plan["nets"]["GPIO_B"]) == {"U1.29", "J3.2"}
    assert len(plan["symbols"]) == 17
    assert len(plan["wires"]) > 40
    input_flag = refs["#FLG01"]
    source_connector = refs["J1"]
    assert (input_flag["x_mm"] - source_connector["x_mm"]) ** 2 + (
        input_flag["y_mm"] - source_connector["y_mm"]
    ) ** 2 >= 15**2, "Do not overlap the input PWR_FLAG and connector reference/value"
    endpoints = [
        (x, y)
        for wire in plan["wires"]
        for x, y in (
            (wire["x1_mm"], wire["y1_mm"]),
            (wire["x2_mm"], wire["y2_mm"]),
        )
    ]
    # KiCad's junction semantics require explicit segment endpoints at branches.
    for point, min_segments in (
        ((43.18, 30.48), 2),  # +5V input PWR_FLAG
        ((50.8, 30.48), 3),  # +5V input cap
        ((88.9, 30.48), 3),  # regulated output decoupling
    ):
        assert endpoints.count(point) >= min_segments, point
