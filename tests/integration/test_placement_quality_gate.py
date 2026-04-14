from __future__ import annotations

from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


def _footprint_block(
    reference: str,
    value: str,
    x_mm: float,
    y_mm: float,
    *,
    name: str = "Resistor_SMD:R_0805",
    width_mm: float = 4.0,
    height_mm: float = 2.0,
    net_name: str = "",
) -> str:
    half_w = width_mm / 2
    half_h = height_mm / 2
    net_clause = f' (net 1 "{net_name}")' if net_name else ""
    return (
        f'\t(footprint "{name}"\n'
        '\t\t(layer "F.Cu")\n'
        f"\t\t(at {x_mm:.2f} {y_mm:.2f} 0)\n"
        f'\t\t(property "Reference" "{reference}" (at 0 0 0) (layer "F.SilkS"))\n'
        f'\t\t(property "Value" "{value}" (at 0 1 0) (layer "F.Fab"))\n'
        f'\t\t(fp_rect (start {-half_w:.2f} {-half_h:.2f}) (end {half_w:.2f} {half_h:.2f}) '
        '(stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))\n'
        f'\t\t(pad "1" smd rect (at 0 0) (size 1 1) '
        f'(layers "F.Cu" "F.Mask" "F.Paste"){net_clause})\n'
        "\t)\n"
    )


def _write_board(sample_project: Path, *footprints: str) -> None:
    (sample_project / "demo.kicad_pcb").write_text(
        (
            "(kicad_pcb\n"
            '\t(version 20250216)\n'
            '\t(generator "pytest")\n'
            '\t(gr_rect (start 0 0) (end 40 30) (stroke (width 0.05) (type solid)) '
            '(fill no) (layer "Edge.Cuts"))\n'
            + "".join(footprints)
            + ")\n"
        ),
        encoding="utf-8",
    )


@pytest.mark.anyio
async def test_project_design_intent_roundtrip(sample_project: Path, mock_kicad) -> None:
    _ = mock_kicad
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    stored = await call_tool_text(
        server,
        "project_set_design_intent",
        {
            "connector_refs": ["J1"],
            "decoupling_pairs": [{"ic_ref": "U1", "cap_refs": ["C1"], "max_distance_mm": 4.0}],
            "critical_nets": ["USB_DP"],
            "power_tree_refs": ["J1", "U1"],
            "analog_refs": ["U2"],
            "digital_refs": ["U1"],
            "sensor_cluster_refs": ["U2", "U3"],
            "rf_keepout_regions": [
                {"name": "Antenna", "x_mm": 30.0, "y_mm": 10.0, "w_mm": 8.0, "h_mm": 6.0}
            ],
            "manufacturer": "JLCPCB",
            "manufacturer_tier": "standard",
        },
    )
    fetched = await call_tool_text(server, "project_get_design_intent", {})

    assert "Stored project design intent" in stored
    assert "Connector refs: J1" in fetched
    assert "U1 <- C1" in fetched
    assert "Power-tree refs: J1, U1" in fetched
    assert "Analog refs: U2" in fetched
    assert "Digital refs: U1" in fetched
    assert "Sensor cluster refs: U2, U3" in fetched
    assert "Antenna" in fetched
    assert "JLCPCB / standard" in fetched


