"""Deterministic reproduction tests for suspected false-PASS paths audited in #1578 (T0).

These unit tests prove that the static-review observations are verified bugs or
integration gaps in the current implementation, rather than unconfirmed hypotheses.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

from kicad_mcp.manufacturing.release_evidence import _evaluate_hv_safety_gate
from kicad_mcp.models.visual_qa import run_cosmetic_qa
from kicad_mcp.project.workflow import build_design_workflow
from kicad_mcp.tools import emc_compliance as emc
from kicad_mcp.tools import signal_integrity_decoupling_placement as sidp
from kicad_mcp.tools import validation


def test_reproduce_hv_safety_keyword_presence_treated_as_insulation_review() -> None:
    """Proves that any .kicad_dru containing 'clearance' passes HV safety review."""
    with tempfile.TemporaryDirectory() as tmpdir:
        project_dir = Path(tmpdir)
        dru_file = project_dir / "unrelated_standard_clearance.kicad_dru"
        dru_file.write_text('(rule "DefaultClearance" (constraint clearance (min 0.2mm)))')

        gate, warnings = _evaluate_hv_safety_gate(
            project_dir,
            is_hv=True,
            voltage_v=230.0,
            effective_domain="hazardous_mains",
        )

        # Gap/Bug: passes 230V hazardous mains safety check based purely on substring match
        assert gate["passed"] is True
        assert "HV design rules found" in gate["detail"]


def test_reproduce_workflow_completed_metadata_treated_as_evidence() -> None:
    """Proves that passing phase names marks them COMPLETE without verifying outputs."""
    unverified_input = ["schematic_capture", "pcb_layout", "manufacturing_prep"]
    wf_state = build_design_workflow(unverified_input)

    phase_map = {p.phase: p.status for p in wf_state.phases}
    # Gap/Bug: arbitrary caller strings become COMPLETE without running ERC, DRC, or gate checks
    assert phase_map["schematic_capture"] == "COMPLETE"


def test_reproduce_empty_schematic_cosmetic_score_passes_without_circuit() -> None:
    """Proves that a schematic with title block but zero components passes cosmetic QA."""
    blank_sch = '(kicad_sch (version 20231120) (generator eeschema) (title_block (title "Empty")))'
    blank_qa = run_cosmetic_qa(blank_sch)

    # Gap/Bug: blank schematic with zero symbols and zero wires passes cosmetic QA with 97/100 score
    assert blank_qa["symbol_count"] == 0
    assert blank_qa["wire_count"] == 0
    assert blank_qa["status"] == "PASS"
    assert blank_qa["cosmetic_score"] >= 95.0


def test_reproduce_missing_power_pin_fallback_to_footprint_centre() -> None:
    """Proves that missing power pin silently falls back to footprint origin."""
    fp_u1 = MagicMock()
    fp_u1.reference_field.text.value = "U1"
    fp_u1.position = MagicMock(x=15_000_000, y=25_000_000)

    # U1 only has pin 1
    pad1 = MagicMock()
    pad1.parent = fp_u1
    pad1.number = "1"
    pad1.position = MagicMock(x=15_000_000, y=26_000_000)

    orig_footprints = sidp.board_footprints
    orig_pads = sidp.board_pads
    orig_get_board = sidp.get_board
    orig_point_xy_mm = sidp.point_xy_mm

    try:
        sidp.board_footprints = MagicMock(return_value=[fp_u1])
        sidp.board_pads = MagicMock(return_value=[pad1])
        sidp.get_board = MagicMock()
        sidp.point_xy_mm = lambda pos: (pos.x / 1_000_000, pos.y / 1_000_000)

        # Query for non-existent power pin "VCC_PIN_99"
        anchor_xy = sidp._find_power_anchor("U1", "VCC_PIN_99")

        # Gap/Bug: returns (15.0, 25.0) which is footprint center, rather than raising/NOT_ASSESSED
        assert anchor_xy == (15.0, 25.0)
    finally:
        sidp.board_footprints = orig_footprints
        sidp.board_pads = orig_pads
        sidp.get_board = orig_get_board
        sidp.point_xy_mm = orig_point_xy_mm


def test_reproduce_near_wrong_net_capacitor_passes_decoupling() -> None:
    """Proves that EMC decoupling check ignores nets and passes wrong-rail capacitors."""
    fp_u1 = MagicMock()
    fp_u1.reference_field.text.value = "U1"
    fp_u1.position = MagicMock(x=10_000_000, y=10_000_000)

    # C1 is 1mm away from U1, but could be on +12V rail or unconnected
    fp_c1 = MagicMock()
    fp_c1.reference_field.text.value = "C1"
    fp_c1.position = MagicMock(x=11_000_000, y=10_000_000)

    orig_footprints = emc.board_footprints
    orig_get_board = emc.get_board
    orig_point_xy_mm = emc.point_xy_mm

    try:
        emc.board_footprints = MagicMock(return_value=[fp_u1, fp_c1])
        emc.get_board = MagicMock()
        emc.point_xy_mm = lambda pos: (pos.x / 1_000_000, pos.y / 1_000_000)

        verdict, detail = emc._emc_check_decoupling_text(max_distance_mm=3.0)

        # Gap/Bug: passes without verifying that C1 is on the same supply net as U1
        assert verdict == "PASS"
        assert "within 3.0 mm" in detail
    finally:
        emc.board_footprints = orig_footprints
        emc.get_board = orig_get_board
        emc.point_xy_mm = orig_point_xy_mm


def test_reproduce_generic_90_degree_style_treated_as_electrical_defect() -> None:
    """Proves that 90-degree track corner fails the gate unconditionally."""
    pcb_text = """
(kicad_pcb
  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net "DC_RAIL"))
  (segment (start 20 10) (end 20 20) (width 0.2) (layer "F.Cu") (net "DC_RAIL"))
)
"""
    segments = validation._pcb_track_segments_from_text(pcb_text)
    corners = validation._route_90_degree_corners(segments)

    # Exactly 1 corner found
    assert len(corners) == 1
    assert "DC_RAIL on F.Cu has a 90° corner" in corners[0]

    # With default max_90_degree_corners=0, release gate fails unconditionally
    assert len(corners) > 0  # causes FAIL in _evaluate_route_corner_style_gate
