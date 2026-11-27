"""Read-only validation of the recorded ChatGPT–Ops server-side MCP trace."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from kicad_mcp.evals.reference_ops_trace_validation import (
    validate_reference_ops_trace,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument(
        "--board-id",
        choices=("stm32f072-usbc", "esp32-c6-usbc", "rp2350-usbc"),
        help="Validate a reserved v1 board attempt instead of a flat diagnostic trace",
    )
    parser.add_argument("--phase", choices=("schematic", "pcb"), required=True)
    args = parser.parse_args()
    try:
        summary = validate_reference_ops_trace(
            args.trace, attempt_id=args.attempt_id, phase_name=args.phase, board_id=args.board_id
        )
    except ValueError:
        print(json.dumps({"status": "blocked", "counts_as_task_success": False}))
        return 2
    report = asdict(summary)
    if summary.board_id is None:
        del report["board_id"]
    print(json.dumps({"status": "server_trace_valid", **report}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
