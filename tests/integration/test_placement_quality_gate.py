from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from kicad_mcp.server import build_server
from tests.conftest import call_tool_payload, call_tool_text


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
        f"\t\t(fp_rect (start {-half_w:.2f} {-half_h:.2f}) (end {half_w:.2f} {half_h:.2f}) "
        '(stroke (width 0.05) (type solid)) (fill no) (layer "F.CrtYd"))\n'
        f'\t\t(pad "1" smd rect (at 0 0) (size 1 1) '
        f'(layers "F.Cu" "F.Mask" "F.Paste"){net_clause})\n'
        "\t)\n"
    )


def _write_board(sample_project: Path, *footprints: str) -> None:
    (sample_project / "demo.kicad_pcb").write_text(
        (
            "(kicad_pcb\n"
            "\t(version 20250216)\n"
            '\t(generator "pytest")\n'
            "\t(gr_rect (start 0 0) (end 40 30) (stroke (width 0.05) (type solid)) "
            '(fill no) (layer "Edge.Cuts"))\n' + "".join(footprints) + ")\n"
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
    spec_path = sample_project / ".kicad-mcp" / "project_spec.json"

    assert "Stored project design spec" in stored
    assert "Connector refs: J1" in fetched
    assert "U1 <- C1" in fetched
    assert "Power-tree refs: J1, U1" in fetched
    assert "Analog refs: U2" in fetched
    assert "Digital refs: U1" in fetched
    assert "Sensor cluster refs: U2, U3" in fetched
    assert "Antenna" in fetched
    assert "JLCPCB / standard" in fetched
    assert spec_path.exists()


@pytest.mark.anyio
async def test_project_design_spec_infers_decoupling_and_sensor_clusters(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    _write_board(
        sample_project,
        _footprint_block(
            "U1",
            "MCU",
            10.0,
            10.0,
            name="Package_QFP:TQFP-48",
            width_mm=6.0,
            height_mm=6.0,
        ),
        _footprint_block("C1", "100n", 34.0, 24.0, name="Capacitor_SMD:C_0603"),
        _footprint_block(
            "U2",
            "SensorA",
            3.0,
            3.0,
            name="Sensor_Motion:ADXL355",
            width_mm=4.0,
            height_mm=4.0,
        ),
        _footprint_block(
            "U3",
            "SensorB",
            37.0,
            27.0,
            name="Sensor:BME280",
            width_mm=4.0,
            height_mm=4.0,
        ),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    payload = await call_tool_payload(server, "project_get_design_spec", {})

    assert isinstance(payload, dict)
    resolved = payload["resolved"]
    inferred = payload["inferred"]
    assert payload["source"] == "none"
    assert inferred["decoupling_pairs"][0]["ic_ref"] == "U1"
    assert inferred["sensor_cluster_refs"] == ["U2", "U3"]
    assert resolved["decoupling_pairs"][0]["cap_refs"] == ["C1"]
    assert resolved["sensor_cluster_refs"] == ["U2", "U3"]


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
async def test_pcb_placement_quality_gate_warns_on_centroid_only_decoupling_distance(
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

    assert "Placement quality gate: WARN" in gate
    assert "nearest decoupling cap is" in gate
    assert "footprint-center proxy" in gate
    assert "power-pad geometry unavailable" in gate


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
            net_name="/3V3",
        ),
        _footprint_block(
            "C1",
            "100n",
            16.0,
            15.0,
            name="Capacitor_SMD:C_0603",
            width_mm=2.0,
            height_mm=1.2,
            net_name="3V3",
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
    assert "- Critical-net Manhattan proxy:" in score
    assert "- Thermal hotspot proximity:" in score


@pytest.mark.anyio
async def test_pcb_score_placement_reports_signal_length_proxy(
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
            net_name="USB_DP",
        ),
        _footprint_block(
            "U1",
            "MCU",
            20.0,
            15.0,
            name="Package_QFP:TQFP-48",
            net_name="USB_DP",
        ),
        _footprint_block(
            "U2",
            "PHY",
            38.0,
            15.0,
            name="Package_SO:SOIC-8",
            net_name="USB_DP",
        ),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(server, "project_set_design_intent", {"critical_nets": ["USB_DP"]})

    score = await call_tool_text(server, "pcb_score_placement", {})

    assert "- Critical-net Manhattan proxy: 36.00 mm" in score
    assert "- Critical-net proxy density: 30.00 mm per 1000 mm^2" in score


@pytest.mark.anyio
async def test_pcb_score_placement_warns_on_tight_thermal_hotspots(
    sample_project: Path,
    mock_kicad,
) -> None:
    _ = mock_kicad
    _write_board(
        sample_project,
        _footprint_block("U1", "HotA", 10.0, 10.0, name="Package_SO:SOIC-8"),
        _footprint_block("U2", "HotB", 14.5, 10.0, name="Package_SO:SOIC-8"),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(server, "project_set_design_intent", {"thermal_hotspots": ["U1", "U2"]})

    score = await call_tool_text(server, "pcb_score_placement", {})

    assert "- Thermal hotspot refs checked: 2" in score
    assert "- Thermal hotspot proximity: 0.2222" in score
    assert "WARN: Thermal hotspots are clustered tightly" in score


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


# ---------------------------------------------------------------------------
# pcb_critique_placement (issue #203)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_pcb_critique_placement_empty_board(
    sample_project: Path,
    mock_kicad,
) -> None:
    """Empty board returns pass verdict with no findings."""
    _ = mock_kicad
    import json

    _write_board(sample_project)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "pcb_critique_placement", {})
    payload = json.loads(result)

    assert payload["verdict"] in {"pass", "empty_board"}
    assert payload.get("finding_count", 0) == 0


@pytest.mark.anyio
async def test_pcb_critique_placement_decap_far_from_ic(
    sample_project: Path,
    mock_kicad,
) -> None:
    """PLR-001 fires when a decoupling cap is > 5 mm from all ICs."""
    _ = mock_kicad
    import json

    _write_board(
        sample_project,
        _footprint_block("U1", "STM32F4", 0.0, 0.0),
        _footprint_block("C1", "100nF", 30.0, 0.0),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "pcb_critique_placement", {})
    payload = json.loads(result)

    assert payload["status"] == "ok"
    plr001 = [f for f in payload["findings"] if f["rule_id"] == "PLR-001"]
    assert len(plr001) == 1
    assert "C1" in plr001[0]["refs"]
    assert plr001[0]["distance_mm"] > 5.0
    assert payload["verdict"] == "warn"


@pytest.mark.anyio
async def test_pcb_critique_placement_crystal_far_from_ic(
    sample_project: Path,
    mock_kicad,
) -> None:
    """PLR-002 fires when a crystal is > 8 mm from all ICs."""
    _ = mock_kicad
    import json

    _write_board(
        sample_project,
        _footprint_block("U1", "STM32F4", 0.0, 0.0),
        _footprint_block("Y1", "16MHz", 50.0, 0.0),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "pcb_critique_placement", {})
    payload = json.loads(result)

    plr002 = [f for f in payload["findings"] if f["rule_id"] == "PLR-002"]
    assert len(plr002) == 1
    assert "Y1" in plr002[0]["refs"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("left_rail", "right_rail"),
    [("+3V3", "+5V"), ("+5V", "+5V")],
)
async def test_inferred_connectors_do_not_form_unrequested_power_tree(
    sample_project: Path,
    mock_kicad,
    left_rail: str,
    right_rail: str,
) -> None:
    _ = mock_kicad
    board = sample_project / "demo.kicad_pcb"
    board.write_text(
        '(kicad_pcb (version 20250216) (generator "pytest")\n'
        "  (gr_rect (start 0 0) (end 85 25) "
        '(stroke (width 0.05) (type solid)) (fill no) (layer "Edge.Cuts"))\n'
        + _footprint_block(
            "J1",
            "Input",
            5.0,
            12.5,
            name="Connector_Generic:Conn_01x02",
            net_name=left_rail,
        )
        + _footprint_block(
            "J2",
            "Output",
            80.0,
            12.5,
            name="Connector_Generic:Conn_01x02",
            net_name=right_rail,
        )
        + ")\n",
        encoding="utf-8",
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    spec = await call_tool_payload(server, "project_get_design_spec", {})
    assert isinstance(spec, dict)
    assert spec["inferred"]["connector_refs"] == ["J1", "J2"]
    assert spec["resolved"]["power_tree_refs"] == []

    gate = await call_tool_text(server, "pcb_placement_quality_gate", {})
    score = await call_tool_text(server, "pcb_score_placement", {})
    assert "Power-tree step" not in gate
    assert "Power-tree step" not in score


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("distance", "with_intent", "expected_status"),
    [(6, False, "PASS"), (6, True, "PASS"), (20, True, "WARN"), (30, True, "FAIL")],
)
async def test_placement_report_serializes_one_measured_snapshot(
    sample_project: Path,
    mock_kicad,
    monkeypatch: pytest.MonkeyPatch,
    distance: int,
    with_intent: bool,
    expected_status: str,
) -> None:
    from kicad_mcp.tools import validation
    from kicad_mcp.tools.design_intent_state import ProjectDesignIntent

    _write_board(
        sample_project,
        _footprint_block("R1", "10k", 5, 10, net_name="DATA"),
        _footprint_block("R2", "10k", 5 + distance, 10, net_name="DATA"),
    )
    intent = ProjectDesignIntent.model_validate(
        {
            "critical_nets": ["DATA"] if with_intent else [],
            "thermal_hotspots": ["R1", "R2"] if with_intent else [],
            "interfaces": [{"kind": "custom", "refs": ["R1", "R2"]}] if with_intent else [],
        }
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.design_intent_state.resolve_design_intent",
        lambda: SimpleNamespace(resolved=intent),
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    original = validation._placement_analysis
    snapshots = []

    def evaluate_once():
        result = original()
        snapshots.append(result)
        return result

    monkeypatch.setattr(validation, "_placement_analysis", evaluate_once)
    payload = await call_tool_payload(server, "pcb_placement_quality_report", {})
    assert isinstance(payload, dict)
    assert len(snapshots) == 1
    analysis, blocked = snapshots[0]
    assert blocked is None
    assert analysis is not None
    expected_length = float(distance) if with_intent else 0.0
    expected_density = round(expected_length / 1.2, 2)
    expected_thermal = round(1 / distance, 4) if with_intent else 0.0
    assert expected_status == payload["status"]
    assert expected_length == payload["critical_net_proxy_mm"]
    assert expected_density == payload["critical_net_proxy_density"]
    assert (2 if with_intent else 0) == payload["checked_thermal_hotspot_refs"]
    assert expected_thermal == payload["thermal_proximity_sum"]
    assert int(with_intent) == payload["checked_hs_interfaces"]
    assert analysis.score == payload["score"]
    assert analysis.hard_failures == payload["hard_failures"]
    assert analysis.warnings == payload["warnings"]
    assert f"Critical-net Manhattan proxy: {expected_length:.2f} mm" in payload["text"]
    assert f"Critical-net proxy density: {expected_density:.2f}" in payload["text"]
    assert f"Thermal hotspot proximity: {expected_thermal:.4f}" in payload["text"]
    assert f"High-speed interfaces checked: {int(with_intent)}" in payload["text"]
    tool = next(t for t in await server.list_tools() if t.name == "pcb_placement_quality_report")
    assert tool.output_schema is not None
    Draft202012Validator(tool.output_schema).validate(payload)
    assert payload == validation.PlacementGateReportPayload.model_validate(payload).model_dump()


@pytest.mark.anyio
@pytest.mark.parametrize("missing_file", [False, True])
async def test_placement_report_marks_unavailable_metrics_null(
    sample_project: Path, mock_kicad, monkeypatch: pytest.MonkeyPatch, missing_file: bool
) -> None:
    _write_board(sample_project)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    if missing_file:
        path = sample_project / "demo.kicad_pcb"
        path.unlink()
        # Model a file disappearing after successful project path resolution.
        monkeypatch.setattr("kicad_mcp.tools.validation._get_pcb_file", lambda: path)
    payload = await call_tool_payload(server, "pcb_placement_quality_report", {})
    assert isinstance(payload, dict)
    assert payload["status"] == "BLOCKED"
    for field in (
        "score",
        "footprint_count",
        "checked_connectors",
        "checked_decoupling_pairs",
        "checked_keepouts",
        "checked_power_tree_refs",
        "checked_analog_refs",
        "checked_digital_refs",
        "checked_sensor_cluster_refs",
        "critical_net_proxy_mm",
        "critical_net_proxy_density",
        "checked_thermal_hotspot_refs",
        "thermal_proximity_sum",
        "checked_hs_interfaces",
    ):
        assert payload[field] is None
    tool = next(t for t in await server.list_tools() if t.name == "pcb_placement_quality_report")
    assert tool.output_schema is not None
    Draft202012Validator(tool.output_schema).validate(payload)