@pytest.mark.anyio
async def test_pcb_placement_quality_gate_fails_connector_distance(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    _write_board(
        sample_project,
        _footprint_block("J1", "Conn", 20.0, 15.0, name="Connector_Generic:Conn_01x02"),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(server, "project_set_design_intent", {"connector_refs": ["J1"]})

    gate = await call_tool_text(server, "pcb_placement_quality_gate", {})
    score = await call_tool_text(server, "pcb_score_placement", {})

    assert "Placement quality gate: FAIL" in gate
    assert "Connector 'J1' is" in gate
    assert "Placement score:" in score
    assert "FAIL: Connector 'J1' is" in score


@pytest.mark.anyio
async def test_pcb_placement_quality_gate_fails_decoupling_distance(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    _write_board(
        sample_project,
        _footprint_block("U1", "MCU", 10.0, 10.0, name="Package_QFP:TQFP-48"),
        _footprint_block("C1", "100n", 30.0, 20.0, name="Capacitor_SMD:C_0603"),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "project_set_design_intent",
        {"decoupling_pairs": [{"ic_ref": "U1", "cap_refs": ["C1"], "max_distance_mm": 4.0}]},
    )

    gate = await call_tool_text(server, "pcb_placement_quality_gate", {})

    assert "Placement quality gate: FAIL" in gate
    assert "nearest decoupling cap is" in gate


@pytest.mark.anyio
async def test_pcb_placement_quality_gate_fails_rf_keepout_overlap(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    _write_board(
        sample_project,
        _footprint_block("U1", "RF", 30.0, 10.0, name="RF_Module:ESP32"),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "project_set_design_intent",
        {
            "rf_keepout_regions": [
                {"name": "Antenna", "x_mm": 30.0, "y_mm": 10.0, "w_mm": 10.0, "h_mm": 8.0}
            ]
        },
    )

    gate = await call_tool_text(server, "pcb_placement_quality_gate", {})

    assert "Placement quality gate: FAIL" in gate
    assert "overlaps RF keepout 'Antenna'" in gate


@pytest.mark.anyio
async def test_pcb_placement_quality_gate_passes_clean_intent_aware_board(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    _write_board(
        sample_project,
        _footprint_block(
            "J1",
            "Conn",
            2.0,
            15.0,
            name="Connector_Generic:Conn_01x02",
            width_mm=3.0,
            height_mm=5.0,
            net_name="USB_DP",
        ),
        _footprint_block(
            "U1",
            "MCU",
            12.0,
            15.0,
            name="Package_QFP:TQFP-48",
            width_mm=6.0,
            height_mm=6.0,
            net_name="USB_DP",
        ),
        _footprint_block(
            "C1",
            "100n",
            16.0,
            15.0,
            name="Capacitor_SMD:C_0603",
            width_mm=2.0,
            height_mm=1.2,
        ),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "project_set_design_intent",
        {
            "connector_refs": ["J1"],
            "decoupling_pairs": [{"ic_ref": "U1", "cap_refs": ["C1"], "max_distance_mm": 4.0}],
            "critical_nets": ["USB_DP"],
            "power_tree_refs": ["J1", "U1", "C1"],
            "sensor_cluster_refs": ["U1", "C1"],
            "rf_keepout_regions": [
                {"name": "Antenna", "x_mm": 32.0, "y_mm": 6.0, "w_mm": 6.0, "h_mm": 4.0}
            ],
        },
    )

    gate = await call_tool_text(server, "pcb_placement_quality_gate", {})
    score = await call_tool_text(server, "pcb_score_placement", {})

    assert "Placement quality gate: PASS" in gate
    assert "Placement score:" in score
    assert "- Hard failures: 0" in score
    assert "- Power-tree refs checked: 3" in score
    assert "- Analog refs checked: 0" in score
    assert "- Sensor-cluster refs checked: 2" in score


@pytest.mark.anyio
async def test_pcb_placement_quality_gate_fails_power_tree_locality(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    _write_board(
        sample_project,
        _footprint_block("J1", "USB", 2.0, 2.0, name="Connector_USB:USB_C_Receptacle_USB2.0_16P"),
        _footprint_block("U1", "LDO", 38.0, 28.0, name="Package_TO_SOT_SMD:SOT-23-5"),
        _footprint_block("U2", "MCU", 38.0, 2.0, name="Package_QFP:TQFP-48"),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "project_set_design_intent",
        {"power_tree_refs": ["J1", "U1", "U2"]},
    )

    gate = await call_tool_text(server, "pcb_placement_quality_gate", {})
    score = await call_tool_text(server, "pcb_score_placement", {})

    assert "Placement quality gate: FAIL" in gate
    assert "Power-tree step 'J1 -> U1' spans" in gate
    assert "FAIL: Power-tree step 'J1 -> U1' spans" in score


@pytest.mark.anyio
async def test_pcb_placement_quality_gate_fails_sensor_cluster_spread(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    _write_board(
        sample_project,
        _footprint_block("U1", "SensorA", 3.0, 3.0, name="Sensor_Motion:ADXL355"),
        _footprint_block("U2", "SensorB", 37.0, 27.0, name="Sensor:BME280"),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "project_set_design_intent",
        {"sensor_cluster_refs": ["U1", "U2"]},
    )

    gate = await call_tool_text(server, "pcb_placement_quality_gate", {})

    assert "Placement quality gate: FAIL" in gate
    assert "Sensor cluster spreads" in gate


@pytest.mark.anyio
async def test_pcb_placement_quality_gate_flags_analog_digital_proximity(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    _write_board(
        sample_project,
        _footprint_block("U1", "AFE", 10.0, 10.0, name="Amplifier_Operational:MCP6002"),
        _footprint_block("U2", "MCU", 14.2, 10.0, name="Package_QFP:TQFP-48"),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "project_set_design_intent",
        {"analog_refs": ["U1"], "digital_refs": ["U2"]},
    )

    gate = await call_tool_text(server, "pcb_placement_quality_gate", {})

    assert "Placement quality gate: FAIL" in gate
    assert "Analog ref 'U1' is only" in gate
