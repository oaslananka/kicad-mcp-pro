"""Project validation-loop orchestration independent of FastMCP."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class GateOutcomeLike(Protocol):
    """Structural gate outcome consumed by validation loops."""

    @property
    def name(self) -> str: ...

    @property
    def status(self) -> str: ...

    @property
    def summary(self) -> str: ...

    @property
    def details(self) -> list[str]: ...


class FixerActionLike(Protocol):
    """Structural fixer action consumed by validation loops."""

    @property
    def tool(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def auto_applicable(self) -> bool: ...

    @property
    def callable_import(self) -> str: ...


class AutoFixAction(BaseModel):
    """One step in the auto-fix loop action plan."""

    gate: str
    status: str
    auto_fixed: bool = False
    auto_fix_description: str = ""
    agent_tool: str = ""
    agent_description: str = ""
    sampling_guidance: str = ""


class AutoFixLoopPayload(BaseModel):
    """Structured result returned by project_auto_fix_loop."""

    text: str
    gate_status: str
    iterations_used: int = 0
    actions: list[AutoFixAction] = Field(default_factory=list)
    remaining_issues: int = 0
    ready_for_release: bool = False


SampleGuidance = Callable[[GateOutcomeLike], Awaitable[str]]
ProgressReporter = Callable[[float, float, str], Awaitable[None]]
CallableResolver = Callable[[str], Callable[[], object] | None]


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
class ProjectValidationLoopService:
    """Run bounded project validation/fix loops without FastMCP dependencies."""

    evaluate_project_gate: Callable[[], Sequence[GateOutcomeLike]]
    fixers_for_gate: Callable[[str], Sequence[FixerActionLike]]
    resolve_callable: CallableResolver

    async def auto_fix_loop(
        self,
        *,
        max_iterations: int = 5,
        sample_guidance: SampleGuidance,
        report_progress: ProgressReporter,
    ) -> AutoFixLoopPayload:
        """Run server-applicable fixes and return remaining agent actions."""
        max_iterations = max(1, min(max_iterations, 20))
        iterations_used = 0
        auto_fix_log: list[str] = []

        await report_progress(0, 100, "Project quality gate is being evaluated...")

        outcomes = list(self.evaluate_project_gate())
        iterations_used += 1

        for _iter in range(max_iterations - 1):
            applied_any = False
            for outcome in outcomes:
                if outcome.status == "PASS":
                    continue
                fixers = list(self.fixers_for_gate(outcome.name))
                auto_fixer = next((fixer for fixer in fixers if fixer.auto_applicable), None)
                if auto_fixer is None:
                    continue
                fn = self.resolve_callable(auto_fixer.callable_import)
                if fn is None:
                    continue
                try:
                    fix_result = fn()
                    auto_fix_log.append(
                        f"[iter {iterations_used}] Auto-fixed '{outcome.name}' "
                        f"via {auto_fixer.tool}: {fix_result}"
                    )
                    applied_any = True
                except Exception as exc:
                    auto_fix_log.append(
                        f"[iter {iterations_used}] Auto-fix '{auto_fixer.tool}' "
                        f"for '{outcome.name}' raised: {exc}"
                    )

            if not applied_any:
                break

            progress = min(90, 10 + (iterations_used * 15))
            await report_progress(
                progress,
                100,
                f"Re-evaluating quality gates after iteration {iterations_used}...",
            )
            outcomes = list(self.evaluate_project_gate())
            iterations_used += 1

            if all(outcome.status == "PASS" for outcome in outcomes):
                break

        actions: list[AutoFixAction] = []
        for outcome in outcomes:
            if outcome.status == "PASS":
                continue
            fixers = list(self.fixers_for_gate(outcome.name))
            auto_fixer = next((fixer for fixer in fixers if fixer.auto_applicable), None)
            agent_fixer = next((fixer for fixer in fixers if not fixer.auto_applicable), None)
            guidance = await sample_guidance(outcome)
            actions.append(
                AutoFixAction(
                    gate=outcome.name,
                    status=outcome.status,
                    auto_fixed=False,
                    auto_fix_description=(auto_fixer.description if auto_fixer is not None else ""),
                    agent_tool=(
                        (agent_fixer.tool if agent_fixer is not None else "")
                        or (auto_fixer.tool if auto_fixer is not None else "")
                    ),
                    agent_description=(
                        (agent_fixer.description if agent_fixer is not None else "")
                        or (auto_fixer.description if auto_fixer is not None else "")
                    ),
                    sampling_guidance=guidance,
                )
            )

        remaining = sum(1 for action in actions if not action.auto_fixed)
        ready = len(actions) == 0

        lines = [f"project_auto_fix_loop: {iterations_used}/{max_iterations} iteration(s) used."]
        if auto_fix_log:
            lines.append("Server-side auto-fixes applied:")
            lines.extend(f"  {entry}" for entry in auto_fix_log)
        if ready:
            lines.append("Status: PASS — all gates pass. Ready for manufacturing release.")
        else:
            lines.append(
                f"Status: {len(actions)} gate(s) still failing ({remaining} require agent action)."
            )
            for action in actions:
                lines.append(
                    f"  [AGENT] {action.gate}: call {action.agent_tool}() "
                    f"— {action.agent_description}"
                )
                if action.sampling_guidance:
                    lines.append(f"    Sampling guidance: {action.sampling_guidance}")
            lines.append("After applying the recommended tool, call project_auto_fix_loop() again.")

        combined = _combined_status(outcomes)

        await report_progress(100, 100, "Project auto-fix loop completed.")

        return AutoFixLoopPayload(
            text="\n".join(lines),
            gate_status=combined,
            iterations_used=iterations_used,
            actions=actions,
            remaining_issues=remaining,
            ready_for_release=ready,
        )

    def full_validation_loop(
        self,
        *,
        max_iterations: int = 5,
        fix_tier: Literal["auto_only", "suggest"] = "auto_only",
    ) -> AutoFixLoopPayload:
        """Run a bounded fix-and-rerun loop without sampling or progress."""
        max_iterations = max(1, min(max_iterations, 20))
        outcomes = list(self.evaluate_project_gate())
        fix_log: list[str] = []
        iterations_used = 1

        while iterations_used < max_iterations:
            if all(outcome.status == "PASS" for outcome in outcomes):
                break
            blocker = next((outcome for outcome in outcomes if outcome.status != "PASS"), None)
            if blocker is None:
                break
            fixers = list(self.fixers_for_gate(blocker.name))
            auto_fixer = next((fixer for fixer in fixers if fixer.auto_applicable), None)
            if auto_fixer is None or fix_tier == "suggest":
                break
            fn = self.resolve_callable(auto_fixer.callable_import)
            if fn is None:
                break
            try:
                fix_result = fn()
                fix_log.append(
                    f"[iter {iterations_used}] {blocker.name}: {auto_fixer.tool} -> {fix_result}"
                )
            except Exception as exc:
                fix_log.append(
                    f"[iter {iterations_used}] {blocker.name}: {auto_fixer.tool} raised {exc}"
                )
                break
            outcomes = list(self.evaluate_project_gate())
            iterations_used += 1

        actions: list[AutoFixAction] = []
        for outcome in outcomes:
            if outcome.status == "PASS":
                continue
            fixers = list(self.fixers_for_gate(outcome.name))
            agent_fixer = next((fixer for fixer in fixers if not fixer.auto_applicable), None)
            auto_fixer = next((fixer for fixer in fixers if fixer.auto_applicable), None)
            chosen = agent_fixer or auto_fixer
            actions.append(
                AutoFixAction(
                    gate=outcome.name,
                    status=outcome.status,
                    auto_fixed=False,
                    auto_fix_description=auto_fixer.description if auto_fixer else "",
                    agent_tool=chosen.tool if chosen else "project_quality_gate",
                    agent_description=chosen.description if chosen else outcome.summary,
                )
            )

        combined = _combined_status(outcomes)
        lines = [
            f"project_full_validation_loop: {iterations_used}/{max_iterations} iteration(s) used.",
        ]
        if fix_log:
            lines.append("Auto-fixes applied:")
            lines.extend(f"  {entry}" for entry in fix_log)
        if not actions:
            lines.append("PASS after validation loop.")
        elif fix_tier == "suggest":
            lines.append("Suggested fixes:")
            lines.extend(
                f"  [SUGGEST] {action.gate}: call {action.agent_tool}() "
                f"- {action.agent_description}"
                for action in actions
            )
        else:
            lines.append("PARTIAL: remaining issues require agent or manual action.")
            lines.extend(
                f"  [REMAINING] {action.gate}: call {action.agent_tool}() "
                f"- {action.agent_description}"
                for action in actions
            )
        return AutoFixLoopPayload(
            text="\n".join(lines),
            gate_status=combined,
            iterations_used=iterations_used,
            actions=actions,
            remaining_issues=len(actions),
            ready_for_release=not actions,
        )
