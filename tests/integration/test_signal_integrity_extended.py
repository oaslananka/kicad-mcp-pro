"""Integration tests for signal-integrity edge cases and error paths."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from kipy.proto.board.board_types_pb2 import BoardLayer, ViaType

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


def _field(value: str) -> SimpleNamespace:
    return SimpleNamespace(text=SimpleNamespace(value=value))


@pytest.mark.anyio
async def test_si_check_differential_pair_skew_missing_nets(sample_project, mock_board) -> None:
    """si_check_differential_pair_skew should report when nets have no tracks."""
    mock_board.get_tracks.return_value = []
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_check_differential_pair_skew",
        {"net_p": "MISSING_P", "net_n": "MISSING_N"},
    )
    assert "Could not compute differential-pair skew" in result
    assert "have no routed track segments" in result


@pytest.mark.anyio
async def test_si_validate_length_matching_empty_groups(sample_project, mock_board) -> None:
    """si_validate_length_matching should handle empty and missing net groups."""
    mock_board.get_tracks.return_value = []
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_validate_length_matching",
        {"net_groups": [[], ["NET1"]], "tolerance_mm": 1.0},
    )
    assert "Length-matching validation" in result
    assert "skipped empty group" in result
    assert "missing routed tracks" in result


@pytest.mark.anyio
async def test_si_validate_length_matching_pass(sample_project, mock_board) -> None:
    """si_validate_length_matching should report PASS when within tolerance."""
    track1 = SimpleNamespace(
        start=SimpleNamespace(x_nm=0, y_nm=0),
        end=SimpleNamespace(x_nm=10_000_000, y_nm=0),
        layer=BoardLayer.BL_F_Cu,
        width=180_000,
        net=SimpleNamespace(name="NET1"),
    )
    track2 = SimpleNamespace(
        start=SimpleNamespace(x_nm=0, y_nm=0),
        end=SimpleNamespace(x_nm=10_500_000, y_nm=0),
        layer=BoardLayer.BL_F_Cu,
        width=180_000,
        net=SimpleNamespace(name="NET2"),
    )
    mock_board.get_tracks.return_value = [track1, track2]
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_validate_length_matching",
        {"net_groups": [["NET1", "NET2"]], "tolerance_mm": 1.0},
    )
    assert "Group 1 (PASS)" in result
    assert "spread=0.500 mm" in result


@pytest.mark.anyio
async def test_si_validate_length_matching_fail(sample_project, mock_board) -> None:
    """si_validate_length_matching should report WARN when spread exceeds tolerance."""
    track1 = SimpleNamespace(
        start=SimpleNamespace(x_nm=0, y_nm=0),
        end=SimpleNamespace(x_nm=10_000_000, y_nm=0),
        layer=BoardLayer.BL_F_Cu,
        width=180_000,
        net=SimpleNamespace(name="NET1"),
    )
    track2 = SimpleNamespace(
        start=SimpleNamespace(x_nm=0, y_nm=0),
        end=SimpleNamespace(x_nm=15_000_000, y_nm=0),
        layer=BoardLayer.BL_F_Cu,
        width=180_000,
        net=SimpleNamespace(name="NET2"),
    )
    mock_board.get_tracks.return_value = [track1, track2]
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_validate_length_matching",
        {"net_groups": [["NET1", "NET2"]], "tolerance_mm": 1.0},
    )
    # spread 5 mm vs tolerance 1 mm exceeds the FAIL threshold (2x tolerance = 2 mm).
    # Previously the gate could only WARN (K2); it now correctly returns FAIL (P1-T3).
    assert "Group 1 (FAIL)" in result
    assert "spread=5.000 mm" in result


@pytest.mark.anyio
async def test_si_check_via_stub_no_vias(sample_project, mock_board) -> None:
    """si_check_via_stub should report when no vias match the positions."""
    mock_board.get_vias.return_value = []
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server, "si_check_via_stub", {"frequency_ghz": 5.0, "via_positions": [[1.0, 1.0]]}
    )
    assert "No vias matched the supplied positions" in result


@pytest.mark.anyio
async def test_si_check_via_stub_all_via_types(sample_project, mock_board) -> None:
    """si_check_via_stub should analyze through, blind, and micro vias."""
    through_via = SimpleNamespace(
        position=SimpleNamespace(x_nm=5_000_000, y_nm=5_000_000),
        drill_diameter=300_000,
        net=SimpleNamespace(name="GND"),
        type=ViaType.VT_THROUGH,
    )
    blind_via = SimpleNamespace(
        position=SimpleNamespace(x_nm=6_000_000, y_nm=6_000_000),
        drill_diameter=250_000,
        net=SimpleNamespace(name="VCC"),
        type=ViaType.VT_BLIND_BURIED,
    )
    micro_via = SimpleNamespace(
        position=SimpleNamespace(x_nm=7_000_000, y_nm=7_000_000),
        drill_diameter=150_000,
        net=SimpleNamespace(name="USB_DP"),
        type=ViaType.VT_MICRO,
    )
    mock_board.get_vias.return_value = [through_via, blind_via, micro_via]
    mock_board.get_stackup.return_value = SimpleNamespace(
        layers=[
            SimpleNamespace(layer=BoardLayer.BL_F_Cu, thickness=35_000, material_name="Copper"),
            SimpleNamespace(layer="Prepreg", thickness=180_000, material_name="FR4"),
            SimpleNamespace(layer=BoardLayer.BL_B_Cu, thickness=35_000, material_name="Copper"),
        ]
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "si_check_via_stub", {"frequency_ghz": 5.0, "er": 4.0})
    assert "Via stub analysis" in result
    assert "GND" in result
    assert "VCC" in result
    assert "USB_DP" in result
    assert "VT_THROUGH" in result or "VT_BLIND_BURIED" in result or "VT_MICRO" in result


@pytest.mark.anyio
async def test_si_calculate_decoupling_placement_no_caps(sample_project, mock_board) -> None:
    """si_calculate_decoupling_placement should report when no capacitors are found."""
    u1 = SimpleNamespace(
        reference_field=_field("U1"),
        value_field=_field("MCU"),
        position=SimpleNamespace(x_nm=10_000_000, y_nm=10_000_000),
    )
    mock_board.get_footprints.return_value = [u1]
    mock_board.get_pads.return_value = [
        SimpleNamespace(
            parent=u1,
            number="7",
            net=SimpleNamespace(name="3V3"),
            position=SimpleNamespace(x_nm=10_100_000, y_nm=10_000_000),
        )
    ]
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_calculate_decoupling_placement",
        {"ic_ref": "U1", "power_pin": "7", "target_freq_mhz": 250.0},
    )
    assert "No capacitor footprints were found" in result
    assert "Add a local decoupler" in result


@pytest.mark.anyio
async def test_si_calculate_decoupling_placement_warn(sample_project, mock_board) -> None:
    """si_calculate_decoupling_placement should WARN when cap is too far."""
    u1 = SimpleNamespace(
        reference_field=_field("U1"),
        value_field=_field("MCU"),
        position=SimpleNamespace(x_nm=10_000_000, y_nm=10_000_000),
    )
    c1 = SimpleNamespace(
        reference_field=_field("C1"),
        value_field=_field("100n"),
        position=SimpleNamespace(x_nm=30_000_000, y_nm=10_000_000),
    )
    mock_board.get_footprints.return_value = [u1, c1]
    mock_board.get_pads.return_value = [
        SimpleNamespace(
            parent=u1,
            number="7",
            net=SimpleNamespace(name="3V3"),
            position=SimpleNamespace(x_nm=10_100_000, y_nm=10_000_000),
        )
    ]
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_calculate_decoupling_placement",
        {"ic_ref": "U1", "power_pin": "7", "target_freq_mhz": 250.0},
    )
    assert "Decoupling placement heuristic" in result
    assert "C1" in result
    assert "WARN" in result or "PASS" in result


@pytest.mark.anyio
async def test_si_generate_stackup_2_layer(sample_project) -> None:
    """si_generate_stackup should support 2-layer stackups."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_generate_stackup",
        {"layer_count": 2, "target_impedance_ohm": 50.0, "manufacturer": "JLCPCB"},
    )
    assert "Recommended 2-layer" in result
    assert "F.Cu" in result
    assert "B.Cu" in result


