"""Project next-action recommendation logic independent of FastMCP."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field

from ..models.verdict import Finding, SuggestedFix, Verdict, stable_finding_id


class GateOutcomeLike(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def summary(self) -> str: ...

    @property
    def details(self) -> list[str]: ...


class ProjectNextActionPayload(BaseModel):
    """Structured next-action recommendation derived from the project gate."""

    text: str
    status: str
    verdict: Verdict = "PASS"
    gate: str = ""
    reason: str = ""
    suggested_tool: str = ""
    findings: list[Finding] = Field(default_factory=list)
    next_action: str = ""


def _queue_reason_from_details(details: list[str], summary: str) -> str:
    for detail in details:
        cleaned = detail.strip()
        if cleaned.startswith("FAIL: "):
            return cleaned[6:]
        if cleaned.startswith("WARN: "):
            return cleaned[6:]
        if cleaned.startswith("BLOCKED: "):
            return cleaned[9:]
    return summary


def _suggested_tool_for_gate(name: str) -> str:
    return {
        "Schematic": "run_erc()",
        "Schematic connectivity": "schematic_connectivity_gate()",
        "PCB": "run_drc()",
        "Placement": "pcb_score_placement()",
        "PCB transfer": "pcb_transfer_quality_gate()",
        "Manufacturing": "manufacturing_quality_gate()",
        "Footprint parity": "validate_footprints_vs_schematic()",
    }.get(name, "project_quality_gate()")


def _tool_name_from_hint(tool_hint: str) -> str:
    return tool_hint.removesuffix("()")


def _next_action_finding(*, status: str, gate: str, reason: str, suggested_tool: str) -> Finding:
    severity = "warning" if status == "EMPTY" else "error"
    return Finding(
        id=stable_finding_id("project_next_action", gate or "project", status, reason),
        severity=severity,
        location=gate or "Project",
        description=reason,
        suggested_fix=SuggestedFix(tool=_tool_name_from_hint(suggested_tool), args={}),
    )


@dataclass(frozen=True, slots=True)
class ProjectNextActionService:
    """Derive the highest-priority next action from project gate outcomes."""

    evaluate_project_gate: Callable[[], Sequence[GateOutcomeLike]]

    def next_action(self) -> ProjectNextActionPayload:
        try:
            outcomes = list(self.evaluate_project_gate())
        except Exception as exc:
            reason = f"Project quality gate could not be evaluated: {exc}"
            suggested_tool = "kicad_get_project_info()"
            lines = [
                "Project next action:",
                "- Status: BLOCKED",
                f"- Suggested tool: {suggested_tool}",
                f"- Reason: {reason}",
            ]
            return ProjectNextActionPayload(
                text="\n".join(lines),
                status="BLOCKED",
                verdict="FAIL",
                reason=reason,
                suggested_tool=suggested_tool,
                findings=[
                    _next_action_finding(
                        status="BLOCKED",
                        gate="Project",
                        reason=reason,
                        suggested_tool=suggested_tool,
                    )
                ],
                next_action=suggested_tool,
            )

        actionable = [outcome for outcome in outcomes if outcome.status != "PASS"]
        if not actionable:
            suggested_tool = "export_manufacturing_package()"
            reason = "No blocking issues remain."
            lines = [
                "Project next action:",
                "- Status: PASS",
                f"- Suggested tool: {suggested_tool}",
                f"- Reason: {reason}",
            ]
            return ProjectNextActionPayload(
                text="\n".join(lines),
                status="PASS",
                verdict="PASS",
                reason=reason,
                suggested_tool=suggested_tool,
                next_action=suggested_tool,
            )

        actionable.sort(key=lambda outcome: (0 if outcome.status == "BLOCKED" else 1, outcome.name))
        target = actionable[0]
        reason = _queue_reason_from_details(target.details, target.summary)
        suggested_tool = _suggested_tool_for_gate(target.name)
        lines = [
            "Project next action:",
            f"- Status: {target.status}",
            f"- Gate: {target.name}",
            f"- Suggested tool: {suggested_tool}",
            f"- Reason: {reason}",
        ]
        return ProjectNextActionPayload(
            text="\n".join(lines),
            status=target.status,
            verdict="WARN" if target.status == "EMPTY" else "FAIL",
            gate=target.name,
            reason=reason,
            suggested_tool=suggested_tool,
            findings=[
                _next_action_finding(
                    status=target.status,
                    gate=target.name,
                    reason=reason,
                    suggested_tool=suggested_tool,
                )
            ],
            next_action=suggested_tool,
        )
