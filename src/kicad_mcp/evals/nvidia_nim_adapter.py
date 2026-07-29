"""Strict NVIDIA NIM adapter for provider-neutral live-model evaluations."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import httpx

from .tool_selection import all_referenced_tools, load_cases

NVIDIA_NIM_CHAT_COMPLETIONS_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_RESPONSE_KINDS = frozenset({"tool_calls", "answer", "confirmation", "refusal"})
_TOOL_ROW = re.compile(r"^\| `([^`]+)` \|.*\| ([^|]+) \|$")


@dataclass(frozen=True, slots=True)
class ToolCatalogEntry:
    """One bounded tool name and public summary supplied to the classifier."""

    name: str
    summary: str

    def as_dict(self) -> dict[str, str]:
        return {"name": self.name, "summary": self.summary}


def load_eval_tool_catalog(
    cases_path: str | Path,
    tools_reference_path: str | Path,
) -> tuple[ToolCatalogEntry, ...]:
    """Build a deterministic catalog from all tools referenced by the corpus."""
    referenced = all_referenced_tools(load_cases(cases_path))
    summaries: dict[str, str] = {}
    for line in Path(tools_reference_path).read_text(encoding="utf-8").splitlines():
        match = _TOOL_ROW.match(line)
        if match is not None:
            summaries[match.group(1)] = match.group(2).strip()
    missing = sorted(referenced - set(summaries))
    if missing:
        raise ValueError(f"Generated tool reference is missing corpus tools: {missing}.")
    return tuple(
        ToolCatalogEntry(name=name, summary=summaries[name][:240]) for name in sorted(referenced)
    )


def _catalog_values(
    catalog: Sequence[ToolCatalogEntry | Mapping[str, str]],
) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    for item in catalog:
        if isinstance(item, ToolCatalogEntry):
            values.append(item.as_dict())
            continue
        name = str(item.get("name", "")).strip()
        summary = str(item.get("summary", "")).strip()
        if not name:
            raise ValueError("Tool catalog entries need a non-empty name.")
        values.append({"name": name, "summary": summary})
    return values


def _classifier_schema(catalog_names: Sequence[str]) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["response_kind", "called_tools"],
        "properties": {
            "response_kind": {"type": "string", "enum": sorted(_RESPONSE_KINDS)},
            "called_tools": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(catalog_names)},
                "uniqueItems": True,
            },
        },
    }


def build_chat_payload(
    *,
    model: str,
    prompt: str,
    catalog: Sequence[ToolCatalogEntry | Mapping[str, str]],
) -> dict[str, Any]:
    """Build a deterministic classification request without case expectations."""
    catalog_values = _catalog_values(catalog)
    system = (
        "You are a tool-selection classifier for KiCad MCP Pro. Do not execute tools. "
        "Choose only exact names from the supplied catalog. Return exactly one JSON object "
        "with keys response_kind and called_tools. response_kind must be one of "
        "tool_calls, answer, confirmation, refusal. For tool_calls, called_tools must be a "
        "non-empty array. For all other response kinds it must be empty. Do not include "
        "explanations or additional keys.\nTOOL_CATALOG="
        + json.dumps(catalog_values, separators=(",", ":"), ensure_ascii=False)
    )
    schema = _classifier_schema([item["name"] for item in catalog_values])
    return {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "top_p": 1,
        "max_tokens": 256,
        "stream": False,
        "guided_json": schema,
    }


def _failure(kind: str) -> dict[str, object]:
    return {"schema_version": 1, "status": "error", "failure_kind": kind}


def _failure_for_status(status_code: int) -> str:
    if status_code in {401, 403}:
        return "provider_auth"
    if status_code == 429:
        return "provider_rate_limit"
    if status_code >= 500:
        return "provider_unavailable"
    return "model_error"


def _json_object(content: str) -> dict[str, Any]:
    value = json.loads(content)
    if not isinstance(value, dict):
        raise ValueError("Model response JSON must be an object.")
    return cast(dict[str, Any], value)


def _optional_usage(usage: object, key: str) -> int | None:
    if not isinstance(usage, dict):
        return None
    value = usage.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("Provider token usage must be a non-negative integer.")
    return value


def _parse_completion(
    payload: object,
    *,
    catalog_names: frozenset[str],
    latency_ms: float,
) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("Provider response must be an object.")
    choices = payload.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("Provider response must contain exactly one choice.")
    choice = choices[0]
    if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
        raise ValueError("Provider response choice is malformed.")
    content = choice["message"].get("content")
    if not isinstance(content, str):
        raise ValueError("Provider response content must be text.")
    selected = _json_object(content)
    if set(selected) != {"response_kind", "called_tools"}:
        raise ValueError("Model response contains unsupported fields.")
    response_kind = selected.get("response_kind")
    called_tools = selected.get("called_tools")
    if response_kind not in _RESPONSE_KINDS or not isinstance(called_tools, list):
        raise ValueError("Model response has an invalid classifier shape.")
    normalized: list[str] = []
    for item in called_tools:
        if not isinstance(item, str) or item not in catalog_names:
            raise ValueError("Model selected an unknown tool.")
        normalized.append(item)
    if len(normalized) != len(set(normalized)):
        raise ValueError("Model selected duplicate tools.")
    if (response_kind == "tool_calls") != bool(normalized):
        raise ValueError("Model response kind and tool list disagree.")
    usage = payload.get("usage")
    return {
        "schema_version": 1,
        "status": "ok",
        "response_kind": response_kind,
        "called_tools": normalized,
        "latency_ms": round(latency_ms, 3),
        "input_tokens": _optional_usage(usage, "prompt_tokens"),
        "output_tokens": _optional_usage(usage, "completion_tokens"),
        "estimated_cost_micros": None,
    }


def request_nvidia_nim(
    *,
    model: str,
    prompt: str,
    api_key: str,
    catalog: Sequence[ToolCatalogEntry | Mapping[str, str]],
    timeout_seconds: float = 50,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, object]:
    """Invoke NVIDIA NIM and return only the normalized adapter contract."""
    catalog_values = _catalog_values(catalog)
    catalog_names = frozenset(item["name"] for item in catalog_values)
    started = time.perf_counter()
    payload = build_chat_payload(model=model, prompt=prompt, catalog=catalog_values)
    try:
        with httpx.Client(timeout=timeout_seconds, transport=transport) as client:
            response = client.post(
                NVIDIA_NIM_CHAT_COMPLETIONS_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            if response.status_code in {400, 422}:
                fallback = dict(payload)
                schema = fallback.pop("guided_json")
                fallback["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "kicad_mcp_tool_selection",
                        "schema": schema,
                    },
                }
                response = client.post(
                    NVIDIA_NIM_CHAT_COMPLETIONS_URL,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=fallback,
                )
    except httpx.TimeoutException:
        return _failure("timeout")
    except httpx.HTTPError:
        return _failure("provider_unavailable")
    if response.status_code >= 400:
        return _failure(_failure_for_status(response.status_code))
    try:
        return _parse_completion(
            response.json(),
            catalog_names=catalog_names,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return _failure("model_error")


__all__ = [
    "NVIDIA_NIM_CHAT_COMPLETIONS_URL",
    "ToolCatalogEntry",
    "build_chat_payload",
    "load_eval_tool_catalog",
    "request_nvidia_nim",
]