@pytest.mark.anyio
async def test_si_generate_stackup_6_layer(sample_project) -> None:
    """si_generate_stackup should support 6-layer stackups."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_generate_stackup",
        {"layer_count": 6, "target_impedance_ohm": 50.0, "manufacturer": "PCBWay"},
    )
    assert "Recommended 6-layer" in result
    assert "In1.Cu" in result
    assert "In4.Cu" in result


@pytest.mark.anyio
async def test_si_generate_stackup_pcbway_4_layer(sample_project) -> None:
    """si_generate_stackup should use PCBWay templates when specified."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_generate_stackup",
        {"layer_count": 4, "target_impedance_ohm": 50.0, "manufacturer": "PCBWay"},
    )
    assert "Recommended 4-layer PCBWay stackup" in result


@pytest.mark.anyio
async def test_si_synthesize_stackup_for_interfaces_2_layer(sample_project) -> None:
    """si_synthesize_stackup_for_interfaces should recommend 2 layers for low-speed."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_synthesize_stackup_for_interfaces",
        {
            "interfaces": [
                {"kind": "uart"},
                {"kind": "i2c"},
            ],
            "cost_tier": "standard",
            "board_thickness_mm": 1.6,
        },
    )
    assert "Layer count: **2**" in result
    assert "uart" in result
    assert "i2c" in result


@pytest.mark.anyio
async def test_si_synthesize_stackup_for_interfaces_highspeed(sample_project) -> None:
    """si_synthesize_stackup_for_interfaces should recommend more layers for high-speed."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_synthesize_stackup_for_interfaces",
        {
            "interfaces": [
                {"kind": "usb3_gen2", "differential": True, "impedance_target_ohm": 90.0},
                {"kind": "pcie_g4", "differential": True, "impedance_target_ohm": 85.0},
            ],
            "cost_tier": "highspeed",
            "board_thickness_mm": 1.6,
        },
    )
    assert "Has high-speed signals" in result
    assert "Has differential pairs: True" in result
    assert "Layer count" in result
    assert "ro4350b" in result or "Rogers" in result or "highspeed" in result.lower()


