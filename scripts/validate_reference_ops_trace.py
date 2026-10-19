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
    parser.add_argument("--phase", choices=("schematic", "pcb"), required=True)
    args = parser.parse_args()
    try:
        summary = validate_reference_ops_trace(
            args.trace, attempt_id=args.attempt_id, phase_name=args.phase
        )
    except ValueError:
        print(json.dumps({"status": "blocked", "counts_as_task_success": False}))
        return 2
    print(json.dumps({"status": "server_trace_valid", **asdict(summary)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
