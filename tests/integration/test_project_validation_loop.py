from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from kicad_mcp.tools.fixers import FixerAction
from kicad_mcp.tools.validation import GateOutcome
from tests.conftest import call_tool_payload, call_tool_text


def _gate_sequence(*runs: list[GateOutcome]) -> Iterator[list[GateOutcome]]:
    yield from runs
    while True:
        yield runs[-1]


@pytest.mark.anyio
async def test_project_full_validation_loop_applies_auto_fixer(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    calls: list[str] = []

    def fake_fix() -> str:
        calls.append("fixed")
        return "junctions repaired"

    monkeypatch.setattr("kicad_mcp.tools.schematic.run_auto_add_missing_junctions", fake_fix)
    outcomes = _gate_sequence(
        [GateOutcome(name="Pre-sync", status="FAIL", summary="missing junctions")],
        [GateOutcome(name="Pre-sync", status="PASS", summary="safe")],
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda: next(outcomes),
    )

    result = await call_tool_payload(
        server,
        "project_full_validation_loop",
        {"max_iterations": 3, "fix_tier": "auto_only"},
    )

    assert isinstance(result, dict)
    assert result["gate_status"] == "PASS"
    assert result["ready_for_release"] is True
    assert result["remaining_issues"] == 0
    assert calls == ["fixed"]
    assert "sch_add_missing_junctions" in result["text"]


@pytest.mark.anyio
async def test_project_full_validation_loop_suggests_without_mutating(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda: [GateOutcome(name="Placement", status="FAIL", summary="caps too far")],
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.project.fixers_for_gate",
        lambda _name: [
            FixerAction(
                tool="pcb_place_decoupling_caps",
                description="move bypass capacitors near ICs",
                auto_applicable=False,
            )
        ],
    )

    result = await call_tool_payload(
        server,
        "project_full_validation_loop",
        {"max_iterations": 2, "fix_tier": "suggest"},
    )

    assert isinstance(result, dict)
    assert result["gate_status"] == "FAIL"
    assert result["remaining_issues"] == 1
    assert result["actions"][0]["agent_tool"] == "pcb_place_decoupling_caps"
    assert "Suggested fixes" in result["text"]


@pytest.mark.anyio
async def test_project_auto_fix_loop_applies_server_fix_and_reports_remaining_action(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    calls: list[str] = []

    def fake_fix() -> str:
        calls.append("auto")
        return "annotated"

    monkeypatch.setattr("kicad_mcp.tools.schematic.run_auto_annotate", fake_fix)
    outcomes = _gate_sequence(
        [GateOutcome(name="Schematic", status="FAIL", summary="unannotated symbols")],
        [GateOutcome(name="Placement", status="WARN", summary="review placement")],
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda: next(outcomes),
    )

    result = await call_tool_payload(
        server,
        "project_auto_fix_loop",
        {"max_iterations": 3},
    )

    assert isinstance(result, dict)
    assert calls == ["auto"]
    # After the auto-fix clears the Schematic FAIL, a Placement WARN remains; the
    # combined gate status now surfaces that WARN instead of swallowing it as PASS.
    assert result["gate_status"] == "WARN"
    assert result["ready_for_release"] is False
    assert result["remaining_issues"] == 1
    assert result["actions"][0]["gate"] == "Placement"
    assert "Server-side auto-fixes applied" in result["text"]
    assert "call pcb_place_decoupling_caps()" in result["text"]


@pytest.mark.anyio
async def test_project_gate_trend_and_design_report(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    def fake_project_gate(**_kwargs: object) -> list[GateOutcome]:
        return [
            GateOutcome(name="Placement", status="PASS", summary="ok"),
            GateOutcome(name="Manufacturing", status="WARN", summary="review DFM"),
        ]

    monkeypatch.setattr("kicad_mcp.tools.validation._evaluate_project_gate", fake_project_gate)
    await call_tool_text(server, "project_quality_gate", {})

    trend = await call_tool_text(server, "project_gate_trend", {"gate_name": "Placement"})
    report = await call_tool_payload(server, "project_design_report", {})

    assert '"gate_name": "Placement"' in trend
    assert '"history"' in trend
    assert isinstance(report, dict)
    # A Manufacturing WARN in the gate set now yields a WARN combined status.
    assert report["gate_status"] == "WARN"
    assert "Project Design Report" in report["text"]
    assert "Manufacturing" in report["text"]


@pytest.mark.anyio
async def test_project_full_validation_loop_does_not_run_fixers_outside_profile(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pcb_only server hides schematic tools, so the loop must not call their fixers."""
    server = build_server("pcb_only")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    calls: list[str] = []
    monkeypatch.setattr(
        "kicad_mcp.tools.schematic.run_auto_add_missing_junctions",
        lambda: calls.append("junctions") or "junctions repaired",
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.schematic.run_auto_annotate",
        lambda: calls.append("annotate") or "annotated",
    )
    outcomes = _gate_sequence(
        [GateOutcome(name="Pre-sync", status="FAIL", summary="missing junctions")],
        [GateOutcome(name="Pre-sync", status="PASS", summary="safe")],
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda: next(outcomes),
    )

    result = await call_tool_payload(
        server,
        "project_full_validation_loop",
        {"max_iterations": 3, "fix_tier": "auto_only"},
    )

    assert isinstance(result, dict)
    assert calls == []
    assert result["gate_status"] != "PASS"
    assert "not enabled" in result["text"]


@pytest.mark.anyio
async def test_project_auto_fix_loop_does_not_run_fixers_outside_profile(
    sample_project: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = build_server("pcb_only")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    calls: list[str] = []
    monkeypatch.setattr(
        "kicad_mcp.tools.schematic.run_auto_annotate",
        lambda: calls.append("annotate") or "annotated",
    )
    outcomes = _gate_sequence(
        [GateOutcome(name="Schematic", status="FAIL", summary="unannotated symbols")],
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.validation._evaluate_project_gate",
        lambda: next(outcomes),
    )

    result = await call_tool_payload(server, "project_auto_fix_loop", {"max_iterations": 3})

    assert isinstance(result, dict)
    assert calls == []
    assert "not enabled" in result["text"]