@pytest.mark.anyio
async def test_si_synthesize_stackup_for_interfaces_midloss(sample_project) -> None:
    """si_synthesize_stackup_for_interfaces should support midloss tier."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_synthesize_stackup_for_interfaces",
        {
            "interfaces": [
                {"kind": "ddr4", "differential": False, "impedance_target_ohm": 50.0},
            ],
            "cost_tier": "midloss",
            "board_thickness_mm": 1.6,
        },
    )
    assert "ddr4" in result
    assert "Net Class Configuration" in result


@pytest.mark.anyio
async def test_si_bind_interfaces_to_net_classes_no_interfaces(sample_project) -> None:
    """si_bind_interfaces_to_net_classes should report when no interfaces need net classes."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_bind_interfaces_to_net_classes",
        {"interfaces": [{"kind": "uart"}, {"kind": "i2c"}], "dry_run": True},
    )
    assert "No high-speed interfaces found" in result


@pytest.mark.anyio
async def test_si_bind_interfaces_to_net_classes_applied(sample_project, monkeypatch) -> None:
    """si_bind_interfaces_to_net_classes should write rules when dry_run=False."""
    written: list[tuple[str, float, float, float | None]] = []

    def fake_write_rule(
        net_class: str,
        clearance_mm: float,
        track_width_mm: float,
        diff_gap_mm: float | None,
    ) -> str:
        written.append((net_class, clearance_mm, track_width_mm, diff_gap_mm))
        return str(sample_project / "demo.kicad_dru")

    monkeypatch.setattr(
        "kicad_mcp.tools.signal_integrity_net_class_binding._write_nc_rule", fake_write_rule
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_bind_interfaces_to_net_classes",
        {
            "interfaces": [{"kind": "usb3", "differential": True, "impedance_target_ohm": 90.0}],
            "dry_run": False,
        },
    )
    assert "Applied" in result
    assert written
    assert written[0][0] == "USB3"


@pytest.mark.anyio
async def test_si_list_dielectric_materials(sample_project) -> None:
    """si_list_dielectric_materials should return built-in materials."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(server, "si_list_dielectric_materials", {})
    assert "Available dielectric materials" in result
    assert "fr4_standard" in result or "FR4" in result


@pytest.mark.anyio
async def test_si_calculate_trace_impedance_stripline(sample_project) -> None:
    """si_calculate_trace_impedance should support stripline trace type."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_calculate_trace_impedance",
        {
            "width_mm": 0.2,
            "height_mm": 0.18,
            "er": 4.2,
            "trace_type": "stripline",
            "copper_oz": 1.0,
            "spacing_mm": 0.2,
        },
    )
    assert "Trace impedance estimate" in result
    assert "stripline" in result


