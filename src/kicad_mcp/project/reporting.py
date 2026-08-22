"""Read-only project quality reporting independent of FastMCP."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel

ProjectSpecSource = Literal["project_spec", "legacy_design_intent", "none"]


class GateOutcomeLike(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def summary(self) -> str: ...

    @property
    def details(self) -> list[str]: ...


class FixerActionLike(Protocol):
    @property
    def tool(self) -> str: ...


class MechanicalConstraintLike(Protocol):
    @property
    def mount_holes(self) -> Sequence[object]: ...

    @property
    def connector_placement(self) -> Sequence[object]: ...

    @property
    def max_height_mm(self) -> float | None: ...


class ProjectDesignIntentLike(Protocol):
    @property
    def power_rails(self) -> Sequence[object]: ...

    @property
    def interfaces(self) -> Sequence[object]: ...

    @property
    def compliance(self) -> Sequence[object]: ...

    @property
    def mechanical(self) -> MechanicalConstraintLike: ...


class ProjectSpecResolutionLike(Protocol):
    @property
    def source(self) -> ProjectSpecSource: ...

    @property
    def resolved(self) -> ProjectDesignIntentLike: ...

    @property
    def notes(self) -> list[str]: ...


class GateHistoryLike(Protocol):
    def trend(self, gate_name: str, last_n: int) -> Sequence[object]: ...

    def regression_check(self) -> list[str]: ...


class DesignReportPayload(BaseModel):
    """Comprehensive design-status report combining intent, gates, and recommended actions."""

    text: str
    gate_status: str
    intent_source: ProjectSpecSource = "none"
    power_rails_count: int = 0
    interfaces_count: int = 0
    compliance_count: int = 0
    has_mechanical_constraint: bool = False
    next_tool: str = ""


def _combined_status(outcomes: Sequence[GateOutcomeLike]) -> str:
    statuses = {outcome.status for outcome in outcomes}
    if "EMPTY" in statuses:
        return "EMPTY"
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "FAIL" in statuses:
        return "FAIL"
    if "WARN" in statuses:
        return "WARN"
    return "PASS"


@dataclass(frozen=True, slots=True)
class ProjectReportingService:
    """Render persisted gate history and current project design status."""

    history_for_active_project: Callable[[], GateHistoryLike]
    resolve_design_intent: Callable[[], ProjectSpecResolutionLike]
    render_design_intent: Callable[[ProjectDesignIntentLike], str]
    evaluate_project_gate: Callable[[], Sequence[GateOutcomeLike]]
    fixers_for_gate: Callable[[str], Sequence[FixerActionLike]]

    def gate_trend(self, gate_name: str, last_n: int = 10) -> str:
        history = self.history_for_active_project()
        payload = {
            "gate_name": gate_name,
            "history": history.trend(gate_name, max(1, min(last_n, 100))),
            "regressions": history.regression_check(),
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    def design_report(self) -> DesignReportPayload:
        resolution = self.resolve_design_intent()
        intent = resolution.resolved

        outcomes = list(self.evaluate_project_gate())
        combined = _combined_status(outcomes)
        failing = [outcome for outcome in outcomes if outcome.status != "PASS"]

        lines = [
            "# Project Design Report",
            "",
            "## Design Intent",
            self.render_design_intent(intent),
            "",
            f"## Gate Status: {combined}",
        ]
        if failing:
            lines.append(f"Failing gates ({len(failing)}):")
            for outcome in failing:
                fixers = list(self.fixers_for_gate(outcome.name))
                hint = fixers[0].tool if fixers else "project_quality_gate"
                lines.append(f"- [{outcome.status}] {outcome.name}: {outcome.summary}")
                lines.append(f"  -> Suggested: {hint}()")
        else:
            lines.append("All gates PASS — ready for export_manufacturing_package().")

        lines += [
            "",
            "## Resolution Notes",
            *[f"- {note}" for note in resolution.notes[:8]],
        ]

        next_tool = failing[0].name if failing else "export_manufacturing_package"
        if failing:
            fixers = list(self.fixers_for_gate(failing[0].name))
            next_tool = fixers[0].tool if fixers else "project_quality_gate"

        return DesignReportPayload(
            text="\n".join(lines),
            gate_status=combined,
            intent_source=resolution.source,
            power_rails_count=len(intent.power_rails),
            interfaces_count=len(intent.interfaces),
            compliance_count=len(intent.compliance),
            has_mechanical_constraint=(
                bool(intent.mechanical.mount_holes)
                or bool(intent.mechanical.connector_placement)
                or intent.mechanical.max_height_mm is not None
            ),
            next_tool=next_tool,
        )
