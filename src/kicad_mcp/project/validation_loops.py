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

    @staticmethod
    def _auto_fixer(fixers: Sequence[FixerActionLike]) -> FixerActionLike | None:
        return next((fixer for fixer in fixers if fixer.auto_applicable), None)

    @staticmethod
    def _agent_fixer(fixers: Sequence[FixerActionLike]) -> FixerActionLike | None:
        return next((fixer for fixer in fixers if not fixer.auto_applicable), None)

    def _apply_auto_fixes(
        self,
        outcomes: Sequence[GateOutcomeLike],
        *,
        iteration: int,
        log: list[str],
    ) -> bool:
        applied_any = False
        for outcome in outcomes:
            if outcome.status == "PASS":
                continue
            auto_fixer = self._auto_fixer(list(self.fixers_for_gate(outcome.name)))
            if auto_fixer is None:
                continue
            fn = self.resolve_callable(auto_fixer.callable_import)
            if fn is None:
                continue
            try:
                fix_result = fn()
                log.append(
                    f"[iter {iteration}] Auto-fixed '{outcome.name}' "
                    f"via {auto_fixer.tool}: {fix_result}"
                )
                applied_any = True
            except Exception as exc:
                log.append(
                    f"[iter {iteration}] Auto-fix '{auto_fixer.tool}' "
                    f"for '{outcome.name}' raised: {exc}"
                )
        return applied_any

    async def _auto_fix_actions(
        self,
        outcomes: Sequence[GateOutcomeLike],
        sample_guidance: SampleGuidance,
    ) -> list[AutoFixAction]:
        actions: list[AutoFixAction] = []
        for outcome in outcomes:
            if outcome.status == "PASS":
                continue
            fixers = list(self.fixers_for_gate(outcome.name))
            auto_fixer = self._auto_fixer(fixers)
            agent_fixer = self._agent_fixer(fixers)
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
        return actions

    @staticmethod
    def _auto_fix_lines(
        *,
        iterations_used: int,
        max_iterations: int,
        auto_fix_log: Sequence[str],
        actions: Sequence[AutoFixAction],
    ) -> list[str]:
        remaining = sum(1 for action in actions if not action.auto_fixed)
        lines = [f"project_auto_fix_loop: {iterations_used}/{max_iterations} iteration(s) used."]
        if auto_fix_log:
            lines.append("Server-side auto-fixes applied:")
            lines.extend(f"  {entry}" for entry in auto_fix_log)
        if not actions:
            lines.append("Status: PASS — all gates pass. Ready for manufacturing release.")
            return lines
        remaining_summary = f"{remaining} require agent action"
        lines.append(f"Status: {len(actions)} gate(s) still failing ({remaining_summary}).")
        for action in actions:
            lines.append(
                f"  [AGENT] {action.gate}: call {action.agent_tool}() — {action.agent_description}"
            )
            if action.sampling_guidance:
                lines.append(f"    Sampling guidance: {action.sampling_guidance}")
        lines.append("After applying the recommended tool, call project_auto_fix_loop() again.")
        return lines

    async def auto_fix_loop(
        self,
        *,
        max_iterations: int = 5,
        sample_guidance: SampleGuidance,
        report_progress: ProgressReporter,
    ) -> AutoFixLoopPayload:
        """Run server-applicable fixes and return remaining agent actions."""
        max_iterations = max(1, min(max_iterations, 20))
        iterations_used = 1
        auto_fix_log: list[str] = []

        await report_progress(0, 100, "Project quality gate is being evaluated...")
        outcomes = list(self.evaluate_project_gate())

        for _iteration in range(max_iterations - 1):
            if not self._apply_auto_fixes(
                outcomes,
                iteration=iterations_used,
                log=auto_fix_log,
            ):
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

        actions = await self._auto_fix_actions(outcomes, sample_guidance)
        remaining = sum(1 for action in actions if not action.auto_fixed)
        ready = not actions
        lines = self._auto_fix_lines(
            iterations_used=iterations_used,
            max_iterations=max_iterations,
            auto_fix_log=auto_fix_log,
            actions=actions,
        )
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

    def _resolve_full_auto_fix(
        self,
        blocker: GateOutcomeLike,
        fix_tier: Literal["auto_only", "suggest"],
    ) -> tuple[FixerActionLike, Callable[[], object]] | None:
        if fix_tier == "suggest":
            return None
        auto_fixer = self._auto_fixer(list(self.fixers_for_gate(blocker.name)))
        if auto_fixer is None:
            return None
        fn = self.resolve_callable(auto_fixer.callable_import)
        if fn is None:
            return None
        return auto_fixer, fn

    def _run_full_iterations(
        self,
        *,
        outcomes: list[GateOutcomeLike],
        max_iterations: int,
        fix_tier: Literal["auto_only", "suggest"],
    ) -> tuple[list[GateOutcomeLike], list[str], int]:
        fix_log: list[str] = []
        iterations_used = 1
        while iterations_used < max_iterations:
            if all(outcome.status == "PASS" for outcome in outcomes):
                break
            blocker = next(outcome for outcome in outcomes if outcome.status != "PASS")
            resolved = self._resolve_full_auto_fix(blocker, fix_tier)
            if resolved is None:
                break
            auto_fixer, fn = resolved
            try:
                fix_result = fn()
            except Exception as exc:
                fix_log.append(
                    f"[iter {iterations_used}] {blocker.name}: {auto_fixer.tool} raised {exc}"
                )
                break
            fix_log.append(
                f"[iter {iterations_used}] {blocker.name}: {auto_fixer.tool} -> {fix_result}"
            )
            outcomes = list(self.evaluate_project_gate())
            iterations_used += 1
        return outcomes, fix_log, iterations_used

    def _full_validation_actions(
        self,
        outcomes: Sequence[GateOutcomeLike],
    ) -> list[AutoFixAction]:
        actions: list[AutoFixAction] = []
        for outcome in outcomes:
            if outcome.status == "PASS":
                continue
            fixers = list(self.fixers_for_gate(outcome.name))
            agent_fixer = self._agent_fixer(fixers)
            auto_fixer = self._auto_fixer(fixers)
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
        return actions

    @staticmethod
    def _full_validation_lines(
        *,
        iterations_used: int,
        max_iterations: int,
        fix_log: Sequence[str],
        actions: Sequence[AutoFixAction],
        fix_tier: Literal["auto_only", "suggest"],
    ) -> list[str]:
        lines = [
            f"project_full_validation_loop: {iterations_used}/{max_iterations} iteration(s) used.",
        ]
        if fix_log:
            lines.append("Auto-fixes applied:")
            lines.extend(f"  {entry}" for entry in fix_log)
        if not actions:
            lines.append("PASS after validation loop.")
            return lines
        if fix_tier == "suggest":
            lines.append("Suggested fixes:")
            prefix = "SUGGEST"
        else:
            lines.append("PARTIAL: remaining issues require agent or manual action.")
            prefix = "REMAINING"
        lines.extend(
            f"  [{prefix}] {action.gate}: call {action.agent_tool}() - {action.agent_description}"
            for action in actions
        )
        return lines

    def full_validation_loop(
        self,
        *,
        max_iterations: int = 5,
        fix_tier: Literal["auto_only", "suggest"] = "auto_only",
    ) -> AutoFixLoopPayload:
        """Run a bounded fix-and-rerun loop without sampling or progress."""
        max_iterations = max(1, min(max_iterations, 20))
        outcomes, fix_log, iterations_used = self._run_full_iterations(
            outcomes=list(self.evaluate_project_gate()),
            max_iterations=max_iterations,
            fix_tier=fix_tier,
        )
        actions = self._full_validation_actions(outcomes)
        lines = self._full_validation_lines(
            iterations_used=iterations_used,
            max_iterations=max_iterations,
            fix_log=fix_log,
            actions=actions,
            fix_tier=fix_tier,
        )
        return AutoFixLoopPayload(
            text="\n".join(lines),
            gate_status=_combined_status(outcomes),
            iterations_used=iterations_used,
            actions=actions,
            remaining_issues=len(actions),
            ready_for_release=not actions,
        )
