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
from typing import Any

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
_INPUTS = ("original-prompt.md", "specification.md", "benchmark.json", "quality-gates.json")


def _input_sha256(path: Path) -> str:
    """Hash only known regular, local review documents."""
    if path.is_symlink() or not path.is_file():
        raise ValueError("input_not_a_reviewed_regular_file")
    if path.stat().st_size > 256_000:
        raise ValueError("input_not_a_reviewed_regular_file")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _assert_metadata(board_id: str, board_dir: Path) -> None:
    for name in ("benchmark.json", "quality-gates.json"):
        data = json.loads((board_dir / name).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("invalid_benchmark_metadata")
        if name == "benchmark.json":
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


def preflight(*, root: Path, board_id: str, attempt_number: int, phase_name: str) -> dict[str, Any]:
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
        except (OSError, ValueError, json.JSONDecodeError):
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
    if shutil.which("claude") is None:
        blocking.add("reviewed_agent_cli_unavailable")

    return {
        "schema_version": SCHEMA,
        "status": "ready" if not blocking else "blocked",
        "board_id": board_id,
        "benchmark_version": "v1",
        "attempt_id": workspace.attempt_id,
        "phase": phase.name,
        "profile": phase.profile,
        "operating_mode": phase.mode,
        "agent": "claude",
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
    args = parser.parse_args(argv)
    try:
        result = preflight(
            root=ROOT,
            board_id=args.board_id,
            attempt_number=args.attempt_number,
            phase_name=args.phase,
        )
    except (ValueError, OSError, ReferenceAgentRunnerError):
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
    return 0 if result["status"] == "ready" else 2


if __name__ == "__main__":
    sys.exit(main())
