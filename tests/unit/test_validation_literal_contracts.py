"""Regression coverage for shared validation labels and missing-analysis errors."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from kicad_mcp.tools import validation


def test_cosmetics_empty_sheet_keeps_public_gate_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp.tools import schematic

    monkeypatch.setattr(schematic, "project_schematic_files", lambda: [])
    outcome = validation._evaluate_schematic_cosmetics_gate()
    assert (outcome.name, outcome.status, outcome.summary) == (
        "Schematic cosmetics",
        "PASS",
        "No schematic sheets to score.",
    )


def test_design_rule_gate_preserves_blocked_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def no_sheet() -> Path:
        raise ValueError("No active schematic.")

    monkeypatch.setattr(validation, "_get_sch_file", no_sheet)
    outcome = validation._evaluate_schematic_design_rule_gate()
    assert (outcome.name, outcome.status, outcome.summary) == (
        "Schematic design rules",
        "BLOCKED",
        "No active schematic.",
    )


def test_design_rule_gate_preserves_top_level_and_success_label(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from kicad_mcp.tools import schematic
    from kicad_mcp.utils import schematic_rules

    main_schematic = tmp_path / "project.kicad_sch"
    main_schematic.touch()
    paths: list[Path] = []
    monkeypatch.setattr(validation, "_get_sch_file", lambda: main_schematic)
    monkeypatch.setattr(schematic, "_iter_child_sheet_paths", lambda _top: [])
    monkeypatch.setattr(
        schematic, "_build_connectivity_groups", lambda path: paths.append(path) or []
    )
    monkeypatch.setattr(schematic_rules, "run_schematic_design_rules", lambda nets: [])

    outcome = validation._evaluate_schematic_design_rule_gate()
    assert paths == [main_schematic]
    assert (outcome.name, outcome.status, outcome.summary) == (
        "Schematic design rules",
        "PASS",
        "No electrical-design-rule issues detected.",
    )


@pytest.mark.parametrize(
    ("hard_failures", "warnings", "expected_status", "expected_summary"),
    [
        (
            ["footprint outside board"],
            ["thermal proximity"],
            "FAIL",
            "Footprint placement still violates hard physical or intent-aware checks.",
        ),
        (
            [],
            ["thermal proximity"],
            "WARN",
            "Placement measurements require manual review; no hard failure was proven.",
        ),
        (
            [],
            [],
            "PASS",
            "Footprint placement is geometrically and contextually sane.",
        ),
    ],
)
def test_placement_gate_preserves_verdict_priority_and_detail_contract(
    monkeypatch: pytest.MonkeyPatch,
    hard_failures: list[str],
    warnings: list[str],
    expected_status: str,
    expected_summary: str,
) -> None:
    analysis = validation.PlacementAnalysis(
        footprint_count=4,
        board_width_mm=40.0,
        board_height_mm=30.0,
        board_area_mm2=1200.0,
        footprint_area_mm2=40.0,
        density_pct=3.3,
        score=90,
        hard_failures=hard_failures,
        warnings=warnings,
    )
    monkeypatch.setattr(validation, "_placement_analysis", lambda: (analysis, None))
    outcome = validation._evaluate_pcb_placement_gate()
    assert (outcome.name, outcome.status, outcome.summary) == (
        "Placement",
        expected_status,
        expected_summary,
    )
    assert f"Placement score: {analysis.score}/100" in outcome.details
    expected_findings = [
        *(f"FAIL: {item}" for item in hard_failures),
        *(f"WARN: {item}" for item in warnings),
    ]
    if expected_findings:
        assert outcome.details[-len(expected_findings) :] == expected_findings


class _ToolRecorder:
    def __init__(self) -> None:
        self.tools: dict[str, Callable[..., object]] = {}

    def tool(self) -> Callable[[Callable[..., object]], Callable[..., object]]:
        def capture(fn: Callable[..., object]) -> Callable[..., object]:
            self.tools[fn.__name__] = fn
            return fn

        return capture


def test_placement_missing_analysis_keeps_all_three_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(validation, "_placement_analysis", lambda: (None, None))
    message = "Placement analysis unexpectedly returned no result."

    with pytest.raises(RuntimeError, match="^" + message.replace(".", r"\.") + "$"):
        validation._evaluate_pcb_placement_gate()

    with pytest.raises(RuntimeError, match="^" + message.replace(".", r"\.") + "$"):
        validation._placement_gate_report_payload()

    recorder = _ToolRecorder()
    validation._register_validation_gate_tools(recorder)  # type: ignore[arg-type]
    with pytest.raises(RuntimeError, match="^" + message.replace(".", r"\.") + "$"):
        recorder.tools["pcb_score_placement"]()
