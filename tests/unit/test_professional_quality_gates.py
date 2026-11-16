import pytest

from kicad_mcp.tools import validation
from kicad_mcp.tools.router import TOOL_CATEGORIES
from kicad_mcp.tools.validation import (
    _pcb_layer_table_copper_layers,
    _pcb_stackup_copper_layers,
    _pcb_track_segments_from_text,
    _route_90_degree_corners,
)
from kicad_mcp.validation.gates import GateOutcome

# Gate tools that must stay declared in a category, otherwise they are registered
# but hidden from discovery in every profile (regression guard for the orphaned-tool
# fix that paired with these gates).
PROFESSIONAL_GATE_TOOLS = {
    "pcb_stackup_consistency_gate",
    "pcb_route_corner_style_gate",
    "project_professional_release_gate",
}


def test_professional_gates_declared_in_validation_category() -> None:
    declared = set(TOOL_CATEGORIES["validation"]["tools"])
    assert PROFESSIONAL_GATE_TOOLS <= declared


def test_stackup_consistency_parser_detects_missing_inner_layers() -> None:
    pcb_text = """
(kicad_pcb
  (layers
    (0 "F.Cu" signal)
    (2 "B.Cu" signal)
  )
  (setup
    (stackup
      (layer "F.Cu" (type "signal"))
      (layer "In1.Cu" (type "ground"))
      (layer "In2.Cu" (type "power"))
      (layer "B.Cu" (type "signal"))
    )
  )
)
"""
    assert _pcb_layer_table_copper_layers(pcb_text) == ["F.Cu", "B.Cu"]
    assert _pcb_stackup_copper_layers(pcb_text) == ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]


def test_route_corner_style_flags_orthogonal_corner() -> None:
    pcb_text = """
(kicad_pcb
  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net "USB_D_P"))
  (segment (start 20 10) (end 20 20) (width 0.2) (layer "F.Cu") (net "USB_D_P"))
)
"""
    segments = _pcb_track_segments_from_text(pcb_text)
    corners = _route_90_degree_corners(segments)
    assert corners == ["USB_D_P on F.Cu has a 90° corner at (20.000, 10.000)"]


def test_route_corner_style_ignores_45_degree_chamfer() -> None:
    pcb_text = """
(kicad_pcb
  (segment (start 10 10) (end 18 10) (width 0.2) (layer "F.Cu") (net "USB_D_P"))
  (segment (start 18 10) (end 20 12) (width 0.2) (layer "F.Cu") (net "USB_D_P"))
  (segment (start 20 12) (end 20 20) (width 0.2) (layer "F.Cu") (net "USB_D_P"))
)
"""
    segments = _pcb_track_segments_from_text(pcb_text)
    assert _route_90_degree_corners(segments) == []


@pytest.mark.parametrize(
    ("corner_status", "expected_status"),
    [("FAIL", "WARN"), ("PASS", "PASS"), ("BLOCKED", "BLOCKED")],
)
def test_release_bundle_corner_style_is_advisory_only(
    monkeypatch: pytest.MonkeyPatch, corner_status: str, expected_status: str
) -> None:
    """A cosmetic bend must not independently block the full release gate."""
    gate_names = (
        "_evaluate_schematic_gate",
        "_evaluate_pcb_gate",
        "_evaluate_pcb_transfer_gate",
        "_evaluate_pcb_placement_gate",
        "_evaluate_stackup_consistency_gate",
        "_evaluate_manufacturing_gate",
    )
    for name in gate_names:
        monkeypatch.setattr(
            validation,
            name,
            lambda **_kwargs: GateOutcome(
                name="Other required gate", status="PASS", summary="Verified"
            ),
        )
    monkeypatch.setattr(
        validation,
        "_evaluate_route_corner_style_gate",
        lambda **_kwargs: GateOutcome(
            name="Route corner style",
            status=corner_status,
            summary="One cosmetic right-angle bend",
            details=["90-degree corner on SIGNAL_A"],
        ),
    )

    result = validation._evaluate_professional_release_gate()

    assert result.status == expected_status
    assert any("Route corner style" in line for line in result.details)
    if corner_status == "FAIL":
        assert any("advisory" in line.lower() for line in result.details)
        assert any("90-degree corner on SIGNAL_A" in line for line in result.details)


def test_release_bundle_still_blocks_real_pcb_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """DRC/electrical FAIL must outrank an independently cosmetic WARN."""

    def make_gate(name: str, status: str = "PASS"):
        return lambda **_kwargs: GateOutcome(name=name, status=status, summary=name)

    monkeypatch.setattr(validation, "_evaluate_schematic_gate", make_gate("Schematic"))
    monkeypatch.setattr(validation, "_evaluate_pcb_gate", make_gate("Native DRC", "FAIL"))
    monkeypatch.setattr(validation, "_evaluate_pcb_transfer_gate", make_gate("Transfer"))
    monkeypatch.setattr(validation, "_evaluate_pcb_placement_gate", make_gate("Placement"))
    monkeypatch.setattr(validation, "_evaluate_stackup_consistency_gate", make_gate("Stackup"))
    monkeypatch.setattr(validation, "_evaluate_manufacturing_gate", make_gate("DFM"))
    monkeypatch.setattr(
        validation,
        "_evaluate_route_corner_style_gate",
        make_gate("Cosmetic right angle", "FAIL"),
    )

    outcome = validation._evaluate_professional_release_gate()

    assert outcome.status == "FAIL"
    assert any("Native DRC: FAIL" in detail for detail in outcome.details)
