from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from kicad_mcp.tools.validation import GateOutcome
from tests.conftest import call_tool_text


def _child_sheet_with_hierarchical_label(name: str) -> str:
    return (
        "(kicad_sch\n"
        "\t(version 20250316)\n"
        '\t(generator "pytest")\n'
        '\t(uuid "11111111-1111-1111-1111-111111111111")\n'
        '\t(paper "A4")\n'
        "\t(lib_symbols)\n"
        f'\t(hierarchical_label "{name}"\n'
        "\t\t(shape input)\n"
        "\t\t(at 10.16 10.16 0)\n"
        "\t\t(effects (font (size 1.27 1.27)))\n"
        '\t\t(uuid "22222222-2222-2222-2222-222222222222")\n'
        "\t)\n"
        "\t(wire (pts (xy 10.16 10.16) (xy 20.32 10.16))\n"
        '\t\t(uuid "33333333-3333-3333-3333-333333333333")\n'
        "\t)\n"
        "\t(sheet_instances\n"
        '\t\t(path "/" (page "1"))\n'
        "\t)\n"
        "\t(embedded_fonts no)\n"
        ")\n"
    )


async def _inject_sheet_pin(server: object, pin_name: str) -> None:
    """Create the sheet pin the gate demands, through the tool that now exists.

    ``pin_name`` is unused by the call itself -- the import derives every pin
    from whatever hierarchical labels the child sheet currently exposes, not
    from a name the caller hands it. It stays a parameter so each call site
    still documents which pin it expects the import to produce.
    """
    _ = pin_name
    await call_tool_text(server, "sch_import_sheet_pins", {})


@pytest.mark.anyio
async def test_schematic_connectivity_gate_passes_for_connected_flat_net(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.16,
                    "y_mm": 10.16,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 20.32,
                    "y_mm": 10.16,
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
        },
    )
    await call_tool_text(
        server,
        "sch_route_wire_between_pins",
        {"ref1": "R1", "pin1": "2", "ref2": "R2", "pin2": "1"},
    )
    await call_tool_text(
        server,
        "sch_add_global_label",
        {"text": "IN", "x_mm": 7.62, "y_mm": 10.16, "shape": "input"},
    )
    await call_tool_text(
        server,
        "sch_add_global_label",
        {"text": "OUT", "x_mm": 22.86, "y_mm": 10.16, "shape": "output"},
    )

    text = await call_tool_text(server, "schematic_connectivity_gate", {})

    assert "Schematic connectivity quality gate: PASS" in text
    assert "Zero-wire pages: 0" in text
    assert "Unnamed single-pin groups: 0" in text
    assert "Isolated footprint symbols: 0" in text


@pytest.mark.anyio
async def test_schematic_connectivity_gate_ignores_explicit_no_connect_pins(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.16,
                    "y_mm": 10.16,
                    "reference": "R1",
                    "value": "10k",
                },
            ],
        },
    )
    await call_tool_text(server, "sch_add_no_connect", {"x_mm": 7.62, "y_mm": 10.16})
    await call_tool_text(server, "sch_add_no_connect", {"x_mm": 12.7, "y_mm": 10.16})

    text = await call_tool_text(server, "schematic_connectivity_gate", {})

    assert "Schematic connectivity quality gate: PASS" in text
    assert "Unnamed single-pin groups: 0" in text
    graph = await call_tool_text(server, "sch_get_connectivity_graph", {})
    assert "~no-connect" in graph
    assert "~unnamed" not in graph


@pytest.mark.anyio
async def test_schematic_connectivity_gate_fails_for_label_only_page(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.16,
                    "y_mm": 10.16,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 20.32,
                    "y_mm": 10.16,
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
        },
    )
    await call_tool_text(
        server,
        "sch_add_global_label",
        {"text": "VIN", "x_mm": 40.64, "y_mm": 40.64, "shape": "input"},
    )
    await call_tool_text(
        server,
        "sch_add_global_label",
        {"text": "VOUT", "x_mm": 45.72, "y_mm": 40.64, "shape": "output"},
    )

    text = await call_tool_text(server, "schematic_connectivity_gate", {})

    assert "Schematic connectivity quality gate: FAIL" in text
    assert "Zero-wire pages: 1" in text
    assert "Dangling label groups:" in text
    assert "not ready for PCB or release work" in text


