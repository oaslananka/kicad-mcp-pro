"""Guard cosmetic fixes, visual policy boundaries, and PCB pin-1 evidence."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from kicad_mcp.models.review import AssessmentStatus, ReviewContext
from kicad_mcp.review import visual_quality as visual

SCHEMATIC = (
    '(kicad_sch (property "Reference" "R1") '
    '(property "Sheetname" "Top") (property "Sheetfile" "top.kicad_sch") '
    '(title "Original"))'
)


def test_rotations_cannot_leak_across_schematic_pcb_and_cpl() -> None:
    before = visual.ComponentRotationState("R1", 0, 90, 90)
    assert before.verify_cpl_calibration()
    assert not replace(before, cpl_rotation_deg=180).verify_cpl_calibration()

    ok, reason = visual.verify_rotation_independence(
        before, replace(before, cpl_rotation_deg=180), mutated_domain="schematic"
    )
    assert not ok
    assert reason is not None
    assert "CPL rotation" in reason

    ok, reason = visual.verify_rotation_independence(
        before, replace(before, symbol_orientation_deg=90), mutated_domain="pcb"
    )
    assert not ok
    assert reason is not None
    assert "schematic orientation" in reason
    assert visual.verify_rotation_independence(
        before, replace(before, pcb_rotation_deg=180), mutated_domain="pcb"
    ) == (True, None)


def test_cosmetic_mutator_exception_and_noop_are_handled_without_mutation() -> None:
    def broken(_: str) -> tuple[str, list[dict[str, Any]]]:
        raise ValueError("render unavailable")

    failed = visual.plan_cosmetic_transaction(SCHEMATIC, "broken", broken)
    assert failed.is_safe_to_apply is False
    assert "render unavailable" in (failed.refusal_reason or "")
    text, ok, reason = visual.apply_cosmetic_transaction(SCHEMATIC, failed)
    assert (text, ok) == (SCHEMATIC, False)
    assert "Refused" in reason

    no_changes = visual.plan_cosmetic_transaction(SCHEMATIC, "noop", lambda text: (text, []))
    unchanged_text = visual.plan_cosmetic_transaction(
        SCHEMATIC, "noop", lambda text: (text, [{"change": "no-op"}])
    )
    for noop in (no_changes, unchanged_text):
        assert noop.is_safe_to_apply
        assert visual.apply_cosmetic_transaction(SCHEMATIC, noop)[1]


def test_cosmetic_hierarchy_changes_are_rejected() -> None:
    plan = visual.plan_cosmetic_transaction(
        SCHEMATIC,
        "invalid_sheet",
        lambda text: (
            text.replace('"top.kicad_sch"', '"hidden.kicad_sch"'),
            [{"change": "sheet_file"}],
        ),
    )
    assert not plan.is_safe_to_apply
    assert plan.hierarchy_preserved is False
    assert "Hierarchical" in (plan.refusal_reason or "")


def test_cosmetic_apply_rechecks_connectivity_and_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = visual.plan_cosmetic_transaction(
        SCHEMATIC,
        "cosmetic_title",
        lambda text: (text.replace("Original", "Revised"), [{"change": "title"}]),
    )
    assert plan.is_safe_to_apply
    # Simulate a changed connectivity reading between planning and commit.
    monkeypatch.setattr(visual, "_connectivity_signature", lambda _: frozenset({"drift"}))
    text, applied, message = visual.apply_cosmetic_transaction(SCHEMATIC, plan)
    assert text == SCHEMATIC
    assert not applied
    assert "Rollback: connectivity signature diverged" in message


def test_pin1_skips_non_targets_and_identifies_occluded_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class OccludingTextBox:
        def contains_point(self, x: float, y: float) -> bool:
            return x == -2.0 and y == -1.5

    monkeypatch.setattr(visual, "_reference_silk_box", lambda *_: OccludingTextBox())
    silk = '(fp_circle (center -2 -2) (end -1 -2) (layer "F.SilkS"))'
    block = '(pad "1" smd roundrect (at -2 -1.5) (size 1 .5)) ' + silk
    footprints: dict[str, dict[str, Any]] = {
        "U1": {"block": block, "x_mm": 0, "y_mm": 0},
        "U2": {"block": ""},
        "U3": {"block": '(pad "3" smd rect (at 0 0))'},
        "R1": {"block": '(pad "1" smd rect (at 0 0))'},
        "U4": {"block": '(pad "1" smd rect (at 0 0))'},
    }
    findings = visual.detect_pin1_marker_visibility(footprints)
    assert {(x.ref, x.code) for x in findings} == {
        ("U1", "pin1_marker_occluded"),
        ("U4", "pin1_marker_missing"),
    }


@pytest.mark.parametrize(
    ("strict", "raw", "expected", "severity", "location"),
    [
        (
            False,
            [{"code": "label_collision", "level": "WARN", "ref": "R1", "position": ("1", "2")}],
            AssessmentStatus.WARN,
            "warning",
            (1.0, 2.0),
        ),
        (
            True,
            [{"code": "label_collision", "level": "WARN", "ref": "R1"}],
            AssessmentStatus.FAIL,
            "error",
            None,
        ),
        (False, [{"code": "grid_alignment", "level": "INFO"}], AssessmentStatus.PASS, None, None),
        (
            True,
            [{"code": "grid_alignment", "level": "WARN", "position": ("1", "invalid")}],
            AssessmentStatus.WARN,
            "warning",
            None,
        ),
        (
            False,
            ["invalid", {"code": "text_overlap", "level": "WARN"}],
            AssessmentStatus.WARN,
            "warning",
            None,
        ),
        (False, "invalid report shape", AssessmentStatus.PASS, None, None),
    ],
)
def test_schematic_cosmetic_policy_honors_strict_mode_and_bad_inputs(
    monkeypatch: pytest.MonkeyPatch,
    strict: bool,
    raw: list[dict[str, object] | str] | str | None,
    expected: AssessmentStatus,
    severity: str | None,
    location: tuple[float, float] | None,
) -> None:
    monkeypatch.setattr(visual, "parse_symbols", lambda _: [object()])
    monkeypatch.setattr(visual, "parse_wires", lambda _: [])
    monkeypatch.setattr(
        visual, "run_cosmetic_qa", lambda _: {"findings": raw, "cosmetic_score": 82}
    )
    context = ReviewContext(explicit_requirements={"strict_schematic_cosmetics": strict})
    result = visual.evaluate_schematic_visual_quality(context, SCHEMATIC)
    assert result.status == expected
    assert result.metadata["electrical_defect"] is False
    assert result.metadata["symbol_count"] == 1
    if severity:
        assert len(result.findings) == 1
        assert result.findings[0].severity == severity
        assert result.findings[0].location_mm == location
    else:
        assert result.findings == []


@pytest.mark.parametrize(
    ("strict", "raw", "expected", "severity"),
    [
        (
            False,
            [{"level": "WARN", "code": "silk_overlap", "position": [5, 6]}],
            AssessmentStatus.WARN,
            "warning",
        ),
        (True, [{"level": "FAIL", "code": "silk_overlap"}], AssessmentStatus.FAIL, "error"),
        (False, [{"level": "INFO", "code": "body_overlap"}], AssessmentStatus.PASS, None),
        (True, [{"level": "INFO", "code": "body_overlap"}], AssessmentStatus.WARN, "warning"),
        (
            False,
            ["invalid report item", {"level": "WARN", "code": "overlap"}],
            AssessmentStatus.WARN,
            "warning",
        ),
        (False, None, AssessmentStatus.PASS, None),
    ],
)
def test_pcb_cosmetic_policy_preserves_electrical_defect_boundary(
    monkeypatch: pytest.MonkeyPatch,
    strict: bool,
    raw: list[dict[str, object] | str] | str | None,
    expected: AssessmentStatus,
    severity: str | None,
) -> None:
    monkeypatch.setattr(visual, "run_pcb_readability", lambda *_: {"findings": raw})
    monkeypatch.setattr(visual, "detect_pin1_marker_visibility", lambda *_: [])
    ctx = ReviewContext(explicit_requirements={"strict_pcb_presentation": strict})
    result = visual.evaluate_pcb_visual_quality(
        ctx, footprints={"R1": {"block": ""}}, bounds=(0, 0, 10, 10)
    )
    assert result.status == expected
    assert result.metadata["electrical_defect"] is False
    if severity:
        assert len(result.findings) == 1
        assert result.findings[0].severity == severity
    else:
        assert result.findings == []


def test_visual_evaluation_is_only_attempted_for_explicit_input() -> None:
    assert visual.evaluate_visual_quality(ReviewContext()) == []
    context = ReviewContext(explicit_requirements={"schematic_symbols": True})
    result = visual.evaluate_visual_quality(context)
    assert len(result) == 1
    assert result[0].status == AssessmentStatus.BLOCKED
    result = visual.evaluate_visual_quality(ReviewContext(), bounds=(0, 0, 20, 20))
    assert len(result) == 1
    assert result[0].status == AssessmentStatus.BLOCKED
    assert (
        visual.evaluate_schematic_visual_quality(ReviewContext(), "   ").status
        == AssessmentStatus.NOT_ASSESSED
    )
