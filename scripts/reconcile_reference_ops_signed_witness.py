"""Verify pinned Ed25519 Gateway export against an independent native MCP trace.

This is client/run-scoped infrastructure acceptance, NOT benchmark task success.
Supply public SPKI and its fingerprint from a trusted channel distinct from the
Gateway export. --consume-nonce atomically records a private one-time use.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from kicad_mcp.evals.reference_ops_signed_witness import (
    SignedOpsWitnessError,
    reconcile_signed_ops_witness,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-trace", type=Path, required=True)
    parser.add_argument("--signed-gateway-witness", type=Path, required=True)
    parser.add_argument("--attempt-id", required=True)
    parser.add_argument("--phase", choices=("schematic", "pcb"), required=True)
    parser.add_argument("--server-name", required=True)
    parser.add_argument("--nonce", required=True)
    parser.add_argument("--trusted-public-key-spki", required=True)
    parser.add_argument("--trusted-key-id", required=True)
    parser.add_argument("--consume-nonce", action="store_true")
    args = parser.parse_args()
    try:
        summary = reconcile_signed_ops_witness(
            args.server_trace,
            args.signed_gateway_witness,
            attempt_id=args.attempt_id,
            phase_name=args.phase,
            server_name=args.server_name,
            nonce=args.nonce,
            trusted_public_key_spki=args.trusted_public_key_spki,
            trusted_key_id=args.trusted_key_id,
            consume_nonce=args.consume_nonce,
        )
    except SignedOpsWitnessError:
        print(json.dumps({"status": "blocked", "counts_as_task_success": False}))
        return 2
    print(json.dumps(asdict(summary), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