@pytest.mark.anyio
async def test_schematic_connectivity_gate_passes_matching_hierarchy_contract(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "sch_create_sheet",
        {"name": "Power", "filename": "power.kicad_sch", "x_mm": 40.64, "y_mm": 50.8},
    )

    (sample_project / "power.kicad_sch").write_text(
        _child_sheet_with_hierarchical_label("VIN"),
        encoding="utf-8",
    )
    await _inject_sheet_pin(server, "VIN")

    text = await call_tool_text(server, "schematic_connectivity_gate", {})

    assert "Schematic connectivity quality gate: PASS" in text
    assert "Hierarchy contract mismatches: 0" in text


@pytest.mark.anyio
async def test_schematic_connectivity_gate_fails_hierarchy_contract_mismatch(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "sch_create_sheet",
        {"name": "Power", "filename": "power.kicad_sch", "x_mm": 40.64, "y_mm": 50.8},
    )

    # Import while the child still exposes VOUT, so the parent gets a real
    # sheet pin for it -- then let the child drift to VIN afterwards, without
    # re-running the import. That stale-pin scenario is exactly what the
    # hierarchy contract check exists to catch.
    (sample_project / "power.kicad_sch").write_text(
        _child_sheet_with_hierarchical_label("VOUT"),
        encoding="utf-8",
    )
    await _inject_sheet_pin(server, "VOUT")
    (sample_project / "power.kicad_sch").write_text(
        _child_sheet_with_hierarchical_label("VIN"),
        encoding="utf-8",
    )

    text = await call_tool_text(server, "schematic_connectivity_gate", {})

    assert "Schematic connectivity quality gate: FAIL" in text
    assert "Hierarchy contract mismatch for 'Power'" in text


