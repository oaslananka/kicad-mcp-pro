#!/usr/bin/env python3
"""Adapt reviewed OpenCode Zen free models to the sanitized live-eval contract."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from kicad_mcp.evals.nvidia_nim_adapter import load_eval_tool_catalog
from kicad_mcp.evals.opencode_zen_adapter import request_opencode_zen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "evals/tool_selection/cases.yaml"
DEFAULT_TOOLS = ROOT / "docs/tools-reference.generated.md"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--tools-reference", type=Path, default=DEFAULT_TOOLS)
    parser.add_argument("--timeout-seconds", type=float, default=50)
    parser.add_argument(
        "--structured-output",
        choices=("none", "guided_json", "json_schema"),
        default="none",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    api_key = os.environ.get("OPENCODE_ZEN_API_KEY", "")
    if not api_key:
        result: dict[str, object] = {
            "schema_version": 1,
            "status": "error",
            "failure_kind": "adapter_unavailable",
        }
    else:
        try:
            request = json.load(sys.stdin)
            if (
                not isinstance(request, dict)
                or request.get("schema_version") != 1
                or not isinstance(request.get("case_id"), str)
                or not isinstance(request.get("prompt"), str)
                or set(request) != {"schema_version", "case_id", "prompt"}
            ):
                raise ValueError
            catalog = load_eval_tool_catalog(args.cases, args.tools_reference)
            result = request_opencode_zen(
                model=args.model,
                prompt=request["prompt"],
                api_key=api_key,
                catalog=catalog,
                timeout_seconds=args.timeout_seconds,
                structured_output=args.structured_output,
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            result = {
                "schema_version": 1,
                "status": "error",
                "failure_kind": "protocol_error",
            }
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
