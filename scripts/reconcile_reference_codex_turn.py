"""Validate one privately captured Codex turn against its native MCP trace.

This command never executes an agent, publishes an attempt, or awards a score.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import fields
from pathlib import Path

from kicad_mcp.evals.reference_codex_turn_evidence import (
    ReferenceCodexEvidenceError,
    reconcile_codex_turn,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--board-id", choices=("stm32f072-usbc", "esp32-c6-usbc", "rp2350-usbc"), required=True
    )
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--thread-id", required=True)
    parser.add_argument("--turn-id", required=True)
    parser.add_argument("--server-trace", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = reconcile_codex_turn(
            args.server_trace,
            board_id=args.board_id,
            attempt_id=args.attempt_id,
            thread_id=args.thread_id,
            turn_id=args.turn_id,
        )
    except ReferenceCodexEvidenceError:
        print(json.dumps({"status": "blocked", "counts_as_task_success": False}))
        return 2
    report = {
        member.name: getattr(result, member.name)
        for member in fields(result)
        if member.name != "events"
    }
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
