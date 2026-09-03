"""Shared CLI harness for sanitized subprocess-backed chat-model evaluations."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol

from .nvidia_nim_adapter import StructuredOutputMode, ToolCatalogEntry, load_eval_tool_catalog

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CASES = ROOT / "evals/tool_selection/cases.yaml"
DEFAULT_TOOLS = ROOT / "docs/tools-reference.generated.md"


class ChatRequest(Protocol):
    """Provider request callable accepted by the shared CLI harness."""

    def __call__(
        self,
        *,
        model: str,
        prompt: str,
        api_key: str,
        catalog: Sequence[ToolCatalogEntry | Mapping[str, object]],
        timeout_seconds: float,
        structured_output: StructuredOutputMode,
    ) -> dict[str, object]: ...


def _parser(
    description: str, default_structured_output: StructuredOutputMode
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--tools-reference", type=Path, default=DEFAULT_TOOLS)
    parser.add_argument("--timeout-seconds", type=float, default=50)
    parser.add_argument(
        "--structured-output",
        choices=("none", "guided_json", "json_schema", "json_object"),
        default=default_structured_output,
    )
    return parser


def _error(kind: str) -> dict[str, object]:
    return {"schema_version": 1, "status": "error", "failure_kind": kind}


def run_chat_eval_cli(
    argv: list[str] | None,
    *,
    description: str,
    api_key_env: str,
    request_chat: ChatRequest,
    default_structured_output: StructuredOutputMode,
) -> int:
    """Run one provider-specific chat adapter through the shared CLI contract."""
    args = _parser(description, default_structured_output).parse_args(argv)
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        result = _error("adapter_unavailable")
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
            result = request_chat(
                model=args.model,
                prompt=request["prompt"],
                api_key=api_key,
                catalog=catalog,
                timeout_seconds=args.timeout_seconds,
                structured_output=args.structured_output,
            )
        except (OSError, TypeError, ValueError):
            result = _error("protocol_error")
    print(json.dumps(result, separators=(",", ":"), sort_keys=True))
    return 0 if result.get("status") == "ok" else 1


__all__ = ["run_chat_eval_cli"]
