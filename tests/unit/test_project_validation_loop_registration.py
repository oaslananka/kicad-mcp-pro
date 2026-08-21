from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP

from kicad_mcp.project.validation_loops import AutoFixAction, AutoFixLoopPayload, GateOutcomeLike
from kicad_mcp.tools.metadata import get_tool_metadata
from kicad_mcp.tools.project_validation_loops import (
    ProjectValidationLoopDependencies,
    _report_progress,
    _sample_guidance,
    register,
    resolve_fixer_callable,
)


@dataclass
class Outcome:
    name: str
    status: str
    summary: str
    details: list[str] = field(default_factory=list)


class FakeValidationLoopService:
    def __init__(self) -> None:
        self.auto_iterations: list[int] = []
        self.full_calls: list[tuple[int, str]] = []

    async def auto_fix_loop(
        self,
        *,
        max_iterations: int,
        sample_guidance: Callable[[GateOutcomeLike], Awaitable[str]],
        report_progress: Callable[[float, float, str], Awaitable[None]],
    ) -> AutoFixLoopPayload:
        self.auto_iterations.append(max_iterations)
        guidance = await sample_guidance(
            Outcome("Placement", "WARN", "review placement", ["caps too far"])
        )
        await report_progress(25, 100, "adapter-progress")
        return AutoFixLoopPayload(
            text="auto-result",
            gate_status="WARN",
            actions=[
                AutoFixAction(
                    gate="Placement",
                    status="WARN",
                    sampling_guidance=guidance,
                )
            ],
            remaining_issues=1,
        )

    def full_validation_loop(
        self,
        *,
        max_iterations: int,
        fix_tier: str,
    ) -> AutoFixLoopPayload:
        self.full_calls.append((max_iterations, fix_tier))
        return AutoFixLoopPayload(text="full-result", gate_status="PASS", ready_for_release=True)


class FakeContext:
    def __init__(
        self,
        *,
        sample_error: Exception | None = None,
        progress_error: Exception | None = None,
    ) -> None:
        self.sample_error = sample_error
        self.progress_error = progress_error
        self.sample_calls: list[dict[str, Any]] = []
        self.progress_calls: list[tuple[float, float, str]] = []

    async def sample(
        self,
        *,
        messages: list[dict[str, str]],
        max_tokens: int,
        system_prompt: str,
    ) -> object:
        self.sample_calls.append(
            {
                "messages": messages,
                "max_tokens": max_tokens,
                "system_prompt": system_prompt,
            }
        )
        if self.sample_error is not None:
            raise self.sample_error
        return SimpleNamespace(content=[SimpleNamespace(text="sampled guidance")])

    async def report_progress(self, current: float, total: float, message: str) -> None:
        self.progress_calls.append((current, total, message))
        if self.progress_error is not None:
            raise self.progress_error


def _prompt_builder(name: str, summary: str, details: list[str] | None = None) -> str:
    return f"prompt::{name}::{summary}::{details}"


def _registered() -> tuple[FastMCP, FakeValidationLoopService]:
    mcp = FastMCP("project-validation-loops-test")
    service = FakeValidationLoopService()
    register(
        mcp,
        ProjectValidationLoopDependencies(
            service=service,
            sampling_prompt_for_gate=_prompt_builder,
        ),
    )
    return mcp, service


