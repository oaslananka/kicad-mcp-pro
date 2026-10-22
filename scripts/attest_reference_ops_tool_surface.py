#!/usr/bin/env python3
"""Non-mutating MCP tool inventory check; never records benchmark success."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase, reviewed_mcp_tools
from scripts.check_reference_board_attempt_readiness import (
    _OPS_CONFIG,
    BOARD_IDS,
    ROOT,
    _ops_descriptor_matches,
    _pinned_uv_version,
    _read_ops_server_descriptor,
    preflight,
)

SCHEMA = "reference-ops-tool-attestation.v1"
_FORBIDDEN_ENV = frozenset(
    {
        "KICAD_API_SOCKET",
        "KICAD_MCP_KICAD_SOCKET_PATH",
        "KICAD_API_TOKEN",
        "KICAD_MCP_KICAD_TOKEN",
        "KICAD_MCP_REFERENCE_TRACE_PATH",
        "KICAD_MCP_REFERENCE_ATTEMPT_ID",
    }
)


def compare_tools(observed: list[str], reviewed: set[str]) -> dict[str, object]:
    """Exact allowlist: missing, extra and duplicate tools all block execution."""
    actual = set(observed)
    return {
        "matched": actual == reviewed and len(observed) == len(actual),
        "reviewed_count": len(reviewed),
        "observed_count": len(observed),
        "missing_count": len(reviewed - actual),
        "extra_count": len(actual - reviewed),
        "duplicate_count": len(observed) - len(actual),
        "tool_names_sha256": hashlib.sha256(
            ("\n".join(sorted(observed)) + "\n").encode()
        ).hexdigest(),
    }


async def list_live_tools(entry: dict[str, Any]) -> list[str]:
    """Initialize and list only; no KiCad write tools are invoked."""
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    env = {key: value for key, value in os.environ.items() if key not in _FORBIDDEN_ENV}
    env.update(entry["env"])
    for key in _FORBIDDEN_ENV:
        env.pop(key, None)
    params = StdioServerParameters(command=entry["command"], args=entry["args"], env=env)
    async with (
        asyncio.timeout(40),
        stdio_client(params) as stream,
        ClientSession(*stream) as session,
    ):
        await session.initialize()
        result = await session.list_tools()
        return [tool.name for tool in result.tools]


def attest(
    *,
    root: Path,
    board_id: str,
    attempt_number: int,
    phase_name: str,
    server_name: str,
    config_path: Path = _OPS_CONFIG,
    approved_source_revision: str | None = None,
) -> dict[str, object]:
    result = preflight(
        root=root,
        board_id=board_id,
        attempt_number=attempt_number,
        phase_name=phase_name,
        agent_runtime="chatgpt-ops",
        ops_server_name=server_name,
        ops_config_path=config_path,
        approved_source_revision=approved_source_revision,
    )
    report: dict[str, object] = {
        **result,
        "schema_version": SCHEMA,
        "tool_surface_attested": False,
        "executes_agent": False,
        "counts_as_task_success": False,
        "attempt_reserved": False,
    }
    if result["status"] != "handoff_required":
        return report
    entry = _read_ops_server_descriptor(config_path, server_name)
    version = _pinned_uv_version(root)
    phase = ReferenceAgentPhase.for_name(phase_name)
    reviewed_args = [
        "tool",
        "run",
        "--from",
        f"uv=={version}",
        "uv",
        "run",
        "--project",
        str(root.resolve()),
        "--no-dev",
        "python",
        "-m",
        "kicad_mcp.evals.reference_ops_server",
        "--phase",
        phase.name,
    ]
    if (
        entry is None
        or version is None
        or any(key in entry["env"] for key in _FORBIDDEN_ENV)
        or not _ops_descriptor_matches(entry, reviewed_args, phase)
    ):
        report.update(status="blocked", blocking_reasons=["reviewed_ops_mcp_server_unavailable"])
        return report
    try:
        reviewed = {
            t.removeprefix("mcp__kicad__")
            for t in reviewed_mcp_tools(ReferenceAgentPhase.for_name(phase_name))
        }
        measured = compare_tools(asyncio.run(list_live_tools(entry)), reviewed)
        report.update(measured)
        report["tool_surface_attested"] = measured["matched"]
        if not measured["matched"]:
            report.update(status="blocked", blocking_reasons=["reviewed_ops_tool_surface_mismatch"])
    except Exception as exc:
        # Only emit the exception class; messages may contain private paths or credentials.
        print(f"live attestation failed: {type(exc).__name__}", file=sys.stderr)
        report.update(
            status="blocked", blocking_reasons=["reviewed_ops_live_attestation_unavailable"]
        )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-id", choices=BOARD_IDS, required=True)
    parser.add_argument("--attempt-number", type=int, required=True, choices=range(1, 1000))
    parser.add_argument("--phase", choices=("schematic", "pcb"), required=True)
    parser.add_argument("--ops-server-name", required=True)
    parser.add_argument(
        "--approved-source-revision",
        required=True,
        help="Exactly the owner-reviewed 40-hex Git commit SHA",
    )
    args = parser.parse_args(argv)
    try:
        report = attest(
            root=ROOT,
            board_id=args.board_id,
            attempt_number=args.attempt_number,
            phase_name=args.phase,
            server_name=args.ops_server_name,
            approved_source_revision=args.approved_source_revision,
        )
    except (ValueError, OSError):
        report = {
            "schema_version": SCHEMA,
            "status": "blocked",
            "blocking_reasons": ["invalid_reviewed_attempt"],
            "tool_surface_attested": False,
            "attempt_reserved": False,
            "executes_agent": False,
            "counts_as_task_success": False,
        }
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] == "handoff_required" and report["tool_surface_attested"] else 2


if __name__ == "__main__":
    sys.exit(main())
