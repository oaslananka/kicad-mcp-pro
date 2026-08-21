from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import SimpleNamespace

from kicad_mcp.project.reporting import ProjectReportingService


@dataclass
class Outcome:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


@dataclass
class Fixer:
    tool: str


class History:
    def __init__(self) -> None:
        self.trend_calls: list[tuple[str, int]] = []

    def trend(self, gate_name: str, last_n: int) -> list[dict[str, object]]:
        self.trend_calls.append((gate_name, last_n))
        return [{"gate_name": gate_name, "issue_count": 1}]

    def regression_check(self) -> list[str]:
        return ["regression"]


def _intent(
    *,
    power_rails: int = 0,
    interfaces: int = 0,
    compliance: int = 0,
    mount_holes: int = 0,
    connector_placement: int = 0,
    max_height_mm: float | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        power_rails=[object()] * power_rails,
        interfaces=[object()] * interfaces,
        compliance=[object()] * compliance,
        mechanical=SimpleNamespace(
            mount_holes=[object()] * mount_holes,
            connector_placement=[object()] * connector_placement,
            max_height_mm=max_height_mm,
        ),
    )


def _resolution(
    *,
    intent: SimpleNamespace | None = None,
    source: str = "project_spec",
    notes: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        resolved=_intent() if intent is None else intent,
        source=source,
        notes=[] if notes is None else notes,
    )


def _service(
    *,
    history: History | None = None,
    resolution: SimpleNamespace | None = None,
    outcomes: list[Outcome] | None = None,
    fixers: dict[str, list[Fixer]] | None = None,
    rendered_intent: str = "intent-summary",
) -> ProjectReportingService:
    active_history = History() if history is None else history
    active_resolution = _resolution() if resolution is None else resolution
    active_outcomes = [Outcome("PCB", "PASS", "ok")] if outcomes is None else outcomes
    active_fixers = {} if fixers is None else fixers
    return ProjectReportingService(
        history_for_active_project=lambda: active_history,
        resolve_design_intent=lambda: active_resolution,
        render_design_intent=lambda _intent: rendered_intent,
        evaluate_project_gate=lambda: active_outcomes,
        fixers_for_gate=lambda gate_name: active_fixers.get(gate_name, []),
    )


def test_gate_trend_clamps_lower_bound_and_renders_exact_json() -> None:
    history = History()
    result = _service(history=history).gate_trend("Placement", 0)

    assert history.trend_calls == [("Placement", 1)]
    assert result == json.dumps(
        {
            "gate_name": "Placement",
            "history": [{"gate_name": "Placement", "issue_count": 1}],
            "regressions": ["regression"],
        },
        indent=2,
        sort_keys=True,
    )


def test_gate_trend_clamps_upper_bound() -> None:
    history = History()
    _service(history=history).gate_trend("Manufacturing", 101)
    assert history.trend_calls == [("Manufacturing", 100)]


def test_design_report_all_pass_preserves_release_path_and_text() -> None:
    payload = _service(
        outcomes=[Outcome("PCB", "PASS", "ok")],
        rendered_intent="rendered-intent",
    ).design_report()

    assert payload.gate_status == "PASS"
    assert payload.next_tool == "export_manufacturing_package"
    assert payload.text == "\n".join(
        [
            "# Project Design Report",
            "",
            "## Design Intent",
            "rendered-intent",
            "",
            "## Gate Status: PASS",
            "All gates PASS — ready for export_manufacturing_package().",
            "",
            "## Resolution Notes",
        ]
    )


def test_design_report_combined_status_precedence() -> None:
    cases = [
        (["PASS", "WARN"], "WARN"),
        (["PASS", "FAIL", "WARN"], "FAIL"),
        (["PASS", "BLOCKED", "FAIL"], "BLOCKED"),
        (["PASS", "EMPTY", "BLOCKED"], "EMPTY"),
        (["PASS"], "PASS"),
    ]
    for statuses, expected in cases:
        payload = _service(
            outcomes=[
                Outcome(f"Gate-{index}", status, status) for index, status in enumerate(statuses)
            ]
        ).design_report()
        assert payload.gate_status == expected


def test_design_report_uses_first_fixer_per_gate_and_first_failing_gate_for_next_tool() -> None:
    payload = _service(
        outcomes=[
            Outcome("Placement", "WARN", "review placement"),
            Outcome("Manufacturing", "FAIL", "review dfm"),
        ],
        fixers={
            "Placement": [Fixer("pcb_score_placement"), Fixer("unused_second")],
            "Manufacturing": [Fixer("manufacturing_quality_gate")],
        },
    ).design_report()

    assert payload.next_tool == "pcb_score_placement"
    assert "- [WARN] Placement: review placement" in payload.text
    assert "  -> Suggested: pcb_score_placement()" in payload.text
    assert "- [FAIL] Manufacturing: review dfm" in payload.text
    assert "  -> Suggested: manufacturing_quality_gate()" in payload.text


def test_design_report_uses_quality_gate_when_fixer_is_missing() -> None:
    payload = _service(
        outcomes=[Outcome("Unknown", "FAIL", "unknown failure")],
        fixers={},
    ).design_report()

    assert payload.next_tool == "project_quality_gate"
    assert "  -> Suggested: project_quality_gate()" in payload.text


def test_design_report_preserves_original_failing_order_without_sorting() -> None:
    payload = _service(
        outcomes=[
            Outcome("Zeta", "WARN", "first"),
            Outcome("Alpha", "FAIL", "second"),
        ],
        fixers={"Zeta": [Fixer("zeta_fix")], "Alpha": [Fixer("alpha_fix")]},
    ).design_report()

    assert payload.next_tool == "zeta_fix"
    assert payload.text.index("Zeta") < payload.text.index("Alpha")


def test_design_report_truncates_resolution_notes_to_eight() -> None:
    notes = [f"note-{index}" for index in range(10)]
    payload = _service(resolution=_resolution(notes=notes)).design_report()

    for index in range(8):
        assert f"- note-{index}" in payload.text
    assert "note-8" not in payload.text
    assert "note-9" not in payload.text


def test_design_report_preserves_intent_counters_source_and_mount_hole_constraint() -> None:
    intent = _intent(power_rails=2, interfaces=3, compliance=4, mount_holes=1)
    payload = _service(
        resolution=_resolution(intent=intent, source="legacy_design_intent")
    ).design_report()

    assert payload.intent_source == "legacy_design_intent"
    assert payload.power_rails_count == 2
    assert payload.interfaces_count == 3
    assert payload.compliance_count == 4
    assert payload.has_mechanical_constraint is True


def test_design_report_mechanical_constraint_detects_connector_or_max_height() -> None:
    connector_payload = _service(
        resolution=_resolution(intent=_intent(connector_placement=1))
    ).design_report()
    height_payload = _service(
        resolution=_resolution(intent=_intent(max_height_mm=12.5))
    ).design_report()
    empty_payload = _service(resolution=_resolution(intent=_intent())).design_report()

    assert connector_payload.has_mechanical_constraint is True
    assert height_payload.has_mechanical_constraint is True
    assert empty_payload.has_mechanical_constraint is False