def test_registration_preserves_exact_tool_order_schemas_descriptions_and_metadata() -> None:
    mcp, _service = _registered()
    tools = mcp._tool_manager.list_tools()

    assert [tool.name for tool in tools] == [
        "project_auto_fix_loop",
        "project_full_validation_loop",
    ]
    auto, full = tools
    assert auto.parameters == {
        "properties": {
            "max_iterations": {"default": 5, "title": "Max Iterations", "type": "integer"},
        },
        "title": "project_auto_fix_loopArguments",
        "type": "object",
    }
    assert full.parameters == {
        "properties": {
            "max_iterations": {"default": 5, "title": "Max Iterations", "type": "integer"},
            "fix_tier": {
                "default": "auto_only",
                "enum": ["auto_only", "suggest"],
                "title": "Fix Tier",
                "type": "string",
            },
        },
        "title": "project_full_validation_loopArguments",
        "type": "object",
    }
    assert auto.description == (
        "Run the project quality gate and automatically apply server-side fixes.\n\n"
        "Each iteration:\n"
        "1. Evaluates all project quality gates.\n"
        "2. For **auto-applicable** gates (annotation, zone refill) — calls the\n"
        "   underlying fix implementation directly on the server, then re-evaluates.\n"
        "3. For gates requiring **agent action** — returns the tool name and\n"
        "   description so the agent can call it, then the agent must call this\n"
        "   tool again to continue.\n\n"
        "The loop runs up to ``max_iterations`` times applying auto-fixes.  It\n"
        "stops early when all gates pass or when no further auto-fix is possible\n"
        "without agent involvement.\n\n"
        "Args:\n"
        "    max_iterations: Maximum number of auto-fix + re-evaluate cycles to\n"
        "        attempt before returning control to the agent (1–20).\n"
    )
    assert (
        full.description == "Run ERC/DRC/project gates in a bounded fix-and-rerun validation loop."
    )
    for name in ("project_auto_fix_loop", "project_full_validation_loop"):
        metadata = get_tool_metadata(name)
        assert metadata is not None
        assert metadata.headless_compatible is True


@pytest.mark.anyio
async def test_registration_bridges_context_sampling_and_progress() -> None:
    mcp, service = _registered()
    auto = mcp._tool_manager.list_tools()[0]
    ctx = FakeContext()

    result = await auto.fn(max_iterations=7, ctx=ctx)

    assert result.text == "auto-result"
    assert result.actions[0].sampling_guidance == "sampled guidance"
    assert service.auto_iterations == [7]
    assert ctx.progress_calls == [(25, 100, "adapter-progress")]
    assert len(ctx.sample_calls) == 1
    sample_call = ctx.sample_calls[0]
    assert sample_call["messages"] == [
        {
            "role": "user",
            "content": "prompt::Placement::review placement::['caps too far']",
        }
    ]
    assert sample_call["max_tokens"] == 256
    assert sample_call["system_prompt"] == "You are a KiCad expert. Reply briefly and directly."


def test_registration_delegates_full_validation_loop() -> None:
    mcp, service = _registered()
    full = mcp._tool_manager.list_tools()[1]

    result = full.fn(max_iterations=9, fix_tier="suggest")

    assert result.text == "full-result"
    assert service.full_calls == [(9, "suggest")]


@pytest.mark.anyio
async def test_sampling_bridge_returns_empty_when_context_or_sampling_fails() -> None:
    outcome = Outcome("PCB", "FAIL", "drc failed")

    assert await _sample_guidance(None, outcome, _prompt_builder) == ""
    assert (
        await _sample_guidance(
            FakeContext(sample_error=RuntimeError("sampling unavailable")),
            outcome,
            _prompt_builder,
        )
        == ""
    )


@pytest.mark.anyio
async def test_progress_bridge_ignores_value_error_only() -> None:
    ctx = FakeContext(progress_error=ValueError("progress unsupported"))

    await _report_progress(ctx, 5, 100, "message")

    assert ctx.progress_calls == [(5, 100, "message")]

    with pytest.raises(RuntimeError, match="transport failed"):
        await _report_progress(
            FakeContext(progress_error=RuntimeError("transport failed")),
            5,
            100,
            "message",
        )


def test_resolve_fixer_callable_handles_valid_missing_and_malformed_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kicad_mcp.tools import project_validation_loops as adapter

    def target() -> str:
        return "fixed"

    monkeypatch.setattr(
        adapter.importlib,
        "import_module",
        lambda name: SimpleNamespace(target=target) if name == "kicad_mcp.tools.fake" else None,
    )

    assert resolve_fixer_callable("tools.fake:target") is target
    assert resolve_fixer_callable("tools.fake:missing") is None
    assert resolve_fixer_callable("malformed") is None
    assert resolve_fixer_callable("") is None
