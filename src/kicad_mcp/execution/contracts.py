"""Tool execution contracts for KiCad MCP Pro."""

from __future__ import annotations

import functools
import inspect
import time
from collections.abc import Callable, Coroutine
from typing import Any, TypeVar, cast

from kicad_mcp.models.tool_result import ToolResult

F = TypeVar("F", bound=Callable[..., Coroutine[Any, Any, Any]])


def tool_contract(
    tool_name: str | None = None,
    writes_files: bool = False,
    source_file_args: list[str] | None = None,
    human_gate: bool = False,
) -> Callable[[F], F]:
    """Decorate a tool function so it always returns a ``ToolResult`` envelope."""

    def decorator(fn: F) -> F:
        resolved_name = tool_name or fn.__name__

        @functools.wraps(fn)
        async def wrapper(*args: object, **kwargs: object) -> ToolResult:
            start = time.monotonic()
            try:
                raw_result = await fn(*args, **kwargs)
                if isinstance(raw_result, ToolResult):
                    result = raw_result
                elif isinstance(raw_result, dict):
                    result = ToolResult(
                        ok=bool(raw_result.get("ok", True)),
                        changed=bool(raw_result.get("changed", False)),
                        dry_run=bool(raw_result.get("dry_run", kwargs.get("dry_run", False))),
                        tool_name=resolved_name,
                        extra=raw_result,
                    )
                else:
                    result = ToolResult.success(
                        resolved_name,
                        changed=False,
                        dry_run=bool(kwargs.get("dry_run", False)),
                        extra={"raw": str(raw_result)},
                    )
            except Exception as exc:  # noqa: BLE001
                result = ToolResult.failure(resolved_name, str(exc))

            result.tool_name = resolved_name
            result.duration_ms = (time.monotonic() - start) * 1000
            if human_gate:
                result.human_gate_required = True

            if writes_files and source_file_args:
                bound = inspect.signature(fn).bind_partial(*args, **kwargs)
                result.extra.setdefault(
                    "contract_source_files",
                    [
                        str(bound.arguments[arg_name])
                        for arg_name in source_file_args
                        if arg_name in bound.arguments
                    ],
                )

            return result

        return cast(F, wrapper)

    return decorator
