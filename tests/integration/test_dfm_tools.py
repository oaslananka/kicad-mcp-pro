from __future__ import annotations

from types import SimpleNamespace

import pytest
from kipy.proto.board.board_types_pb2 import BoardLayer

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text


@pytest.mark.anyio
async def test_dfm_profile_load_run_and_cost(
    sample_project,
    mock_board,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_board.get_enabled_layers.return_value = [BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu]
    mock_board.get_tracks.return_value = [SimpleNamespace(width=200_000)]
    mock_board.get_vias.return_value = [SimpleNamespace(drill_diameter=300_000, diameter=600_000)]
    (sample_project / "demo.kicad_pcb").write_text(
        "\n".join(
            [
                "(kicad_pcb",
                "\t(version 20250216)",
                '\t(generator "pytest")',
                (
                    "\t(gr_rect (start 0 0) (end 50 40) "
                    "(stroke (width 0.05) (type solid)) "
                    '(fill no) (layer "Edge.Cuts"))'
                ),
                ")",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.dfm._run_drc_report",
        lambda _report_name: (
            sample_project / "output" / "dfm_profile_check.json",
            {
                "violations": [],
                "unconnected_items": [],
                "items_not_passing_courtyard": [],
            },
            None,
        ),
    )
    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    loaded = await call_tool_text(
        server,
        "dfm_load_manufacturer_profile",
        {"manufacturer": "JLCPCB", "tier": "standard"},
    )
    report = await call_tool_text(server, "dfm_run_manufacturer_check", {})
    cost = await call_tool_text(
        server,
        "dfm_calculate_manufacturing_cost",
        {"quantity": 10, "manufacturer": "JLCPCB", "tier": "standard"},
    )

    assert "Active profile: JLCPCB / standard" in loaded
    assert "Profile: JLCPCB / standard" in report
    assert "PASS: Minimum track width 0.200 mm >= 0.127 mm" in report
    assert "PASS: Minimum via drill 0.300 mm >= 0.300 mm" in report
    assert "WARN: JLCPCB 2-layer/1-oz PTH annular ring absolute minimum 0.180 mm" in report
    assert "noncircular PTH, plated slots and finished hole tolerances are not measured" in report
    assert "actual copper weight is not checked" in report
    assert "Partial source-board PTH preflight: 0 circular pads measured" in report
    assert "Manufacturing cost estimate:" in cost
    assert "Board size: 50.00 x 40.00 mm" in cost
    assert "Quantity: 10" in cost


@pytest.mark.anyio
async def test_legacy_dfm_validation_uses_profile_backend(
    sample_project,
    mock_board,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock_board.get_enabled_layers.return_value = [BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu]
    mock_board.get_tracks.return_value = [SimpleNamespace(width=150_000)]
    mock_board.get_vias.return_value = [SimpleNamespace(drill_diameter=350_000, diameter=700_000)]
    monkeypatch.setattr(
        "kicad_mcp.tools.dfm._run_drc_report",
        lambda _report_name: (
            sample_project / "output" / "dfm_profile_check.json",
            {
                "violations": [{"severity": "warning", "description": "Silk overlap"}],
                "unconnected_items": [],
                "items_not_passing_courtyard": [],
            },
            None,
        ),
    )
    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    jlcpcb = await call_tool_text(server, "check_design_for_manufacture", {"jlcpcb": True})
    generic = await call_tool_text(server, "check_design_for_manufacture", {"jlcpcb": False})

    assert "DFM check (JLCPCB profile):" in jlcpcb
    assert "Profile: JLCPCB / standard" in jlcpcb
    assert "DFM check (generic profile):" in generic
    assert "Profile: PCBWay / standard" in generic


@pytest.mark.anyio
async def test_manufacturer_dfm_flags_saved_board_nominal_underwidth_pth(
    sample_project, mock_board, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_board.get_enabled_layers.return_value = [BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu]
    mock_board.get_tracks.return_value = []
    mock_board.get_vias.return_value = []
    board_text = (
        "(kicad_pcb (version 20250216) "
        '(footprint "Connector_USB:Test" (layer "F.Cu") '
        '(property "Reference" "J1") '
        '(pad "1" thru_hole circle (at 0 0) (size 0.65 0.65) (drill 0.4) '
        '(layers "*.Cu" "*.Mask"))'
        '(pad "2" thru_hole oval (size 1.2 2) (drill oval 0.6 1.4))'
        "))"
    )
    (sample_project / "demo.kicad_pcb").write_text(board_text, encoding="utf-8")
    monkeypatch.setattr(
        "kicad_mcp.tools.dfm._run_drc_report",
        lambda _name: (
            sample_project / "report.json",
            {"violations": [], "unconnected_items": [], "items_not_passing_courtyard": []},
            None,
        ),
    )
    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    report = await call_tool_text(server, "dfm_run_manufacturer_check", {})
    assert "FAIL: JLCPCB nominal circular PTH J1 pad 1: nominal ring 0.125 mm" in report
    assert "1 circular pads measured, 1 unmeasured PTH shapes/plated slots" in report
    assert "written CAM signoff" in report


@pytest.mark.anyio
async def test_manufacturer_dfm_missing_saved_pcb_reports_unverified_geometry(
    sample_project, mock_board, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_board.get_enabled_layers.return_value = [BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu]
    monkeypatch.setattr(
        "kicad_mcp.tools.dfm._run_drc_report",
        lambda _name: (
            sample_project / "report.json",
            {"violations": [], "unconnected_items": [], "items_not_passing_courtyard": []},
            None,
        ),
    )
    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    monkeypatch.setattr(
        "kicad_mcp.tools.dfm._get_pcb_file", lambda: sample_project / "absent.kicad_pcb"
    )
    report = await call_tool_text(server, "dfm_run_manufacturer_check", {})
    assert "Saved PCB PTH geometry unavailable" in report
    assert "individual pads/slots remain unverified" in report
    assert "written CAM" in report


@pytest.mark.anyio
async def test_dfm_missing_pcb_source_cannot_bypass_drc_or_saved_pad_warnings(
    sample_project, mock_board, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_board.get_enabled_layers.return_value = [BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu]
    server = build_server("manufacturing")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    # Unlike the previous stubbed integration case, DRC itself must fail
    # because the saved PCB is missing; this used to escape as ValueError.
    def missing_pcb() -> None:
        raise ValueError("saved project PCB is absent")

    monkeypatch.setattr("kicad_mcp.tools.dfm._get_pcb_file", missing_pcb)
    report = await call_tool_text(server, "dfm_run_manufacturer_check", {})
    assert "DRC report unavailable" in report
    assert "Saved PCB PTH geometry unavailable" in report
    assert "written CAM" in report
    assert "DFM profile check" in report
