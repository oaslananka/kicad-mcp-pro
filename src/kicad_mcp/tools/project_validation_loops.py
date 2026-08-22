"""Thin FastMCP adapter for project validation loops."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from mcp.server.fastmcp import Context, FastMCP

from ..project.validation_loops import AutoFixLoopPayload, GateOutcomeLike
from .metadata import headless_compatible

SamplingPromptBuilder = Callable[[str, str, list[str] | None], str]
SampleGuidance = Callable[[GateOutcomeLike], Awaitable[str]]
ProgressReporter = Callable[[float, float, str], Awaitable[None]]


class ValidationLoopService(Protocol):
    async def auto_fix_loop(
        self,
        *,
        max_iterations: int,
        sample_guidance: SampleGuidance,
        report_progress: ProgressReporter,
    ) -> AutoFixLoopPayload: ...

    def full_validation_loop(
        self,
        *,
        max_iterations: int,
        fix_tier: Literal["auto_only", "suggest"],
    ) -> AutoFixLoopPayload: ...


@dataclass(frozen=True)
class ProjectValidationLoopDependencies:
    """Validation-loop service and sampling prompt bridge."""

    service: ValidationLoopService
    sampling_prompt_for_gate: SamplingPromptBuilder


def resolve_fixer_callable(import_str: str) -> Callable[[], object] | None:
    """Resolve a package-relative fixer callable, returning None when unavailable."""
    if not import_str:
        return None
    try:
        mod_path, func_name = import_str.rsplit(":", 1)
        module = importlib.import_module(f"kicad_mcp.{mod_path}")
        candidate = getattr(module, func_name, None)
        return candidate if callable(candidate) else None
    except Exception:
        return None


async def _sample_guidance(
    ctx: Context[Any, Any, Any] | None,
    outcome: GateOutcomeLike,
    prompt_builder: SamplingPromptBuilder,
) -> str:
    if ctx is None:
        return ""
    sample = getattr(ctx, "sample", None)
    if not callable(sample):
        return ""
    try:
        result = await sample(
            messages=[
                {
                    "role": "user",
                    "content": prompt_builder(outcome.name, outcome.summary, outcome.details),
                }
            ],
            max_tokens=256,
            system_prompt="You are a KiCad expert. Reply briefly and directly.",
        )
    except Exception:
        return ""

    content = getattr(result, "content", None)
    if isinstance(content, list) and content:
        return str(getattr(content[0], "text", "") or "")
    return ""


async def _report_progress(
    ctx: Context[Any, Any, Any] | None,
    current: float,
    total: float,
    message: str,
) -> None:
    if ctx is None:
        return
    try:
        await ctx.report_progress(current, total, message)
    except ValueError:
        return


def register(mcp: FastMCP, dependencies: ProjectValidationLoopDependencies) -> None:
    """Register project validation-loop tools at their legacy public positions."""
    service = dependencies.service
    prompt_builder = dependencies.sampling_prompt_for_gate

    @mcp.tool()
    @headless_compatible
    async def project_auto_fix_loop(
        max_iterations: int = 5,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> AutoFixLoopPayload:
        """Run the project quality gate and automatically apply server-side fixes.

        Each iteration:
        1. Evaluates all project quality gates.
        2. For **auto-applicable** gates (annotation, zone refill) — calls the
           underlying fix implementation directly on the server, then re-evaluates.
        3. For gates requiring **agent action** — returns the tool name and
           description so the agent can call it, then the agent must call this
           tool again to continue.

        The loop runs up to ``max_iterations`` times applying auto-fixes.  It
        stops early when all gates pass or when no further auto-fix is possible
        without agent involvement.

        Args:
            max_iterations: Maximum number of auto-fix + re-evaluate cycles to
                attempt before returning control to the agent (1–20).
        """

        async def sample_guidance(outcome: GateOutcomeLike) -> str:
            return await _sample_guidance(ctx, outcome, prompt_builder)

        async def report_progress(current: float, total: float, message: str) -> None:
            await _report_progress(ctx, current, total, message)

        return await service.auto_fix_loop(
            max_iterations=max_iterations,
            sample_guidance=sample_guidance,
            report_progress=report_progress,
        )

    @mcp.tool()
    @headless_compatible
    def project_full_validation_loop(
        max_iterations: int = 5,
        fix_tier: Literal["auto_only", "suggest"] = "auto_only",
    ) -> AutoFixLoopPayload:
        """Run ERC/DRC/project gates in a bounded fix-and-rerun validation loop."""
        return service.full_validation_loop(
            max_iterations=max_iterations,
            fix_tier=fix_tier,
        )
