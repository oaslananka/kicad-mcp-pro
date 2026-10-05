from __future__ import annotations

from types import SimpleNamespace

import pytest
from kipy.proto.board.board_types_pb2 import BoardLayer, ViaType

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


def _field(value: str) -> SimpleNamespace:
    return SimpleNamespace(text=SimpleNamespace(value=value))


def _configure_signal_integrity_board(mock_board) -> None:
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
    clk1 = SimpleNamespace(
        start=SimpleNamespace(x_nm=0, y_nm=2_000_000),
        end=SimpleNamespace(x_nm=21_000_000, y_nm=2_000_000),
        layer=BoardLayer.BL_F_Cu,
        width=150_000,
        net=SimpleNamespace(name="CLK1"),
    )
    clk2 = SimpleNamespace(
        start=SimpleNamespace(x_nm=0, y_nm=3_000_000),
        end=SimpleNamespace(x_nm=21_500_000, y_nm=3_000_000),
        layer=BoardLayer.BL_F_Cu,
        width=150_000,
        net=SimpleNamespace(name="CLK2"),
    )
    via = SimpleNamespace(
        position=SimpleNamespace(x_nm=5_000_000, y_nm=5_000_000),
        drill_diameter=300_000,
        net=SimpleNamespace(name="USB_DP"),
        type=ViaType.VT_THROUGH,
    )
    u1 = SimpleNamespace(
        reference_field=_field("U1"),
        value_field=_field("MCU"),
        position=SimpleNamespace(x_nm=10_000_000, y_nm=10_000_000),
    )
    c1 = SimpleNamespace(
        reference_field=_field("C1"),
        value_field=_field("100n"),
        position=SimpleNamespace(x_nm=11_200_000, y_nm=10_000_000),
    )
    c2 = SimpleNamespace(
        reference_field=_field("C2"),
        value_field=_field("1u"),
        position=SimpleNamespace(x_nm=17_500_000, y_nm=10_000_000),
    )
    pad_vdd = SimpleNamespace(
        parent=u1,
        number="7",
        net=SimpleNamespace(name="3V3"),
        position=SimpleNamespace(x_nm=10_100_000, y_nm=10_000_000),
    )
    stackup = SimpleNamespace(
        layers=[
            SimpleNamespace(layer=BoardLayer.BL_F_Cu, thickness=35_000, material_name="Copper"),
            SimpleNamespace(layer="Prepreg", thickness=180_000, material_name="FR4"),
            SimpleNamespace(layer=BoardLayer.BL_In1_Cu, thickness=18_000, material_name="Copper"),
            SimpleNamespace(layer="Core", thickness=1_124_000, material_name="FR4"),
            SimpleNamespace(layer=BoardLayer.BL_In2_Cu, thickness=18_000, material_name="Copper"),
            SimpleNamespace(layer="Prepreg", thickness=180_000, material_name="FR4"),
            SimpleNamespace(layer=BoardLayer.BL_B_Cu, thickness=35_000, material_name="Copper"),
        ]
    )

    mock_board.get_tracks.return_value = [usb_dp, usb_dn, clk1, clk2]
    mock_board.get_vias.return_value = [via]
    mock_board.get_footprints.return_value = [u1, c1, c2]
    mock_board.get_pads.return_value = [pad_vdd]
    mock_board.get_stackup.return_value = stackup


