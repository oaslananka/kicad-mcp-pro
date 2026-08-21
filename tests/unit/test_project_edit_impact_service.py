from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest


class FakeInferenceError(Exception):
    pass


@dataclass
class FakeOutcome:
    name: str
    status: str


def _service(
    *,
    baseline: dict[str, Any] | None = None,
    current: dict[str, Any] | None = None,
    inference_error: Exception | None = None,
    gate_calls: list[dict[str, object]] | None = None,
):
    from kicad_mcp.project.edit_impact import ProjectEditImpactService

    baseline_value = baseline or {"manufacturer": "ACME", "critical_nets": ["USB_DP"]}
    current_value = current or {"manufacturer": "PCBWay", "critical_nets": ["USB_DP", "USB_DM"]}

    def load_baseline() -> dict[str, Any]:
        return baseline_value

    def infer_current() -> dict[str, Any]:
        if inference_error is not None:
            raise inference_error
        return current_value

    def evaluate_project_gate(**kwargs: object) -> list[FakeOutcome]:
        if gate_calls is not None:
            gate_calls.append(kwargs)
        return [FakeOutcome("PCB", "FAIL")]

    return ProjectEditImpactService(
        load_baseline=load_baseline,
        infer_current=infer_current,
        evaluate_project_gate=evaluate_project_gate,
        combined_status=lambda outcomes: outcomes[0].status if outcomes else "PASS",
        format_gate=lambda outcome: f"{outcome.name}:{outcome.status}",
        project_gate_categories=frozenset(
            {"schematic", "connectivity", "pcb", "manufacturing", "dfm"}
        ),
        inference_error_types=(FakeInferenceError,),
    )


def test_assess_uses_saved_baseline_and_preserves_edit_impact_rendering() -> None:
    text = _service().assess()

    assert text.startswith("Edit-impact analysis:\n-")
    assert "[added] critical_nets: USB_DM" in text
    assert "[modified] manufacturer:" in text
    assert "Gates to re-run: connectivity, signal_integrity, pcb, manufacturing, dfm" in text
    assert "Gates preserved: schematic, power, thermal, emc" in text


def test_assess_explicit_json_bypasses_saved_baseline() -> None:
    text = _service(baseline={"manufacturer": "SAVED"}).assess(
        '{"manufacturer": "PCBWay", "critical_nets": ["USB_DP", "USB_DM"]}'
    )

    assert "Changes:\n  (none)" in text
    assert "Gates to re-run: (none)" in text


def test_invalid_baseline_messages_match_existing_contract() -> None:
    service = _service()

    invalid = service.assess("{")
    non_object = service.assess("[]")

    assert invalid.startswith("Invalid baseline_spec_json:")
    assert non_object == "baseline_spec_json must be a JSON object (a design spec)."


def test_configured_inference_error_is_rendered_but_other_errors_propagate() -> None:
    blocked = _service(inference_error=FakeInferenceError("offline"))
    assert blocked.assess() == "Could not infer the current board intent: offline"

    exploding = _service(inference_error=RuntimeError("unexpected"))
    with pytest.raises(RuntimeError, match="unexpected"):
        exploding.assess()


def test_revalidate_runs_only_impacted_project_gates_and_lists_analysis_tools() -> None:
    calls: list[dict[str, object]] = []
    service = _service(gate_calls=calls)

    text = service.revalidate(manufacturer="JLCPCB", tier="standard")

    assert calls == [
        {
            "manufacturer": "JLCPCB",
            "tier": "standard",
            "only_categories": {"connectivity", "pcb", "manufacturing", "dfm"},
        }
    ]
    assert "Selective re-validation after edit:" in text
    assert "Re-ran impacted project gates (connectivity, dfm, manufacturing, pcb): FAIL" in text
    assert "PCB:FAIL" in text
    assert (
        "- signal_integrity: si_calculate_trace_impedance / si_analyze_high_speed_channel" in text
    )
    assert "Preserved project gates (not re-run): schematic" in text


def test_revalidate_no_changes_skips_gate_execution() -> None:
    calls: list[dict[str, object]] = []
    baseline = {"manufacturer": "ACME", "critical_nets": ["USB_DP"]}
    service = _service(baseline=baseline, current=dict(baseline), gate_calls=calls)

    text = service.revalidate()

    assert calls == []
    assert "No gates were re-run; every previously-passing gate is preserved." in text


def test_legacy_tools_edit_impact_import_remains_compatible() -> None:
    from kicad_mcp.project import edit_impact as project_edit_impact
    from kicad_mcp.tools import edit_impact as tools_edit_impact

    assert tools_edit_impact.semantic_intent_diff is project_edit_impact.semantic_intent_diff
    assert tools_edit_impact.impact_of_changes is project_edit_impact.impact_of_changes
    assert tools_edit_impact.render_impact_report is project_edit_impact.render_impact_report
