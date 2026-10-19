"""Read-only reconciliation of client-supplied and server-observed MCP metadata."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from kicad_mcp.evals.reference_ops_reconciliation import (
    ReferenceOpsReconciliationError,
    reconcile_ops_events,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-trace", type=Path, required=True)
    parser.add_argument("--client-events", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--phase", choices=("schematic", "pcb"), required=True)
    args = parser.parse_args()
    try:
        result = reconcile_ops_events(
            args.server_trace,
            args.client_events,
            attempt_id=args.attempt_id,
            phase_name=args.phase,
        )
    except ReferenceOpsReconciliationError:
        print(json.dumps({"status": "blocked", "counts_as_task_success": False}))
        return 2
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
