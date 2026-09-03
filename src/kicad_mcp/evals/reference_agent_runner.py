"""Sanitized execution evidence helpers for real reference-board agent runs."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ..operating_modes import is_tool_allowed_in_mode
from ..tools.router import tools_for_profile
from .reference_corpus import ReferenceAgentLogEvent

_MCP_PREFIX = "mcp__kicad__"
_INTERNAL_TOOLS = frozenset({"ToolSearch"})


class ReferenceAgentRunnerError(ValueError):
    """Raised when a benchmark agent stream violates the reviewed execution contract."""


@dataclass(frozen=True, slots=True)
class ReferenceAgentPhase:
    """Reviewed KiCad MCP profile/mode pair for one benchmark phase."""

    name: Literal["schematic", "pcb", "manufacturing"]
    profile: Literal["build", "release"]
    mode: Literal["write", "manufacturing"]

    @classmethod
    def for_name(cls, name: str) -> ReferenceAgentPhase:
        phases = {
            "schematic": cls("schematic", "build", "write"),
            "pcb": cls("pcb", "build", "write"),
            "manufacturing": cls("manufacturing", "release", "manufacturing"),
        }
        try:
            return phases[name]
        except KeyError as exc:
            raise ReferenceAgentRunnerError(f"unsupported reference-agent phase: {name}") from exc


def reviewed_mcp_tools(phase: ReferenceAgentPhase) -> frozenset[str]:
    """Return the exact reviewed MCP tool ceiling for one benchmark phase."""
    return frozenset(
        _MCP_PREFIX + tool
        for tool in tools_for_profile(phase.profile)
        if is_tool_allowed_in_mode(tool, phase.mode)
    )


@dataclass(frozen=True, slots=True)
class ReferenceAgentRunSummary:
    """Sanitized summary of one Claude Code benchmark session."""

    events: tuple[ReferenceAgentLogEvent, ...]
    primary_model: str
    auxiliary_models: tuple[str, ...]
    provider: str
    permission_denials: int
    terminal_reason: str
    successful: bool


def _as_mapping(value: object, *, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ReferenceAgentRunnerError(f"{label} must be an object")
    return value


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ReferenceAgentRunnerError("agent event timestamp is missing")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReferenceAgentRunnerError("agent event timestamp is invalid") from exc
    if timestamp.utcoffset() is None:
        raise ReferenceAgentRunnerError("agent event timestamp must be timezone-aware")
    return timestamp


def _content_items(row: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    message = row.get("message")
    if not isinstance(message, Mapping):
        return ()
    content = message.get("content")
    if not isinstance(content, list):
        return ()
    return tuple(item for item in content if isinstance(item, Mapping))


def _validate_init(row: Mapping[str, Any], allowed_mcp_tools: frozenset[str] | None = None) -> str:
    tools = row.get("tools")
    if not isinstance(tools, list) or not all(isinstance(item, str) for item in tools):
        raise ReferenceAgentRunnerError("agent tool inventory is missing")
    unexpected = [
        item
        for item in tools
        if item not in _INTERNAL_TOOLS
        and (
            not item.startswith(_MCP_PREFIX)
            or (allowed_mcp_tools is not None and item not in allowed_mcp_tools)
        )
    ]
    if unexpected:
        suffix = " outside reviewed phase surface" if allowed_mcp_tools is not None else ""
        raise ReferenceAgentRunnerError(
            f"agent tool inventory contains unreviewed execution tools{suffix}"
        )
    plugins = row.get("plugins")
    if plugins not in (None, []):
        raise ReferenceAgentRunnerError("agent plugin inventory must be empty")
    servers = row.get("mcp_servers")
    if not isinstance(servers, list) or len(servers) != 1:
        raise ReferenceAgentRunnerError("agent MCP server inventory must contain only kicad")
    server = servers[0]
    if (
        not isinstance(server, Mapping)
        or server.get("name") != "kicad"
        or server.get("status") != "connected"
    ):
        raise ReferenceAgentRunnerError("agent MCP server inventory must contain connected kicad")
    model = row.get("model")
    if not isinstance(model, str) or not model:
        raise ReferenceAgentRunnerError("agent primary model is missing")
    return model


def _result_metadata(
    row: Mapping[str, Any], primary_model: str
) -> tuple[tuple[str, ...], str, int, str, bool]:
    usage = row.get("modelUsage")
    usage_map = usage if isinstance(usage, Mapping) else {}
    model_names = sorted(str(name) for name in usage_map if isinstance(name, str))
    auxiliary = tuple(name for name in model_names if name != primary_model)
    primary_usage = usage_map.get(primary_model)
    provider = "unknown"
    if isinstance(primary_usage, Mapping) and isinstance(primary_usage.get("provider"), str):
        provider = str(primary_usage["provider"])
    denials = row.get("permission_denials")
    denial_count = len(denials) if isinstance(denials, list) else 0
    terminal_reason = row.get("terminal_reason")
    if not isinstance(terminal_reason, str) or not terminal_reason:
        terminal_reason = "unknown"
    successful = (
        row.get("subtype") == "success"
        and row.get("is_error") is False
        and denial_count == 0
        and terminal_reason == "completed"
    )
    return auxiliary, provider, denial_count, terminal_reason, successful


def load_phase_prompt(path: Path, phase: ReferenceAgentPhase) -> str:
    """Select one reviewed phase prompt while preserving the common prompt preamble."""
    text = path.read_text(encoding="utf-8")
    headings = tuple(f"## Phase: {name}" for name in ("schematic", "pcb", "manufacturing"))
    positions = {heading: text.find(heading) for heading in headings}
    if any(position < 0 for position in positions.values()):
        raise ReferenceAgentRunnerError("original prompt must declare all three reviewed phases")
    ordered = sorted((position, heading) for heading, position in positions.items())
    if [heading for _, heading in ordered] != list(headings):
        raise ReferenceAgentRunnerError("original prompt phases must use canonical order")
    common = text[: ordered[0][0]].strip()
    selected_heading = f"## Phase: {phase.name}"
    selected_index = headings.index(selected_heading)
    start = positions[selected_heading] + len(selected_heading)
    end = len(text)
    if selected_index + 1 < len(headings):
        end = positions[headings[selected_index + 1]]
    selected = text[start:end].strip()
    if not common or not selected:
        raise ReferenceAgentRunnerError(
            "original prompt common and phase sections must be non-empty"
        )
    return f"{common}\n\n{selected_heading}\n{selected}\n"


def build_mcp_config(
    *,
    phase: ReferenceAgentPhase,
    uv_executable: Path,
    checkout_dir: Path,
    project_dir: Path,
    kicad_cli: Path,
) -> dict[str, Any]:
    """Build one strict stdio KiCad MCP configuration for a benchmark phase."""
    return {
        "mcpServers": {
            "kicad": {
                "type": "stdio",
                "command": str(uv_executable),
                "args": ["--directory", str(checkout_dir), "run", "--frozen", "kicad-mcp-pro"],
                "env": {
                    "KICAD_MCP_PROJECT_DIR": str(project_dir),
                    "KICAD_MCP_PROFILE": phase.profile,
                    "KICAD_MCP_OPERATING_MODE": phase.mode,
                    "KICAD_MCP_KICAD_CLI": str(kicad_cli),
                },
            }
        }
    }


def build_claude_command(
    *,
    claude_executable: str,
    model: str,
    settings_path: Path,
    mcp_config_path: Path,
) -> tuple[str, ...]:
    """Build the isolated Claude Code command used by reference-board attempts."""
    return (
        claude_executable,
        "-p",
        "--model",
        model,
        "--setting-sources",
        "project",
        "--settings",
        str(settings_path),
        "--strict-mcp-config",
        "--mcp-config",
        str(mcp_config_path),
        "--tools",
        "ToolSearch",
        "--allowedTools",
        "mcp__kicad__*",
        "--output-format",
        "stream-json",
        "--verbose",
    )


def parse_claude_stream(
    lines: Iterable[str],
    *,
    attempt_id: str,
    allowed_mcp_tools: frozenset[str] | None = None,
) -> ReferenceAgentRunSummary:
    """Convert one Claude stream-json session to sanitized reference evidence."""
    rows: list[Mapping[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReferenceAgentRunnerError("agent stream contains invalid JSON") from exc
        rows.append(_as_mapping(value, label="agent stream record"))

    init = next(
        (row for row in rows if row.get("type") == "system" and row.get("subtype") == "init"),
        None,
    )
    if init is None:
        raise ReferenceAgentRunnerError("agent stream is missing init metadata")
    primary_model = _validate_init(init, allowed_mcp_tools)

    tool_names: dict[str, str | None] = {}
    events: list[ReferenceAgentLogEvent] = []

    for row in rows:
        row_type = row.get("type")
        for item in _content_items(row):
            item_type = item.get("type")
            if row_type == "assistant" and item_type == "tool_use":
                tool_id = item.get("id")
                tool_name = item.get("name")
                if not isinstance(tool_id, str) or not isinstance(tool_name, str):
                    raise ReferenceAgentRunnerError("agent tool call is missing identity")
                if tool_name in _INTERNAL_TOOLS:
                    tool_names[tool_id] = None
                    continue
                if not tool_name.startswith(_MCP_PREFIX):
                    raise ReferenceAgentRunnerError(f"agent executed unreviewed tool {tool_name!r}")
                normalized_name = tool_name.removeprefix(_MCP_PREFIX)
                tool_names[tool_id] = normalized_name
                events.append(
                    ReferenceAgentLogEvent(
                        attempt_id=attempt_id,
                        sequence=len(events) + 1,
                        timestamp=_timestamp(row.get("timestamp")),
                        event_type="tool_call",
                        name=normalized_name,
                        status="started",
                    )
                )
            elif row_type == "user" and item_type == "tool_result":
                tool_id = item.get("tool_use_id")
                if not isinstance(tool_id, str) or tool_id not in tool_names:
                    raise ReferenceAgentRunnerError("agent tool result has unknown tool-use id")
                result_name = tool_names[tool_id]
                if result_name is None:
                    continue
                status = "failed" if item.get("is_error") is True else "completed"
                events.append(
                    ReferenceAgentLogEvent(
                        attempt_id=attempt_id,
                        sequence=len(events) + 1,
                        timestamp=_timestamp(row.get("timestamp")),
                        event_type="tool_result",
                        name=result_name,
                        status=status,
                    )
                )

    result = next((row for row in reversed(rows) if row.get("type") == "result"), None)
    if result is None:
        raise ReferenceAgentRunnerError("agent stream is missing terminal result")
    auxiliary, provider, denials, terminal_reason, successful = _result_metadata(
        result, primary_model
    )
    return ReferenceAgentRunSummary(
        events=tuple(events),
        primary_model=primary_model,
        auxiliary_models=auxiliary,
        provider=provider,
        permission_denials=denials,
        terminal_reason=terminal_reason,
        successful=successful,
    )


def write_agent_log(path: Path, summary: ReferenceAgentRunSummary, *, append: bool = False) -> None:
    """Write sanitized publication events, optionally extending one attempt log."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[ReferenceAgentLogEvent] = []
    if append and path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                existing.append(ReferenceAgentLogEvent.model_validate_json(line))
            except ValueError as exc:
                raise ReferenceAgentRunnerError("existing agent log is invalid") from exc
    if existing and summary.events:
        attempt_id = existing[0].attempt_id
        if any(event.attempt_id != attempt_id for event in existing + list(summary.events)):
            raise ReferenceAgentRunnerError("agent log append crosses attempt identities")
    offset = len(existing)
    appended = tuple(
        event.model_copy(update={"sequence": offset + index})
        for index, event in enumerate(summary.events, start=1)
    )
    events = tuple(existing) + appended if append else appended
    payload = "".join(event.model_dump_json() + "\n" for event in events)
    path.write_text(payload, encoding="utf-8")


