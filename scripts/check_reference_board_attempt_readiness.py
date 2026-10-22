#!/usr/bin/env python3
"""Offline, read-only preflight for one reviewed reference-board agent attempt.

This never invokes an agent, edits a KiCad project or counts a board success.
The existing run_reference_board_agent.py remains the reviewed phase executor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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
from scripts.check_reference_live_gui_readiness import probe_live_gui

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


def _read_ops_server_descriptor(config_path: Path, server_name: str) -> dict[str, Any] | None:
    """Read only a fixed local config or injected test fixture; never execute it."""
    if config_path.is_symlink() or not config_path.is_file():
        return None
    try:
        stat = config_path.stat()
        if stat.st_size > _MAX_OPS_CONFIG_BYTES or stat.st_mode & 0o077:
            return None
        data = json.loads(config_path.read_text(encoding="utf-8"))
        entry = data["mcpServers"][server_name]
        return entry if isinstance(entry, dict) else None
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return None


def _is_reviewed_uv_command(command: object) -> bool:
    """Accept the installed UV executable locations, not arbitrary input paths."""
    if not isinstance(command, str):
        return False
    home = Path.home()
    allowed = (
        home / ".local/bin/uv",
        home / ".local/share/pipx/venvs/uv/bin/uv",
        Path("/usr/bin/uv"),
    )
    return command in {str(path) for path in allowed}


def _ops_descriptor_matches(
    entry: dict[str, Any], expected_args: list[str], phase: ReferenceAgentPhase
) -> bool:
    """Reject extra launcher switches, stale sockets and wrong phase settings."""
    env = entry.get("env")
    if not isinstance(env, dict):
        return False
    return (
        entry.get("enabled") is True
        and entry.get("type") == "stdio"
        and _is_reviewed_uv_command(entry.get("command"))
        and entry.get("args") == expected_args
        and not any(
            key in env
            for key in (
                "KICAD_API_SOCKET",
                "KICAD_MCP_KICAD_SOCKET_PATH",
                "KICAD_API_TOKEN",
                "KICAD_MCP_KICAD_TOKEN",
            )
        )
        and env.get("KICAD_MCP_PROFILE") == phase.profile
        and env.get("KICAD_MCP_OPERATING_MODE") == phase.mode
    )


def _reviewed_ops_server_available(
    *, root: Path, phase_name: str, server_name: str | None, config_path: Path
) -> bool:
    """Check fixed-scope launcher metadata; actual tool attestation is separate."""
    if not server_name or not server_name.startswith("kicad-"):
        return False
    if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in server_name):
        return False
    phase = ReferenceAgentPhase.for_name(phase_name)
    if phase.name == "manufacturing":
        return False
    version = _pinned_uv_version(root)
    if version is None:
        return False
    entry = _read_ops_server_descriptor(config_path, server_name)
    if entry is None:
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
    return _ops_descriptor_matches(entry, expected_args, phase)


def _reviewed_inputs(board_id: str, board_dir: Path) -> tuple[dict[str, str], set[str]]:
    hashes: dict[str, str] = {}
    blocking: set[str] = set()
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
    return hashes, blocking


def _runtime_blockers(
    *,
    root: Path,
    phase_name: str,
    agent_runtime: AgentRuntime,
    ops_server_name: str | None,
    ops_config_path: Path,
) -> set[str]:
    blocking: set[str] = set()
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
    return blocking


def _live_gui_gate(
    *, required: bool, phase_name: str, socket: str | None, expected_board: str | None
) -> tuple[bool, set[str]]:
    """Report optional PCB GUI readiness without changing offline preflight."""
    if not required:
        return False, set()
    if phase_name != "pcb":
        return False, {"live_gui_gate_requires_pcb_phase"}
    measured = probe_live_gui(ipc_socket=socket, expected_board_name=expected_board)
    if measured["gui_ready"] is True:
        return True, set()
    return False, set(measured["blocking_reasons"])


def preflight(
    *,
    root: Path,
    board_id: str,
    attempt_number: int,
    phase_name: str,
    agent_runtime: AgentRuntime = "claude",
    ops_server_name: str | None = None,
    ops_config_path: Path = _OPS_CONFIG,
    approved_source_revision: str | None = None,
    require_live_gui: bool = False,
    live_gui_socket: str | None = None,
    expected_live_board_name: str | None = None,
) -> dict[str, Any]:
    """Return machine-readable, sanitized readiness; never write an artifact."""
    workspace = ReferenceAgentWorkspace.for_reviewed_attempt(
        checkout_dir=root, board_id=board_id, attempt_number=attempt_number
    )
    phase = ReferenceAgentPhase.for_name(phase_name)
    hashes, blocking = _reviewed_inputs(board_id, workspace.prompt_path.parent)
    attempt_dir = workspace.agent_log_path.parent
    if attempt_dir.is_symlink() or attempt_dir.exists() or workspace.scratch_dir.exists():
        blocking.add("attempt_identity_already_used")
    source_revision: str | None = None
    try:
        source_revision = discover_reference_source_revision(root)
    except (OSError, ReferenceAgentRunnerError):
        blocking.add("source_revision_not_reproducible")
    # An attester executing from the same checkout cannot establish which
    # revision the owner independently reviewed. Require an explicit SHA pin
    # for ChatGPT–Ops handoff, and fail closed on an absent/stale/malformed pin.
    # This is intentionally NOT hardcoded to a commit (main/merge evolves).
    if (
        agent_runtime == "chatgpt-ops"
        and source_revision is not None
        and (
            approved_source_revision is None
            or re.fullmatch(r"[0-9a-f]{40}", approved_source_revision) is None
            or source_revision != approved_source_revision
        )
    ):
        blocking.add("source_revision_not_reviewed")
    blocking.update(
        _runtime_blockers(
            root=root,
            phase_name=phase_name,
            agent_runtime=agent_runtime,
            ops_server_name=ops_server_name,
            ops_config_path=ops_config_path,
        )
    )
    # Optional stage-two gate, only for an already-launched isolated PCB GUI.
    # It must not run in the default offline preflight: schematic clean starts
    # and ChatGPT–Ops inventory attestation intentionally have no GUI yet.
    live_gui_attested, gui_blockers = _live_gui_gate(
        required=require_live_gui,
        phase_name=phase.name,
        socket=live_gui_socket,
        expected_board=expected_live_board_name,
    )
    blocking.update(gui_blockers)
    if blocking:
        status = "blocked"
    elif agent_runtime == "claude":
        status = "ready"
    else:
        status = "handoff_required"
    return {
        "schema_version": SCHEMA,
        "status": status,
        "board_id": board_id,
        "benchmark_version": "v1",
        "attempt_id": workspace.attempt_id,
        "phase": phase.name,
        "profile": phase.profile,
        "operating_mode": phase.mode,
        "agent": agent_runtime,
        "mcp_server": ops_server_name if agent_runtime == "chatgpt-ops" else None,
        "live_tool_attestation_required": agent_runtime == "chatgpt-ops",
        "live_gui_attestation_requested": require_live_gui,
        "live_gui_attested": live_gui_attested,
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
    parser.add_argument(
        "--require-live-gui",
        action="store_true",
        help="Stage-two read-only KiCad 10 IPC/board-readiness gate (PCB phase only)",
    )
    parser.add_argument("--ipc-socket", help="Exact isolated KiCad IPC Unix socket URI")
    parser.add_argument(
        "--expected-live-board-name", help="Exact live .kicad_pcb basename to match"
    )
    parser.add_argument(
        "--approved-source-revision",
        help=(
            "Exact 40-hex source SHA independently approved by the owner (required for ChatGPT–Ops)"
        ),
    )
    args = parser.parse_args(argv)
    try:
        result = preflight(
            root=ROOT,
            board_id=args.board_id,
            attempt_number=args.attempt_number,
            phase_name=args.phase,
            agent_runtime=args.agent_runtime,
            ops_server_name=args.ops_server_name,
            approved_source_revision=args.approved_source_revision,
            require_live_gui=args.require_live_gui,
            live_gui_socket=args.ipc_socket,
            expected_live_board_name=args.expected_live_board_name,
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