@pytest.mark.anyio
async def test_project_quality_gate_includes_connectivity_failures(
    sample_project: Path,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = mock_kicad
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_schematic_gate",
        lambda: GateOutcome(
            name="Schematic",
            status="PASS",
            summary="ERC is clean.",
            details=["ERC violations: 0"],
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_pcb_gate",
        lambda: GateOutcome(
            name="PCB",
            status="PASS",
            summary="PCB passes DRC, unconnected, and courtyard checks.",
            details=["DRC violations: 0"],
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_pcb_placement_gate",
        lambda: GateOutcome(
            name="Placement",
            status="PASS",
            summary="Footprint placement is geometrically sane.",
            details=["Overlaps: 0"],
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_manufacturing_gate",
        lambda **_kwargs: GateOutcome(
            name="Manufacturing",
            status="PASS",
            summary="DFM checks passed.",
            details=["Profile: JLCPCB / standard"],
        ),
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._footprint_parity_outcome",
        lambda: GateOutcome(
            name="Footprint parity",
            status="PASS",
            summary="PCB and schematic references are aligned.",
            details=["Missing on board: 0"],
        ),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    await call_tool_text(
        server,
        "sch_build_circuit",
        {
            "symbols": [
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 10.16,
                    "y_mm": 10.16,
                    "reference": "R1",
                    "value": "10k",
                    "footprint": "Resistor_SMD:R_0805",
                },
                {
                    "library": "Device",
                    "symbol_name": "R",
                    "x_mm": 20.32,
                    "y_mm": 10.16,
                    "reference": "R2",
                    "value": "22k",
                    "footprint": "Resistor_SMD:R_0805",
                },
            ],
        },
    )
    await call_tool_text(
        server,
        "sch_add_global_label",
        {"text": "VIN", "x_mm": 40.64, "y_mm": 40.64, "shape": "input"},
    )

    text = await call_tool_text(server, "project_quality_gate", {})

    assert "Schematic connectivity quality gate: FAIL" in text


@pytest.mark.anyio
async def test_schematic_connectivity_gate_flags_component_contract_violation(
    sample_project: Path,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = mock_kicad
    server = build_server("schematic")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    monkeypatch.setattr("kicad_mcp.tools.validation._sheet_contracts", lambda _path: [])
    monkeypatch.setattr(
        "kicad_mcp.tools.schematic.parse_schematic_file",
        lambda _path: {
            "symbols": [
                {
                    "reference": "U1",
                    "value": "ESP32-S3-WROOM-1",
                    "footprint": "RF_Module:ESP32-S3-WROOM-1",
                    "lib_id": "RF_Module:ESP32-S3-WROOM-1",
                }
            ],
            "power_symbols": [],
            "labels": [],
            "wires": [],
        },
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.schematic._connectivity_groups_from_data",
        lambda _data, _content: [
            {
                "names": ["GND"],
                "points": [(0.0, 0.0)],
                "pins": [{"reference": "U1", "pin": "1", "value": "ESP32-S3-WROOM-1"}],
            }
        ],
    )

    text = await call_tool_text(server, "schematic_connectivity_gate", {})

    assert "Schematic connectivity quality gate: FAIL" in text
    assert "Matched component contracts: 1" in text
    assert "Component contract violations: 1" in text
    assert "esp32_s3_wroom_1" in text


def test_connectivity_page_parses_once_and_observes_external_edits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    from kicad_mcp.tools import schematic, validation

    page = tmp_path / "test.kicad_sch"
    page.write_text(_child_sheet_with_hierarchical_label("NET_A"), encoding="utf-8")
    original_parse = schematic.parse_schematic_file
    observed: list[str] = []

    def counted_parse(path: Path) -> dict:
        data = original_parse(path)
        observed.extend(label["name"] for label in data["labels"])
        return data

    monkeypatch.setattr(schematic, "parse_schematic_file", counted_parse)

    def analyze() -> list[str]:
        blocked: list[str] = []
        validation._analyze_single_page_connectivity(
            "Top",
            page,
            validation._ConnectivityGateCounters(),
            sheet_keys_by_path={},
            has_sheet_contract=False,
            required_sheet_keys=set(),
            optional_sheet_keys=set(),
            blocked=blocked,
            failures=[],
            page_summaries=[],
        )
        return blocked

    assert analyze() == []
    assert observed == ["NET_A"]
    original_stat = page.stat()
    page.write_text(_child_sheet_with_hierarchical_label("NET_B"), encoding="utf-8")
    os.utime(page, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert analyze() == []
    assert observed == ["NET_A", "NET_B"]


def test_connectivity_page_blocks_edit_during_parse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.tools import schematic, validation

    page = tmp_path / "test.kicad_sch"
    page.write_text(_child_sheet_with_hierarchical_label("NET_A"), encoding="utf-8")
    original_parse = schematic.parse_schematic_file

    def changing_parse(path: Path) -> dict:
        data = original_parse(path)
        path.write_text(_child_sheet_with_hierarchical_label("NET_B"), encoding="utf-8")
        return data

    monkeypatch.setattr(schematic, "parse_schematic_file", changing_parse)
    blocked: list[str] = []
    summaries: list[str] = []
    validation._analyze_single_page_connectivity(
        "Top",
        page,
        validation._ConnectivityGateCounters(),
        sheet_keys_by_path={},
        has_sheet_contract=False,
        required_sheet_keys=set(),
        optional_sheet_keys=set(),
        blocked=blocked,
        failures=[],
        page_summaries=summaries,
    )
    assert blocked and "changed during" in blocked[0]
    assert summaries == []


def test_checked_analysis_matches_legacy_groups_and_blocks_removed_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kicad_mcp.tools import schematic

    page = tmp_path / "test.kicad_sch"
    page.write_text(_child_sheet_with_hierarchical_label("NET_A"), encoding="utf-8")
    expected_data = schematic.parse_schematic_file(page)
    expected_groups = schematic.build_connectivity_groups(page)
    data, groups = schematic.analyze_schematic_file(page)
    assert data == expected_data
    assert groups == expected_groups

    original_parse = schematic.parse_schematic_file

    def remove_after_parse(path: Path) -> dict:
        data = original_parse(path)
        path.unlink()
        return data

    monkeypatch.setattr(schematic, "parse_schematic_file", remove_after_parse)
    with pytest.raises(schematic.SchematicChangedDuringAnalysisError, match="changed during"):
        schematic.analyze_schematic_file(page)
