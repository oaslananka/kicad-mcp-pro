"""Sandboxed OpenCode CLI adapter for sanitized live-model evaluations."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .nvidia_nim_adapter import (
    ToolCatalogEntry,
    build_chat_payload,
    normalize_classifier_text,
)
from .opencode_zen_adapter import OPENCODE_ZEN_FREE_MODELS

OPENCODE_CLI_VERSION = "1.18.10"
OPENCODE_CLI_AGENT_ID = "kicad-eval"
OPENCODE_CLI_PROVIDER_ID = "kicad-eval-zen"
OPENCODE_ZEN_BASE_URL = "https://opencode.ai/zen/v1"

_SAFE_PARENT_ENV = frozenset(
    {
        "LANG",
        "LC_ALL",
        "NO_PROXY",
        "PATH",
        "REQUESTS_CA_BUNDLE",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
    }
)
_KNOWN_EVENT_TYPES = frozenset({"step_start", "text", "step_finish"})


@dataclass(frozen=True, slots=True)
class OpenCodeEventResult:
    """Only the normalized fields retained from one OpenCode JSON event stream."""

    text: str
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_micros: int | None


RunProcess = Callable[..., subprocess.CompletedProcess[str]]


def build_opencode_config(*, model: str, system_prompt: str) -> dict[str, object]:
    """Build an isolated provider and primary classifier agent with every permission denied."""
    if model not in OPENCODE_ZEN_FREE_MODELS:
        raise ValueError("Model is not a reviewed OpenCode Zen free model.")
    return {
        "$schema": "https://opencode.ai/config.json",
        "enabled_providers": [OPENCODE_CLI_PROVIDER_ID],
        "model": f"{OPENCODE_CLI_PROVIDER_ID}/{model}",
        "small_model": f"{OPENCODE_CLI_PROVIDER_ID}/{model}",
        "permission": "deny",
        "agent": {
            OPENCODE_CLI_AGENT_ID: {
                "description": "Strict KiCad MCP tool-selection classifier.",
                "mode": "primary",
                "model": f"{OPENCODE_CLI_PROVIDER_ID}/{model}",
                "prompt": system_prompt,
                "temperature": 0,
                "permission": "deny",
            }
        },
        "provider": {
            OPENCODE_CLI_PROVIDER_ID: {
                "npm": "@ai-sdk/openai-compatible",
                "name": "KiCad MCP OpenCode Zen Evaluation",
                "options": {
                    "baseURL": OPENCODE_ZEN_BASE_URL,
                    "apiKey": "{env:OPENCODE_ZEN_API_KEY}",
                },
                "models": {
                    model: {
                        "name": model,
                        "limit": {"context": 131072, "output": 4096},
                    }
                },
            }
        },
    }


def build_classifier_messages(
    *,
    model: str,
    prompt: str,
    catalog: Sequence[ToolCatalogEntry | Mapping[str, object]],
) -> tuple[str, str]:
    """Return the reviewed classifier system policy and user request as separate messages."""
    payload = build_chat_payload(model=model, prompt=prompt, catalog=catalog)
    messages = payload.get("messages")
    if not isinstance(messages, list) or len(messages) != 2:
        raise ValueError("Classifier payload must contain one system and one user message.")
    system = messages[0]
    user = messages[1]
    if not isinstance(system, dict) or not isinstance(system.get("content"), str):
        raise ValueError("Classifier system message is malformed.")
    if not isinstance(user, dict) or not isinstance(user.get("content"), str):
        raise ValueError("Classifier user message is malformed.")
    return system["content"], user["content"]


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("OpenCode token counts must be non-negative integers.")
    return value


def _cost_micros(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ValueError("OpenCode cost must be a non-negative number.")
    return round(float(value) * 1_000_000)


def parse_opencode_events(stdout: str) -> OpenCodeEventResult:
    """Parse only documented headless events and discard all other provider/session data."""
    text_parts: list[str] = []
    finish: dict[str, Any] | None = None
    for line in stdout.splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError("OpenCode event must be a JSON object.")
        event_type = value.get("type")
        if event_type not in _KNOWN_EVENT_TYPES:
            raise ValueError("OpenCode emitted an unsupported event type.")
        part = value.get("part")
        if not isinstance(part, dict):
            raise ValueError("OpenCode event part is malformed.")
        if event_type == "step_start":
            if part.get("type") != "step-start":
                raise ValueError("OpenCode step-start event is malformed.")
            continue
        if event_type == "text":
            if part.get("type") != "text" or not isinstance(part.get("text"), str):
                raise ValueError("OpenCode text event is malformed.")
            text_parts.append(part["text"])
            continue
        if finish is not None or part.get("type") != "step-finish":
            raise ValueError("OpenCode step-finish event is malformed or duplicated.")
        finish = part
    if finish is None or not text_parts:
        raise ValueError("OpenCode event stream is incomplete.")
    tokens = finish.get("tokens")
    if not isinstance(tokens, dict):
        raise ValueError("OpenCode step-finish tokens are malformed.")
    return OpenCodeEventResult(
        text="".join(text_parts),
        input_tokens=_optional_nonnegative_int(tokens.get("input")),
        output_tokens=_optional_nonnegative_int(tokens.get("output")),
        estimated_cost_micros=_cost_micros(finish.get("cost")),
    )


def _isolated_env(*, api_key: str, root: Path, config: Mapping[str, object]) -> dict[str, str]:
    env = {name: os.environ[name] for name in _SAFE_PARENT_ENV if name in os.environ}
    env.update(
        {
            "HOME": str(root / "home"),
            "XDG_DATA_HOME": str(root / "data"),
            "XDG_CONFIG_HOME": str(root / "config"),
            "XDG_CACHE_HOME": str(root / "cache"),
            "TERM": "dumb",
            "NO_COLOR": "1",
            "OPENCODE_AUTO_SHARE": "false",
            "OPENCODE_DISABLE_AUTOUPDATE": "true",
            "OPENCODE_DISABLE_PRUNE": "true",
            "OPENCODE_DISABLE_TERMINAL_TITLE": "true",
            "OPENCODE_CONFIG_CONTENT": json.dumps(config, separators=(",", ":")),
            "OPENCODE_ZEN_API_KEY": api_key,
        }
    )
    return env


def request_opencode_cli(
    *,
    model: str,
    prompt: str,
    api_key: str,
    catalog: Sequence[ToolCatalogEntry | Mapping[str, object]],
    opencode_bin: str = "opencode",
    timeout_seconds: float = 55,
    run_process: RunProcess = subprocess.run,
) -> dict[str, object]:
    """Invoke pinned OpenCode headlessly with no tools, plugins, sharing, or persistent state."""
    if model not in OPENCODE_ZEN_FREE_MODELS:
        raise ValueError("Model is not a reviewed OpenCode Zen free model.")
    if not api_key:
        return {"schema_version": 1, "status": "error", "failure_kind": "adapter_unavailable"}
    system_prompt, user_message = build_classifier_messages(
        model=model,
        prompt=prompt,
        catalog=catalog,
    )
    config = build_opencode_config(model=model, system_prompt=system_prompt)
    started = time.perf_counter()
    try:
        with tempfile.TemporaryDirectory(prefix="kicad-mcp-opencode-") as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            workspace.mkdir(parents=True)
            completed = run_process(
                [
                    opencode_bin,
                    "run",
                    "--pure",
                    "--format",
                    "json",
                    "--title",
                    "kicad-mcp-live-eval",
                    "--model",
                    f"{OPENCODE_CLI_PROVIDER_ID}/{model}",
                    "--agent",
                    OPENCODE_CLI_AGENT_ID,
                    "--dir",
                    str(workspace),
                ],
                input=user_message,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                env=_isolated_env(api_key=api_key, root=root, config=config),
            )
    except subprocess.TimeoutExpired:
        return {"schema_version": 1, "status": "error", "failure_kind": "timeout"}
    except OSError:
        return {"schema_version": 1, "status": "error", "failure_kind": "adapter_unavailable"}
    if completed.returncode != 0:
        return {"schema_version": 1, "status": "error", "failure_kind": "provider_unavailable"}
    try:
        event = parse_opencode_events(completed.stdout)
        return normalize_classifier_text(
            content=event.text,
            prompt=prompt,
            catalog=catalog,
            latency_ms=(time.perf_counter() - started) * 1000,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            estimated_cost_micros=event.estimated_cost_micros,
        )
    except (TypeError, ValueError):
        return {"schema_version": 1, "status": "error", "failure_kind": "model_output_invalid"}


__all__ = [
    "OPENCODE_CLI_AGENT_ID",
    "OPENCODE_CLI_PROVIDER_ID",
    "OPENCODE_CLI_VERSION",
    "OpenCodeEventResult",
    "build_classifier_messages",
    "build_opencode_config",
    "parse_opencode_events",
    "request_opencode_cli",
]