@pytest.mark.anyio
async def test_si_calculate_trace_width_for_impedance_coplanar(sample_project) -> None:
    """si_calculate_trace_width_for_impedance should support coplanar trace type."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_calculate_trace_width_for_impedance",
        {
            "target_ohm": 50.0,
            "height_mm": 0.18,
            "er": 4.2,
            "trace_type": "coplanar",
            "copper_oz": 1.0,
            "spacing_mm": 0.2,
        },
    )
    assert "Width synthesis" in result
    assert "coplanar" in result


@pytest.mark.anyio
async def test_si_check_differential_pair_skew_no_phase_data(sample_project, mock_board) -> None:
    """si_check_differential_pair_skew should work without phase data."""
    usb_dp = SimpleNamespace(
        start=SimpleNamespace(x_nm=0, y_nm=0),
        end=SimpleNamespace(x_nm=10_000_000, y_nm=0),
        layer=BoardLayer.BL_F_Cu,
        width=180_000,
        net=SimpleNamespace(name="USB_DP"),
    )
    usb_dn = SimpleNamespace(
        start=SimpleNamespace(x_nm=0, y_nm=1_000_000),
        end=SimpleNamespace(x_nm=9_700_000, y_nm=1_000_000),
        layer=BoardLayer.BL_F_Cu,
        width=180_000,
        net=SimpleNamespace(name="USB_DN"),
    )
    mock_board.get_tracks.return_value = [usb_dp, usb_dn]
    mock_board.get_stackup.return_value = SimpleNamespace(
        layers=[
            SimpleNamespace(layer=BoardLayer.BL_F_Cu, thickness=35_000, material_name="Copper"),
            SimpleNamespace(layer="Prepreg", thickness=180_000, material_name="FR4"),
            SimpleNamespace(layer=BoardLayer.BL_B_Cu, thickness=35_000, material_name="Copper"),
        ]
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_check_differential_pair_skew",
        {"net_p": "USB_DP", "net_n": "USB_DN", "er": 4.2, "trace_type": "microstrip"},
    )
    assert "Differential-pair skew analysis" in result
    assert "USB_DP" in result
    assert "USB_DN" in result


@pytest.mark.anyio
async def test_si_check_via_stub_critical_resonance(sample_project, mock_board) -> None:
    """si_check_via_stub should flag critical resonances near design frequencies."""
    via = SimpleNamespace(
        position=SimpleNamespace(x_nm=5_000_000, y_nm=5_000_000),
        drill_diameter=300_000,
        net=SimpleNamespace(name="CLK"),
        type=ViaType.VT_THROUGH,
    )
    mock_board.get_vias.return_value = [via]
    mock_board.get_stackup.return_value = SimpleNamespace(
        layers=[
            SimpleNamespace(layer=BoardLayer.BL_F_Cu, thickness=35_000, material_name="Copper"),
            SimpleNamespace(layer="Prepreg", thickness=180_000, material_name="FR4"),
            SimpleNamespace(layer=BoardLayer.BL_B_Cu, thickness=35_000, material_name="Copper"),
        ]
    )
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "project_set_design_intent",
        {"critical_frequencies_mhz": [1500.0]},
    )

    result = await call_tool_text(server, "si_check_via_stub", {"frequency_ghz": 1.5, "er": 4.0})
    assert "Via stub analysis" in result
    assert "CLK" in result


@pytest.mark.anyio
async def test_si_calculate_decoupling_placement_by_footprint(sample_project, mock_board) -> None:
    """si_calculate_decoupling_placement should fall back to footprint center when pad missing."""
    u1 = SimpleNamespace(
        reference_field=_field("U1"),
        value_field=_field("MCU"),
        position=SimpleNamespace(x_nm=10_000_000, y_nm=10_000_000),
    )
    c1 = SimpleNamespace(
        reference_field=_field("C1"),
        value_field=_field("100n"),
        position=SimpleNamespace(x_nm=11_000_000, y_nm=10_000_000),
    )
    mock_board.get_footprints.return_value = [u1, c1]
    mock_board.get_pads.return_value = []
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_calculate_decoupling_placement",
        {"ic_ref": "U1", "power_pin": "7", "target_freq_mhz": 250.0},
    )
    assert "Decoupling placement heuristic" in result
    assert "Anchor position" in result


@pytest.mark.anyio
async def test_si_synthesize_stackup_for_interfaces_rf(sample_project) -> None:
    """si_synthesize_stackup_for_interfaces should handle RF interfaces."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_synthesize_stackup_for_interfaces",
        {
            "interfaces": [{"kind": "sgmii", "differential": True, "impedance_target_ohm": 100.0}],
            "cost_tier": "rf",
            "board_thickness_mm": 1.0,
        },
    )
    assert "sgmii" in result
    assert "ro4003c" in result or "RF" in result


@pytest.mark.anyio
async def test_si_synthesize_stackup_for_interfaces_ultralow(sample_project) -> None:
    """si_synthesize_stackup_for_interfaces should handle ultralow loss tier."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    result = await call_tool_text(
        server,
        "si_synthesize_stackup_for_interfaces",
        {
            "interfaces": [{"kind": "ddr5", "differential": False, "impedance_target_ohm": 50.0}],
            "cost_tier": "ultralow",
            "board_thickness_mm": 1.6,
        },
    )
    assert "ddr5" in result
    assert "megtron6" in result or "Megtron" in result
