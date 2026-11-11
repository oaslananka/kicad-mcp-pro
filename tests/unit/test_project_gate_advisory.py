"""Advisory outcomes must not become fake product blockers."""

from __future__ import annotations

from kicad_mcp.tools.validation import (
    GateOutcome,
    _gate_findings,
    _gate_report,
    _project_gate_report_payload,
    _project_gate_verdict_report,
)


def _cosmetic_advisory() -> GateOutcome:
    return GateOutcome(
        name="Schematic cosmetics",
        status="WARN",
        summary="Cosmetic score 69/100. Advisory ? does not block release.",
        details=["DividerDemo.kicad_sch: score 69 (worst: typography)"],
    )


def test_untagged_cosmetic_advisory_is_warning_not_error() -> None:
    outcome = _cosmetic_advisory()
    result = _gate_report(outcome)
    assert result.verdict == "WARN"
    assert [f.severity for f in result.findings] == ["warning"]

    project = _project_gate_verdict_report([GateOutcome("PCB", "PASS", "DRC clean"), outcome])
    assert project.verdict == "WARN"
    assert project.metadata["status"] == "WARN"
    assert project.findings[0].severity == "warning"
    assert "Advisory findings remain" in project.summary
    assert "Blocking issues remain" not in project.text
    assert "first blocking gate" not in project.next_action
    assert "advisory" in project.next_action.lower()

    payload = _project_gate_report_payload([outcome])
    assert payload.status == "WARN"
    assert "Advisory findings remain" in payload.summary


def test_explicit_fail_remains_error_even_inside_warn_gate() -> None:
    inconsistent = GateOutcome(
        "Schematic cosmetics", "WARN", "Review notes", ["FAIL: physical obstruction"]
    )
    assert [f.severity for f in _gate_findings(inconsistent)] == ["error"]
    assert _gate_report(inconsistent).verdict == "FAIL"


def test_advisory_before_true_failure_prioritizes_actual_blocker() -> None:
    report = _project_gate_verdict_report(
        [
            _cosmetic_advisory(),
            GateOutcome("PCB", "FAIL", "Physical DRC failure", ["FAIL: trace clearance"]),
        ]
    )
    assert report.verdict == "FAIL"
    assert report.metadata["status"] == "FAIL"
    assert "Blocking issues remain" in report.summary
    assert "pcb_refill_zones" in report.next_action
    assert "sch_cosmetic_score" not in report.next_action
