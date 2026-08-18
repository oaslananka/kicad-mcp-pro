#!/usr/bin/env python3
"""Adapt reviewed OpenAI models to the sanitized live-eval contract."""

from __future__ import annotations

from kicad_mcp.evals.chat_eval_cli import run_chat_eval_cli
from kicad_mcp.evals.openai_adapter import request_openai


def main(argv: list[str] | None = None) -> int:
    return run_chat_eval_cli(
        argv,
        description=__doc__ or "OpenAI live-eval adapter",
        api_key_env="OPENAI_KEY",
        request_chat=request_openai,
        default_structured_output="json_schema",
    )


if __name__ == "__main__":
    raise SystemExit(main())