def run_claude_session(
    *,
    command: tuple[str, ...],
    prompt: str,
    raw_stream_path: Path,
    attempt_id: str,
    cwd: Path,
    timeout_seconds: float,
    allowed_mcp_tools: frozenset[str] | None = None,
) -> ReferenceAgentRunSummary:
    """Run one isolated Claude session and retain raw stream only in scratch storage."""
    started_at = datetime.now(UTC)
    completed = subprocess.run(
        command,
        input=prompt,
        cwd=cwd,
        timeout=timeout_seconds,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
        check=False,
    )
    ended_at = datetime.now(UTC)
    raw_stream_path.parent.mkdir(parents=True, exist_ok=True)
    raw_stream_path.write_text(completed.stdout, encoding="utf-8")
    parsed = parse_claude_stream(
        completed.stdout.splitlines(),
        attempt_id=attempt_id,
        allowed_mcp_tools=allowed_mcp_tools,
    )
    successful = parsed.successful and completed.returncode == 0
    events = [
        ReferenceAgentLogEvent(
            attempt_id=attempt_id,
            sequence=1,
            timestamp=started_at,
            event_type="workflow",
            name="claude_session",
            status="started",
        )
    ]
    events.extend(
        event.model_copy(update={"sequence": index})
        for index, event in enumerate(parsed.events, start=2)
    )
    events.append(
        ReferenceAgentLogEvent(
            attempt_id=attempt_id,
            sequence=len(events) + 1,
            timestamp=ended_at,
            event_type="workflow",
            name="claude_session",
            status="completed" if successful else "failed",
            details={"exit_code": completed.returncode},
        )
    )
    return ReferenceAgentRunSummary(
        events=tuple(events),
        primary_model=parsed.primary_model,
        auxiliary_models=parsed.auxiliary_models,
        provider=parsed.provider,
        permission_denials=parsed.permission_denials,
        terminal_reason=parsed.terminal_reason,
        successful=successful,
    )
