"""OpenAI adapter boundary for nonblocking live-model evaluation candidates."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import httpx

from .nvidia_nim_adapter import (
    StructuredOutputMode,
    ToolCatalogEntry,
    request_openai_compatible_chat,
)

OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_EVAL_MODELS = frozenset({"gpt-5.4-mini-2026-03-17"})


def request_openai(
    *,
    model: str,
    prompt: str,
    api_key: str,
    catalog: Sequence[ToolCatalogEntry | Mapping[str, object]],
    timeout_seconds: float = 50,
    transport: httpx.BaseTransport | None = None,
    structured_output: StructuredOutputMode = "json_schema",
) -> dict[str, object]:
    """Invoke one reviewed OpenAI snapshot through the sanitized shared path."""
    if model not in OPENAI_EVAL_MODELS:
        raise ValueError("Model is not a reviewed OpenAI eval model.")
    return request_openai_compatible_chat(
        endpoint=OPENAI_CHAT_COMPLETIONS_URL,
        model=model,
        prompt=prompt,
        api_key=api_key,
        catalog=catalog,
        timeout_seconds=timeout_seconds,
        transport=transport,
        structured_output=structured_output,
        request_profile="openai-gpt5",
    )


__all__ = ["OPENAI_CHAT_COMPLETIONS_URL", "OPENAI_EVAL_MODELS", "request_openai"]
