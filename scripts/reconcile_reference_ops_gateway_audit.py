"""Read-only comparison of independently exported Ops Gateway and MCP traces.

The exporter is not authenticated here; matching metadata remains untrusted
for benchmark success accounting even when the validation passes.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from kicad_mcp.evals.reference_ops_gateway_audit import (
    ReferenceOpsGatewayAuditError,
    reconcile_gateway_audit,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-trace", type=Path, required=True)
    parser.add_argument("--gateway-audit", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--phase", choices=("schematic", "pcb"), required=True)
    parser.add_argument("--server-name", required=True)
    args = parser.parse_args()
    try:
        result = reconcile_gateway_audit(
            args.server_trace,
            args.gateway_audit,
            attempt_id=args.attempt_id,
            phase_name=args.phase,
            server_name=args.server_name,
        )
    except ReferenceOpsGatewayAuditError:
        print(json.dumps({"status": "blocked", "counts_as_task_success": False}))
        return 2
    print(json.dumps(asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
