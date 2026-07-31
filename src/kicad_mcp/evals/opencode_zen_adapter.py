"""Experimental OpenCode Zen adapter for sanitized live-model evaluations."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import httpx

from .nvidia_nim_adapter import (
    StructuredOutputMode,
    ToolCatalogEntry,
    request_openai_compatible_chat,
)

OPENCODE_ZEN_CHAT_COMPLETIONS_URL = "https://opencode.ai/zen/v1/chat/completions"
OPENCODE_ZEN_FREE_MODELS = frozenset(
    {
        "deepseek-v4-flash-free",
        "mimo-v2.5-free",
        "laguna-s-2.1-free",
        "ling-3.0-flash-free",
        "north-mini-code-free",
        "nemotron-3-ultra-free",
    }
)


def request_opencode_zen(
    *,
    model: str,
    prompt: str,
    api_key: str,
    catalog: Sequence[ToolCatalogEntry | Mapping[str, object]],
    timeout_seconds: float = 50,
    transport: httpx.BaseTransport | None = None,
    structured_output: StructuredOutputMode = "none",
) -> dict[str, object]:
    """Invoke one reviewed free Zen model without retaining provider payloads."""
    if model not in OPENCODE_ZEN_FREE_MODELS:
        raise ValueError("Model is not a reviewed OpenCode Zen free model.")
    return request_openai_compatible_chat(
        endpoint=OPENCODE_ZEN_CHAT_COMPLETIONS_URL,
        model=model,
        prompt=prompt,
        api_key=api_key,
        catalog=catalog,
        timeout_seconds=timeout_seconds,
        transport=transport,
        structured_output=structured_output,
    )


__all__ = [
    "OPENCODE_ZEN_CHAT_COMPLETIONS_URL",
    "OPENCODE_ZEN_FREE_MODELS",
    "request_opencode_zen",
]
