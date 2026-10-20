from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
@pytest.mark.slow
async def test_sch_build_circuit_exports_component_netlist_with_real_kicad_cli(
    tmp_path: Path,
) -> None:
    """Guard against visually valid schematics that disappear from KiCad netlists.

    The file writer can produce an SVG even when the placed-symbol S-expression is
    not accepted as a real component by KiCad's netlist exporter.  This smoke test
    uses the real KiCad CLI when it is installed and proves that a schematic built
    through sch_build_circuit contains at least one exported component.
    """

    kicad_cli = shutil.which("kicad-cli")
    if kicad_cli is None:
        pytest.skip("kicad-cli is not installed")

    project_root = tmp_path / "netlist-smoke"
    server = build_server("full")

    await call_tool_text(
        server,
        "kicad_create_new_project",
        {
            "path": str(project_root),
            "name": "SchSmoke",
            "confirm_overwrite": True,
        },
    )
    project_dir = project_root / "SchSmoke"
    schematic_path = project_dir / "SchSmoke.kicad_sch"

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805_2012Metric",
                    "x_mm": 50.8,
                    "y_mm": 50.8,
                }
            ],
            "wires": [],
            "labels": [],
            "power_symbols": [],
            "nets": [],
            "auto_layout": False,
        },
    )

    netlist_path = project_dir / "SchSmoke.net"
    subprocess.run(
        [
            kicad_cli,
            "sch",
            "export",
            "netlist",
            str(schematic_path),
            "--output",
            str(netlist_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    netlist = netlist_path.read_text(encoding="utf-8", errors="replace")
    assert "(comp" in netlist
    assert '(ref "R1")' in netlist
    assert '(value "10k")' in netlist
    assert "(components)" not in netlist


@pytest.mark.anyio
@pytest.mark.slow
async def test_sch_build_circuit_custom_power_rail_exports_named_net(
    tmp_path: Path,
) -> None:
    """Custom rails such as +3V3_A must be labels, not fake power symbols."""

    kicad_cli = shutil.which("kicad-cli")
    if kicad_cli is None:
        pytest.skip("kicad-cli is not installed")

    project_root = tmp_path / "custom-rail-smoke"
    server = build_server("full")

    await call_tool_text(
        server,
        "kicad_create_new_project",
        {
            "path": str(project_root),
            "name": "CustomRailSmoke",
            "confirm_overwrite": True,
        },
    )
    project_dir = project_root / "CustomRailSmoke"
    schematic_path = project_dir / "CustomRailSmoke.kicad_sch"

    flag_ref = chr(35) + "FLG1"
    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0603_1608Metric",
                },
                {
                    "library": "power",
                    "symbol_name": "PWR_FLAG",
                    "reference": flag_ref,
                    "value": "PWR_FLAG",
                    "footprint": "",
                },
            ],
            "wires": [],
            "labels": [],
            "power_symbols": [],
            "nets": [
                {"name": "+3V3_A", "endpoints": ["R1.1", f"{flag_ref}.1"]},
            ],
            "auto_layout": True,
        },
    )

    schematic = schematic_path.read_text(encoding="utf-8", errors="replace")
    assert 'lib_id "power:+3V3_A"' not in schematic
    assert 'global_label "+3V3_A"' in schematic

    netlist_path = project_dir / "CustomRailSmoke.net"
    subprocess.run(
        [
            kicad_cli,
            "sch",
            "export",
            "netlist",
            str(schematic_path),
            "--output",
            str(netlist_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    netlist = netlist_path.read_text(encoding="utf-8", errors="replace")
    assert '(name "+3V3_A")' in netlist
    assert '(ref "R1")' in netlist


@pytest.mark.anyio
@pytest.mark.slow
async def test_sch_build_circuit_resolves_project_sym_lib_table_symbol_pins(
    tmp_path: Path,
) -> None:
    """Project-local sym-lib-table symbols must be terminalized by sch_build_circuit.

    Library tools already discover project libraries through sym-lib-table.  The
    schematic builder must use the same lookup path; otherwise a custom IC can be
    visible to lib_get_symbol_info while every net endpoint is reported as a
    missing pin.
    """

    kicad_cli = shutil.which("kicad-cli")
    if kicad_cli is None:
        pytest.skip("kicad-cli is not installed")

    project_root = tmp_path / "project-symbol-smoke"
    server = build_server("full")
    await call_tool_text(
        server,
        "kicad_create_new_project",
        {
            "path": str(project_root),
            "name": "ProjectSymbolSmoke",
            "confirm_overwrite": True,
        },
    )
    project_dir = project_root / "ProjectSymbolSmoke"
    schematic_path = project_dir / "ProjectSymbolSmoke.kicad_sch"

    symbols_dir = project_dir / "symbols"
    symbols_dir.mkdir()
    local_symbol = symbols_dir / "LocalLib.kicad_sym"
    local_symbol.write_text(
        """
(kicad_symbol_lib (version 20250316) (generator pytest)
  (symbol "LocalIC"
    (property "Reference" "U" (id 0) (at 0 5.08 0))
    (property "Value" "LocalIC" (id 1) (at 0 -5.08 0))
    (property "Footprint" "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm" (id 2) (at 0 0 0))
    (property "Datasheet" "~" (id 3) (at 0 0 0))
    (symbol "LocalIC_1_1"
      (rectangle (start -7.62 -5.08) (end 7.62 5.08)
        (stroke (width 0.15) (type default))
        (fill (type background))
      )
      (pin passive line (at -10.16 0 0) (length 2.54) (name "IN") (number "1"))
      (pin passive line (at 10.16 0 180) (length 2.54) (name "OUT") (number "2"))
    )
  )
)
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (project_dir / "sym-lib-table").write_text(
        "(sym_lib_table\n"
        '  (lib (name "LocalLib") (type "KiCad") '
        '(uri "${KIPRJMOD}/symbols/LocalLib.kicad_sym") (options "") (descr ""))\n'
        ")\n",
        encoding="utf-8",
    )

    result = await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "LocalLib",
                    "symbol_name": "LocalIC",
                    "reference": "U1",
                    "value": "LocalIC",
                    "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
                }
            ],
            "wires": [],
            "labels": [],
            "power_symbols": [],
            "nets": [
                {"name": "LOCAL_IN", "endpoints": ["U1.1"]},
                {"name": "LOCAL_OUT", "endpoints": ["U1.OUT"]},
            ],
            "auto_layout": True,
        },
    )

    assert "pin '1' was not found" not in result
    assert "pin 'OUT' was not found" not in result
    assert "could not" not in result.lower()

    netlist_path = project_dir / "ProjectSymbolSmoke.net"
    subprocess.run(
        [
            kicad_cli,
            "sch",
            "export",
            "netlist",
            str(schematic_path),
            "--output",
            str(netlist_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    netlist = netlist_path.read_text(encoding="utf-8", errors="replace")
    assert '(ref "U1")' in netlist
    assert '(name "LOCAL_IN")' in netlist
    assert '(name "LOCAL_OUT")' in netlist


@pytest.mark.anyio
@pytest.mark.slow
async def test_inherited_thvd1450_symbol_matches_native_kicad_library(tmp_path: Path) -> None:
    """KiCad ERC must agree with the MCP-embedded inherited symbol definition.

    THVD1450D inherits through MAX481E and adds its own Manufacturer property.
    A copied symbol missing this field previously triggered lib_symbol_mismatch.
    """
    from kicad_mcp.tools.schematic import _symbol_library_file

    kicad_cli = shutil.which("kicad-cli")
    if kicad_cli is None or _symbol_library_file("Interface_UART") is None:
        pytest.skip("native KiCad CLI and official symbol libraries are required")

    project_root = tmp_path / "inherited-symbol-smoke"
    server = build_server("schematic")
    await call_tool_text(
        server,
        "kicad_create_new_project",
        {"path": str(project_root), "name": "DerivedSmoke"},
    )
    project_dir = project_root / "DerivedSmoke"
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(project_dir)})
    result = await call_tool_text(
        server,
        "sch_add_symbol",
        {
            "library": "Interface_UART",
            "symbol_name": "THVD1450D",
            "reference": "U1",
            "value": "THVD1450D",
            "footprint": "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
            "x_mm": 101.6,
            "y_mm": 101.6,
        },
    )
    assert "No schematic file" not in result
    schematic = project_dir / "DerivedSmoke.kicad_sch"
    assert '(property "Manufacturer" "Texas Instruments"' in schematic.read_text(encoding="utf-8")

    erc_report = tmp_path / "inherited-symbol-erc.rpt"
    # Reuse the existing bounded, shell-free native KiCad CLI smoke runner.
    from tests.integration.test_kicad_cli_smoke import _run_kicad_cli

    completed = _run_kicad_cli(Path(kicad_cli), "sch", "erc", "-o", str(erc_report), str(schematic))
    # A one-symbol schematic intentionally has other unconnected/power ERC errors.
    assert completed.returncode in (0, 5), completed.stderr
    report = erc_report.read_text(encoding="utf-8")
    assert "[lib_symbol_issues]" not in report  # the reference library must load
    assert "[lib_symbol_mismatch]" not in report
    assert "[pin_not_connected]" in report