@pytest.mark.anyio
async def test_signal_integrity_surface(sample_project, mock_board) -> None:
    _configure_signal_integrity_board(mock_board)
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    impedance = await call_tool_text(
        server,
        "si_calculate_trace_impedance",
        {
            "width_mm": 0.34,
            "height_mm": 0.18,
            "er": 4.2,
            "trace_type": "microstrip",
            "copper_oz": 1.0,
            "spacing_mm": 0.2,
        },
    )
    width = await call_tool_text(
        server,
        "si_calculate_trace_width_for_impedance",
        {
            "target_ohm": 50.0,
            "height_mm": 0.18,
            "er": 4.2,
            "trace_type": "microstrip",
            "copper_oz": 1.0,
            "spacing_mm": 0.2,
        },
    )
    skew = await call_tool_text(
        server,
        "si_check_differential_pair_skew",
        {"net_p": "USB_DP", "net_n": "USB_DN", "er": 4.2, "trace_type": "microstrip"},
    )
    matching = await call_tool_text(
        server,
        "si_validate_length_matching",
        {"net_groups": [["USB_DP", "USB_DN"], ["CLK1", "CLK2"]], "tolerance_mm": 1.0},
    )
    stackup = await call_tool_text(
        server,
        "si_generate_stackup",
        {
            "layer_count": 4,
            "target_impedance_ohm": 50.0,
            "manufacturer": "JLCPCB",
            "er": 4.2,
            "copper_oz": 1.0,
        },
    )
    await call_tool_text(
        server,
        "project_set_design_intent",
        {"critical_frequencies_mhz": [23_420.0]},
    )
    via_stub = await call_tool_text(
        server,
        "si_check_via_stub",
        {"frequency_ghz": 5.0, "via_positions": [[5.0, 5.0]], "er": 4.0},
    )
    decoupling = await call_tool_text(
        server,
        "si_calculate_decoupling_placement",
        {"ic_ref": "U1", "power_pin": "7", "target_freq_mhz": 250.0},
    )

    assert "Trace impedance estimate" in impedance
    assert "Estimated single-ended impedance" in impedance
    assert "Width synthesis for 50.00 ohm" in width
    assert "Differential-pair skew analysis" in skew
    assert "Skew: 0.300 mm" in skew
    assert "Length-matching validation" in matching
    assert "Group 1 (PASS)" in matching
    assert "Recommended 4-layer JLCPCB stackup" in stackup
    assert "100 ohm differential pair starting point" in stackup
    assert "Via stub analysis at 5.000 GHz" in via_stub
    assert "quarter-wave resonance" in via_stub
    assert "CRITICAL resonance near 23420.0 MHz" in via_stub
    assert "Decoupling placement heuristic" in decoupling
    assert "Nearest decoupler: C1" in decoupling


@pytest.mark.anyio
async def test_signal_integrity_stackup_synthesis_and_net_class_binding(
    sample_project,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
    interfaces = [
        {
            "kind": "usb3",
            "differential": True,
            "impedance_target_ohm": 90.0,
            "net_prefix": "USB",
        },
        {
            "kind": "ddr4",
            "differential": False,
            "impedance_target_ohm": 50.0,
            "net_prefix": "DDR",
        },
        {"kind": "uart"},
    ]

    materials = await call_tool_text(server, "si_list_dielectric_materials", {})
    synthesis = await call_tool_text(
        server,
        "si_synthesize_stackup_for_interfaces",
        {"interfaces": interfaces, "cost_tier": "midloss", "board_thickness_mm": 1.6},
    )
    dry_run = await call_tool_text(
        server,
        "si_bind_interfaces_to_net_classes",
        {"interfaces": interfaces, "dry_run": True},
    )

    applied = await call_tool_text(
        server,
        "si_bind_interfaces_to_net_classes",
        {"interfaces": interfaces, "dry_run": False},
    )
    no_plan = await call_tool_text(
        server,
        "si_bind_interfaces_to_net_classes",
        {"interfaces": [{"kind": "uart"}], "dry_run": True},
    )

    assert "Available dielectric materials" in materials
    assert "Stackup Synthesis Report" in synthesis
    assert "Has differential pairs: True" in synthesis
    assert "Net Class Configuration" in synthesis
    assert "Net Class Binding Plan" in dry_run
    assert "USB3" in dry_run
    assert "DDR4" in dry_run
    assert "Dry-run mode" in dry_run
    assert "Applied" in applied
    assert written
    assert written[0][0] == "USB3"
    assert "No high-speed interfaces" in no_plan


@pytest.mark.anyio
async def test_si_high_speed_channel_reports_il_eye_and_verdict(sample_project) -> None:
    """si_analyze_high_speed_channel returns insertion loss, eye, and a PASS/FAIL verdict
    with an honest method label (work order P3-T3)."""
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    short = await call_tool_text(
        server,
        "si_analyze_high_speed_channel",
        {"length_mm": 40.0, "data_rate_gbps": 5.0, "max_insertion_loss_db": 10.0},
    )
    assert "High-speed channel analysis" in short
    assert "Insertion loss at Nyquist" in short
    assert "Eye height" in short
    assert "-3 dB bandwidth" in short
    assert "(PASS;" in short
    # ngspice is not present in CI, so the honest closed-form label and note must appear.
    assert "- Method: closed-form lossy-line" in short
    assert "not a measured" in short.lower()

    lossy = await call_tool_text(
        server,
        "si_analyze_high_speed_channel",
        {
            "length_mm": 600.0,
            "data_rate_gbps": 25.0,
            "loss_tangent": 0.025,
            "max_insertion_loss_db": 10.0,
        },
    )
    assert "(FAIL;" in lossy
