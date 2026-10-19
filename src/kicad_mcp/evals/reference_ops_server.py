"""Strict phase-limited MCP stdio host for an external ChatGPT–Ops benchmark.

This process only exposes approved tools; it does not start a ChatGPT session,
reserve an attempt, or publish evidence. The live invocation transcript must
still be independently captured and validated before scoring an attempt.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path
from typing import cast

from ..config import get_config, reset_config
from ..server import KiCadFastMCP, _ensure_thread_aware_stdout, build_server
from .reference_agent_runner import (
    ReferenceAgentPhase,
    ReferenceAgentRunnerError,
    reviewed_mcp_tools,
)
from .reference_ops_trace import ReviewedOpsTraceMiddleware, configured_trace

_PREFIX = "mcp__kicad__"


def build_reference_ops_server(*, phase_name: str, defer_registration: bool = True) -> KiCadFastMCP:
    """Enforce the exact reviewed phase tools at discovery AND invocation."""
    phase = ReferenceAgentPhase.for_name(phase_name)
    if phase.name == "manufacturing":
        raise ReferenceAgentRunnerError("ChatGPT Ops manufacturing phase is not approved")
    cfg = get_config()
    if cfg.profile != phase.profile or cfg.operating_mode != phase.mode:
        raise ReferenceAgentRunnerError("ChatGPT Ops phase profile/mode mismatch")
    server = cast(KiCadFastMCP, build_server(phase.profile, defer_registration=defer_registration))
    exact = {tool.removeprefix(_PREFIX) for tool in reviewed_mcp_tools(phase)}
    server.allowed_tool_names = exact
    server.execution_tool_names = exact
    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", choices=("schematic", "pcb"), required=True)
    args = parser.parse_args(argv)
    with contextlib.redirect_stdout(sys.stderr):
        reset_config()
        config = get_config()
        if config.transport != "stdio":
            raise SystemExit("reviewed ChatGPT Ops server requires stdio transport")
        try:
            server = build_reference_ops_server(phase_name=args.phase)
            trace = configured_trace(checkout=Path(__file__).resolve().parents[3])
            if trace is not None:
                server.middleware.append(ReviewedOpsTraceMiddleware(trace))
        except (ValueError, OSError) as exc:
            raise SystemExit(str(exc)) from None
    _ensure_thread_aware_stdout()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
