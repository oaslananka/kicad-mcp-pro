#!/usr/bin/env python3
"""Offline, read-only preflight for one reviewed reference-board agent attempt.

This never invokes an agent, edits a KiCad project or counts a board success.
The existing run_reference_board_agent.py remains the reviewed phase executor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Literal

from kicad_mcp.discovery import find_kicad_version
from kicad_mcp.evals.reference_agent_runner import (
    ReferenceAgentPhase,
    ReferenceAgentRunnerError,
    ReferenceAgentWorkspace,
    discover_reference_source_revision,
)

ROOT = Path(__file__).resolve().parents[1]
BOARD_IDS = ("esp32-c6-usbc", "stm32f072-usbc", "rp2350-usbc")
SCHEMA = "reference-agent-preflight.v1"
_BENCHMARK_METADATA = "benchmark.json"
_INPUTS = ("original-prompt.md", "specification.md", _BENCHMARK_METADATA, "quality-gates.json")


def _input_sha256(path: Path) -> str:
    """Hash only known regular, local review documents."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("input_not_a_reviewed_regular_file")
    if path.stat().st_size > 256_000:
        raise ValueError("input_not_a_reviewed_regular_file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_metadata(board_id: str, board_dir: Path) -> None:
    for name in (_BENCHMARK_METADATA, "quality-gates.json"):
        data = json.loads((board_dir / name).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("invalid_benchmark_metadata")
        if name == _BENCHMARK_METADATA:
            if (
                data.get("schema_version") != "pcb-task-outcome.v1"
                or data.get("benchmark_version") != "v1"
            ):
                raise ValueError("invalid_benchmark_metadata")
        elif (
            data.get("schema_version") != "pcb-reference-board-quality.v1"
            or data.get("board_id") != board_id
            or data.get("benchmark_version") != "v1"
        ):
            raise ValueError("invalid_benchmark_metadata")


def _kicad_10_cli_available() -> bool:
    """Probe version within a strict timeout without exposing machine output."""
    binary = shutil.which("kicad-cli")
    if binary is None:
        return False
    version = find_kicad_version(Path(binary))
    return version is not None and version.lstrip("v").startswith("10.")


AgentRuntime = Literal["claude", "chatgpt-ops"]
_OPS_CONFIG = Path.home() / ".config/ops-node/mcp.json"
_MAX_OPS_CONFIG_BYTES = 128_000


def _pinned_uv_version(root: Path) -> str | None:
    pin_file = root / "scripts/dev-toolchain.env"
    if pin_file.is_symlink() or not pin_file.is_file() or pin_file.stat().st_size > 8192:
        return None
    matches = [
        line.removeprefix("UV_VERSION=")
        for line in pin_file.read_text(encoding="utf-8").splitlines()
        if line.startswith("UV_VERSION=")
    ]
    if len(matches) != 1 or not all(c.isdigit() or c == "." for c in matches[0]):
        return None
    return matches[0]


def _reviewed_ops_server_available(
    *, root: Path, phase_name: str, server_name: str | None, config_path: Path
) -> bool:
    """Verify the local execution descriptor, not a live agent or tool call."""
    if not server_name or not server_name.startswith("kicad-"):
        return False
    if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in server_name):
        return False
    if config_path.is_symlink() or not config_path.is_file():
        return False
    try:
        stat = config_path.stat()
        if stat.st_size > _MAX_OPS_CONFIG_BYTES or stat.st_mode & 0o077:
            return False
        data = json.loads(config_path.read_text(encoding="utf-8"))
        entry = data["mcpServers"][server_name]
        if not isinstance(entry, dict):
            return False
        args = entry["args"]
        env = entry["env"]
        command = entry["command"]
        if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
            return False
        if not isinstance(env, dict) or not isinstance(command, str):
            return False
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
            return False
        from kicad_mcp.evals.reference_agent_runner import ReferenceAgentPhase

        phase = ReferenceAgentPhase.for_name(phase_name)
        version = _pinned_uv_version(root)
        if version is None:
            return False
        expected_args = [
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
        return (
            phase.name != "manufacturing"
            and entry.get("enabled") is True
            and entry.get("type") == "stdio"
            and Path(command).is_absolute()
            and Path(command).name == "uv"
            and Path(command).is_file()
            and args == expected_args
            and "KICAD_API_SOCKET" not in env
            and env.get("KICAD_MCP_PROFILE") == phase.profile
            and env.get("KICAD_MCP_OPERATING_MODE") == phase.mode
        )
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError):
        return False


def preflight(
    *,
    root: Path,
    board_id: str,
    attempt_number: int,
    phase_name: str,
    agent_runtime: AgentRuntime = "claude",
    ops_server_name: str | None = None,
    ops_config_path: Path = _OPS_CONFIG,
) -> dict[str, Any]:
    """Return machine-readable, sanitized readiness; never write an artifact."""
    workspace = ReferenceAgentWorkspace.for_reviewed_attempt(
        checkout_dir=root, board_id=board_id, attempt_number=attempt_number
    )
    phase = ReferenceAgentPhase.for_name(phase_name)
    board_dir = workspace.prompt_path.parent
    blocking: set[str] = set()
    hashes: dict[str, str] = {}
    for name in _INPUTS:
        try:
            hashes[name] = _input_sha256(board_dir / name)
        except (OSError, ValueError):
            blocking.add("missing_or_unreviewed_input")
    if len(hashes) == len(_INPUTS):
        try:
            _assert_metadata(board_id, board_dir)
        except (OSError, ValueError):
            blocking.add("invalid_benchmark_metadata")

    # Fail closed on reused attempts: do not overwrite a prior run or conceal
    # an already-counted attempt behind an empty fresh log.
    attempt_dir = workspace.agent_log_path.parent
    if attempt_dir.is_symlink() or attempt_dir.exists() or workspace.scratch_dir.exists():
        blocking.add("attempt_identity_already_used")
    source_revision: str | None = None
    try:
        source_revision = discover_reference_source_revision(root)
    except (OSError, ReferenceAgentRunnerError):
        blocking.add("source_revision_not_reproducible")
    if not _kicad_10_cli_available():
        blocking.add("kicad_10_cli_unavailable")
    if agent_runtime == "claude":
        if shutil.which("claude") is None:
            blocking.add("reviewed_agent_cli_unavailable")
    elif agent_runtime == "chatgpt-ops":
        if not _reviewed_ops_server_available(
            root=root,
            phase_name=phase_name,
            server_name=ops_server_name,
            config_path=ops_config_path,
        ):
            blocking.add("reviewed_ops_mcp_server_unavailable")
    else:
        raise ValueError("unsupported reviewed agent runtime")

    return {
        "schema_version": SCHEMA,
        "status": (
            "blocked" if blocking else "ready" if agent_runtime == "claude" else "handoff_required"
        ),
        "board_id": board_id,
        "benchmark_version": "v1",
        "attempt_id": workspace.attempt_id,
        "phase": phase.name,
        "profile": phase.profile,
        "operating_mode": phase.mode,
        "agent": agent_runtime,
        "mcp_server": ops_server_name if agent_runtime == "chatgpt-ops" else None,
        "live_tool_attestation_required": agent_runtime == "chatgpt-ops",
        "recorded_event_log_required": agent_runtime == "chatgpt-ops",
        "source_revision": source_revision,
        "reviewed_input_sha256": dict(sorted(hashes.items())),
        "blocking_reasons": sorted(blocking),
        "executes_agent": False,
        "counts_as_task_success": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board-id", choices=BOARD_IDS, required=True)
    parser.add_argument("--attempt-number", type=int, choices=range(1, 1000), required=True)
    parser.add_argument("--phase", choices=("schematic", "pcb", "manufacturing"), required=True)
    parser.add_argument("--agent-runtime", choices=("claude", "chatgpt-ops"), default="claude")
    parser.add_argument("--ops-server-name")
    parser.add_argument("--ops-config", type=Path, default=_OPS_CONFIG)
    args = parser.parse_args(argv)
    try:
        result = preflight(
            root=ROOT,
            board_id=args.board_id,
            attempt_number=args.attempt_number,
            phase_name=args.phase,
            agent_runtime=args.agent_runtime,
            ops_server_name=args.ops_server_name,
            ops_config_path=args.ops_config,
        )
    except (ValueError, OSError):
        print(
            json.dumps(
                {
                    "schema_version": SCHEMA,
                    "status": "blocked",
                    "blocking_reasons": ["invalid_reviewed_attempt"],
                },
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] in ("ready", "handoff_required") else 2


if __name__ == "__main__":
    sys.exit(main())
