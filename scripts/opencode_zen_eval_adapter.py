#!/usr/bin/env python3
"""Adapt reviewed OpenCode Zen chat models to the sanitized live-eval contract."""

from __future__ import annotations

from kicad_mcp.evals.chat_eval_cli import run_chat_eval_cli
from kicad_mcp.evals.opencode_zen_adapter import request_opencode_zen


def main(argv: list[str] | None = None) -> int:
    return run_chat_eval_cli(
        argv,
        description=__doc__ or "OpenCode Zen live-eval adapter",
        api_key_env="OPENCODE_ZEN_API_KEY",
        request_chat=request_opencode_zen,
        default_structured_output="none",
    )


if __name__ == "__main__":
    raise SystemExit(main())
