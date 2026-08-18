#!/usr/bin/env python3
"""Adapt NVIDIA NIM chat completions to the sanitized live-eval contract."""

from __future__ import annotations

from kicad_mcp.evals.chat_eval_cli import run_chat_eval_cli
from kicad_mcp.evals.nvidia_nim_adapter import request_nvidia_nim


def main(argv: list[str] | None = None) -> int:
    return run_chat_eval_cli(
        argv,
        description=__doc__ or "NVIDIA NIM live-eval adapter",
        api_key_env="NVIDIA_API_KEY",
        request_chat=request_nvidia_nim,
        default_structured_output="none",
    )


if __name__ == "__main__":
    raise SystemExit(main())
