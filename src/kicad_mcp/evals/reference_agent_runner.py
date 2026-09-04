"""Sanitized execution evidence helpers for real reference-board agent runs."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ..discovery import discover_kicad_cli, find_kicad_version
from ..operating_modes import is_tool_allowed_in_mode
from ..tools.router import tools_for_profile
from .reference_corpus import ReferenceAgentLogEvent

_MCP_PREFIX = "mcp__kicad__"
_CLAUDE_EXECUTABLE = "claude"
_CLAUDE_MODEL = "claude-sonnet-5"
_INTERNAL_TOOLS = frozenset({"ToolSearch"})


class ReferenceAgentRunnerError(ValueError):
    """Raised when a benchmark agent stream violates the reviewed execution contract."""


_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_ATTEMPT_IDENTIFIER = re.compile(r"^attempt-[0-9]{3,6}$")
_VERSION_IDENTIFIER = re.compile(r"^v[1-9][0-9]*$")
_REVIEWED_BOARD_ROOTS = {
    "esp32-c6-usbc": Path("docs/evidence/reference-boards/esp32-c6-usbc/v1"),
    "stm32f072-usbc": Path("docs/evidence/reference-boards/stm32f072-usbc/v1"),
    "rp2350-usbc": Path("docs/evidence/reference-boards/rp2350-usbc/v1"),
}


@dataclass(frozen=True, slots=True)
class ReferenceAgentWorkspace:
    """Deterministic private/public paths for one reviewed board attempt."""

    checkout_dir: Path
    board_id: str
    version: str
    attempt_id: str
    prompt_path: Path
    agent_log_path: Path
    scratch_dir: Path
    project_dir: Path

    @classmethod
    def for_board(
        cls, *, checkout_dir: Path, board_id: str, version: str, attempt_id: str
    ) -> ReferenceAgentWorkspace:
        if not _IDENTIFIER.fullmatch(board_id):
            raise ReferenceAgentRunnerError("board identifier is invalid")
        if not _VERSION_IDENTIFIER.fullmatch(version):
            raise ReferenceAgentRunnerError("version identifier is invalid")
        if not _ATTEMPT_IDENTIFIER.fullmatch(attempt_id):
            raise ReferenceAgentRunnerError("attempt identifier is invalid")
        root = checkout_dir.resolve()
        board_root = root / "docs" / "evidence" / "reference-boards" / board_id / version
        prompt = board_root / "original-prompt.md"
        if not prompt.is_file() or prompt.is_symlink():
            raise ReferenceAgentRunnerError("reviewed original prompt is missing")
        scratch = root / ".dev-tools" / "reference-agent-runs" / board_id / version / attempt_id
        return cls(
            checkout_dir=root,
            board_id=board_id,
            version=version,
            attempt_id=attempt_id,
            prompt_path=prompt,
            agent_log_path=board_root / "attempts" / attempt_id / "agent-log.jsonl",
            scratch_dir=scratch,
            project_dir=scratch / "project",
        )

    @classmethod
    def for_reviewed_attempt(
        cls, *, checkout_dir: Path, board_id: str, attempt_number: int
    ) -> ReferenceAgentWorkspace:
        try:
            board_relative = _REVIEWED_BOARD_ROOTS[board_id]
        except KeyError as exc:
            raise ReferenceAgentRunnerError("board is not in reviewed board set") from exc
        if not 1 <= attempt_number <= 999:
            raise ReferenceAgentRunnerError("attempt number must be between 1 and 999")
        root = checkout_dir.resolve()
        board_root = root / board_relative
        prompt = board_root / "original-prompt.md"
        if not prompt.is_file() or prompt.is_symlink():
            raise ReferenceAgentRunnerError("reviewed original prompt is missing")
        canonical_board_id = board_relative.parent.name
        attempt_id = f"attempt-{attempt_number:03d}"
        scratch = root / ".dev-tools/reference-agent-runs" / canonical_board_id / "v1" / attempt_id
        return cls(
            checkout_dir=root,
            board_id=canonical_board_id,
            version="v1",
            attempt_id=attempt_id,
            prompt_path=prompt,
            agent_log_path=board_root / "attempts" / attempt_id / "agent-log.jsonl",
            scratch_dir=scratch,
            project_dir=scratch / "project",
        )

    def phase_settings_path(self, phase: ReferenceAgentPhase) -> Path:
        return self.scratch_dir / f"{phase.name}-settings.json"

    def phase_mcp_config_path(self, phase: ReferenceAgentPhase) -> Path:
        return self.scratch_dir / f"{phase.name}-mcp.json"

    def phase_raw_stream_path(self, phase: ReferenceAgentPhase) -> Path:
        return self.scratch_dir / f"{phase.name}-claude-stream.jsonl"


def _reference_kicad_candidates() -> tuple[Path, ...]:
    candidates: list[Path] = []
    discovered = discover_kicad_cli()
    candidates.append(discovered)
    if sys.platform == "win32":
        candidates.extend(
            (
                Path.home() / "AppData/Local/Programs/KiCad/10.0/bin/kicad-cli.exe",
                Path("C:/Program Files/KiCad/10.0/bin/kicad-cli.exe"),
            )
        )
    unique: list[Path] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return tuple(unique)


def discover_reference_kicad_cli() -> Path:
    """Return a working KiCad 10 CLI for reproducible reference-board runs."""
    for candidate in _reference_kicad_candidates():
        if not candidate.is_file():
            continue
        version = find_kicad_version(candidate)
        if version is not None and version.lstrip("v").startswith("10."):
            return candidate.resolve()
    raise ReferenceAgentRunnerError("working KiCad 10 CLI was not found")


@dataclass(frozen=True, slots=True)
class ReferenceAgentPhase:
    """Reviewed KiCad MCP profile/mode pair for one benchmark phase."""

    name: Literal["schematic", "pcb", "manufacturing"]
    profile: Literal["schematic_authoring", "pcb_layout", "release"]
    mode: Literal["write", "manufacturing"]

    @classmethod
    def for_name(cls, name: str) -> ReferenceAgentPhase:
        phases = {
            "schematic": cls("schematic", "schematic_authoring", "write"),
            "pcb": cls("pcb", "pcb_layout", "write"),
            "manufacturing": cls("manufacturing", "release", "manufacturing"),
        }
        try:
            return phases[name]
        except KeyError as exc:
            raise ReferenceAgentRunnerError(f"unsupported reference-agent phase: {name}") from exc


_SCHEMATIC_EXECUTION_TOOLS = (
    "kicad_create_new_project",
    "kicad_set_project",
    "kicad_get_project_info",
    "kicad_get_server_info",
    "kicad_get_version",
    "project_set_design_intent",
    "project_get_design_spec",
    "lib_search_symbols",
    "lib_get_symbol_info",
    "lib_search_footprints",
    "lib_get_footprint_info",
    "lib_verify_component_contract",
    "lib_assign_footprint",
    "sch_add_symbol",
    "sch_add_wire",
    "sch_route_wire_between_pins",
    "sch_add_label",
    "sch_add_global_label",
    "sch_add_power_symbol",
    "sch_add_no_connect",
    "sch_update_properties",
    "sch_annotate",
    "sch_auto_place_functional",
    "sch_get_symbols",
    "sch_get_connectivity_graph",
    "sch_get_net_names",
    "sch_check_power_flags",
    "sch_visual_qa",
    "run_erc",
    "schematic_connectivity_gate",
    "schematic_quality_gate",
    "validate_design",
    "project_quality_gate",
    "vcs_commit_checkpoint",
    "vcs_diff_with_checkpoint",
)

_PCB_EXECUTION_TOOLS = (
    "kicad_set_project",
    "kicad_get_project_info",
    "kicad_get_server_info",
    "pcb_sync_from_schematic",
    "pcb_get_board_summary",
    "pcb_get_footprints",
    "pcb_get_nets",
    "pcb_get_tracks",
    "pcb_get_vias",
    "pcb_get_ratsnest",
    "pcb_get_design_rules",
    "pcb_set_board_outline",
    "pcb_set_design_rules",
    "pcb_set_net_class",
    "pcb_auto_place_by_schematic",
    "pcb_place_component",
    "pcb_move_component",
    "pcb_add_track",
    "pcb_route_trace",
    "pcb_add_tracks_bulk",
    "pcb_add_via",
    "pcb_add_copper_zone",
    "pcb_refill_zones",
    "pcb_save",
    "pcb_begin_commit",
    "pcb_push_commit",
    "pcb_drop_commit",
    "pcb_revert",
    "pcb_delete_items",
    "run_drc",
    "run_erc",
    "get_unconnected_nets",
    "validate_footprints_vs_schematic",
    "pcb_quality_gate",
    "pcb_placement_quality_gate",
    "project_quality_gate",
    "vcs_commit_checkpoint",
    "vcs_diff_with_checkpoint",
)


def catalog_mcp_tools(phase: ReferenceAgentPhase) -> frozenset[str]:
    """Return the profile/mode catalog boundary visible to the benchmark agent."""
    return frozenset(
        _MCP_PREFIX + tool
        for tool in tools_for_profile(phase.profile)
        if is_tool_allowed_in_mode(tool, phase.mode)
    )


def reviewed_mcp_tools(phase: ReferenceAgentPhase) -> frozenset[str]:
    """Return the exact reviewed execution ceiling for one benchmark phase."""
    tools: tuple[str, ...]
    if phase.name == "schematic":
        tools = _SCHEMATIC_EXECUTION_TOOLS
    elif phase.name == "pcb":
        tools = _PCB_EXECUTION_TOOLS
    else:
        tools = tuple(tools_for_profile("release"))
    reviewed = frozenset(_MCP_PREFIX + tool for tool in tools)
    catalog = catalog_mcp_tools(phase)
    if not reviewed <= catalog:
        raise ReferenceAgentRunnerError("reviewed execution tools exceed phase catalog")
    return reviewed


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


def _validate_init(row: Mapping[str, Any], catalog_mcp_tools: frozenset[str] | None = None) -> str:
    tools = row.get("tools")
    if not isinstance(tools, list) or not all(isinstance(item, str) for item in tools):
        raise ReferenceAgentRunnerError("agent tool inventory is missing")
    unexpected = [
        item
        for item in tools
        if item not in _INTERNAL_TOOLS
        and (
            not item.startswith(_MCP_PREFIX)
            or (catalog_mcp_tools is not None and item not in catalog_mcp_tools)
        )
    ]
    if unexpected:
        suffix = " outside reviewed phase surface" if catalog_mcp_tools is not None else ""
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


def load_phase_prompt(workspace: ReferenceAgentWorkspace, phase: ReferenceAgentPhase) -> str:
    """Select one reviewed phase prompt while preserving the common prompt preamble."""
    text = workspace.prompt_path.read_text(encoding="utf-8")
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
    workspace: ReferenceAgentWorkspace,
    kicad_cli: Path,
) -> dict[str, Any]:
    """Build one strict stdio KiCad MCP configuration for a benchmark phase."""
    return {
        "mcpServers": {
            "kicad": {
                "type": "stdio",
                "command": sys.executable,
                "args": ["-m", "kicad_mcp.server"],
                "env": {
                    "KICAD_MCP_PROJECT_DIR": str(workspace.project_dir),
                    "KICAD_MCP_PROFILE": phase.profile,
                    "KICAD_MCP_OPERATING_MODE": phase.mode,
                    "KICAD_MCP_KICAD_CLI": str(kicad_cli),
                },
            }
        }
    }


def build_claude_command(
    *,
    settings_path: Path,
    mcp_config_path: Path,
    allowed_mcp_tools: frozenset[str],
) -> tuple[str, ...]:
    """Build the canonical isolated Claude Code command for reference-board attempts."""
    return (
        _CLAUDE_EXECUTABLE,
        "-p",
        "--model",
        _CLAUDE_MODEL,
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
        ",".join(sorted(allowed_mcp_tools)),
        "--output-format",
        "stream-json",
        "--verbose",
    )


def _parse_stream_rows(lines: Iterable[str]) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ReferenceAgentRunnerError("agent stream contains invalid JSON") from exc
        rows.append(_as_mapping(value, label="agent stream record"))
    return rows


def _required_stream_record(
    rows: Iterable[Mapping[str, Any]], *, record_type: str, subtype: str | None = None
) -> Mapping[str, Any]:
    for row in rows:
        if row.get("type") != record_type:
            continue
        if subtype is not None and row.get("subtype") != subtype:
            continue
        return row
    label = f"{record_type}/{subtype}" if subtype is not None else record_type
    raise ReferenceAgentRunnerError(f"agent stream is missing {label} metadata")


def _tool_call_event(
    row: Mapping[str, Any],
    item: Mapping[str, Any],
    *,
    attempt_id: str,
    sequence: int,
    allowed_mcp_tools: frozenset[str] | None,
) -> tuple[str, str | None, ReferenceAgentLogEvent | None]:
    tool_id = item.get("id")
    tool_name = item.get("name")
    if not isinstance(tool_id, str) or not isinstance(tool_name, str):
        raise ReferenceAgentRunnerError("agent tool call is missing identity")
    if tool_name in _INTERNAL_TOOLS:
        return tool_id, None, None
    if not tool_name.startswith(_MCP_PREFIX):
        raise ReferenceAgentRunnerError(f"agent executed unreviewed tool {tool_name!r}")
    if allowed_mcp_tools is not None and tool_name not in allowed_mcp_tools:
        raise ReferenceAgentRunnerError(
            "agent executed tool outside reviewed phase execution surface"
        )
    normalized_name = tool_name.removeprefix(_MCP_PREFIX)
    event = ReferenceAgentLogEvent(
        attempt_id=attempt_id,
        sequence=sequence,
        timestamp=_timestamp(row.get("timestamp")),
        event_type="tool_call",
        name=normalized_name,
        status="started",
    )
    return tool_id, normalized_name, event


def _tool_result_event(
    row: Mapping[str, Any],
    item: Mapping[str, Any],
    *,
    attempt_id: str,
    sequence: int,
    tool_names: Mapping[str, str | None],
) -> ReferenceAgentLogEvent | None:
    tool_id = item.get("tool_use_id")
    if not isinstance(tool_id, str) or tool_id not in tool_names:
        raise ReferenceAgentRunnerError("agent tool result has unknown tool-use id")
    result_name = tool_names[tool_id]
    if result_name is None:
        return None
    status: Literal["failed", "completed"] = (
        "failed" if item.get("is_error") is True else "completed"
    )
    return ReferenceAgentLogEvent(
        attempt_id=attempt_id,
        sequence=sequence,
        timestamp=_timestamp(row.get("timestamp")),
        event_type="tool_result",
        name=result_name,
        status=status,
    )


def _stream_tool_events(
    rows: Iterable[Mapping[str, Any]],
    *,
    attempt_id: str,
    allowed_mcp_tools: frozenset[str] | None,
) -> tuple[ReferenceAgentLogEvent, ...]:
    tool_names: dict[str, str | None] = {}
    events: list[ReferenceAgentLogEvent] = []
    for row in rows:
        row_type = row.get("type")
        for item in _content_items(row):
            if row_type == "assistant" and item.get("type") == "tool_use":
                tool_id, name, event = _tool_call_event(
                    row,
                    item,
                    attempt_id=attempt_id,
                    sequence=len(events) + 1,
                    allowed_mcp_tools=allowed_mcp_tools,
                )
                tool_names[tool_id] = name
                if event is not None:
                    events.append(event)
            elif row_type == "user" and item.get("type") == "tool_result":
                event = _tool_result_event(
                    row,
                    item,
                    attempt_id=attempt_id,
                    sequence=len(events) + 1,
                    tool_names=tool_names,
                )
                if event is not None:
                    events.append(event)
    return tuple(events)


def parse_claude_stream(
    lines: Iterable[str],
    *,
    attempt_id: str,
    catalog_mcp_tools: frozenset[str] | None = None,
    allowed_mcp_tools: frozenset[str] | None = None,
) -> ReferenceAgentRunSummary:
    """Convert one Claude stream-json session to sanitized reference evidence."""
    rows = _parse_stream_rows(lines)
    init = _required_stream_record(rows, record_type="system", subtype="init")
    init_boundary = catalog_mcp_tools if catalog_mcp_tools is not None else allowed_mcp_tools
    primary_model = _validate_init(init, init_boundary)
    events = _stream_tool_events(rows, attempt_id=attempt_id, allowed_mcp_tools=allowed_mcp_tools)
    result = _required_stream_record(reversed(rows), record_type="result")
    auxiliary, provider, denials, terminal_reason, successful = _result_metadata(
        result, primary_model
    )
    return ReferenceAgentRunSummary(
        events=events,
        primary_model=primary_model,
        auxiliary_models=auxiliary,
        provider=provider,
        permission_denials=denials,
        terminal_reason=terminal_reason,
        successful=successful,
    )


def write_agent_log(
    workspace: ReferenceAgentWorkspace, summary: ReferenceAgentRunSummary, *, append: bool = False
) -> None:
    """Write sanitized publication events, optionally extending one attempt log."""
    path = workspace.agent_log_path
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
    path.write_text(payload, encoding="utf-8", newline="\n")


def _failed_session_summary(
    *,
    attempt_id: str,
    model: str,
    started_at: datetime,
    ended_at: datetime,
    terminal_reason: str,
    details: Mapping[str, bool | int | float | str] | None = None,
) -> ReferenceAgentRunSummary:
    events = (
        ReferenceAgentLogEvent(
            attempt_id=attempt_id,
            sequence=1,
            timestamp=started_at,
            event_type="workflow",
            name="claude_session",
            status="started",
        ),
        ReferenceAgentLogEvent(
            attempt_id=attempt_id,
            sequence=2,
            timestamp=ended_at,
            event_type="workflow",
            name="claude_session",
            status="failed",
            details=dict(details or {}),
        ),
    )
    return ReferenceAgentRunSummary(
        events=events,
        primary_model=model,
        auxiliary_models=(),
        provider="unknown",
        permission_denials=0,
        terminal_reason=terminal_reason,
        successful=False,
    )


def run_claude_session(
    *,
    workspace: ReferenceAgentWorkspace,
    phase: ReferenceAgentPhase,
    prompt: str,
    timeout_seconds: float,
    catalog_mcp_tools: frozenset[str] | None = None,
    allowed_mcp_tools: frozenset[str] | None = None,
) -> ReferenceAgentRunSummary:
    """Run one isolated Claude session with only deterministic workspace paths."""
    settings_path = workspace.phase_settings_path(phase)
    mcp_config_path = workspace.phase_mcp_config_path(phase)
    raw_stream_path = workspace.phase_raw_stream_path(phase)
    execution_tools = allowed_mcp_tools or reviewed_mcp_tools(phase)
    command = build_claude_command(
        settings_path=settings_path,
        mcp_config_path=mcp_config_path,
        allowed_mcp_tools=execution_tools,
    )
    started_at = datetime.now(UTC)
    try:
        completed = subprocess.run(
            command,
            input=prompt,
            cwd=workspace.checkout_dir,
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        ended_at = datetime.now(UTC)
        output = (
            exc.stdout.decode("utf-8", errors="replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        raw_stream_path.parent.mkdir(parents=True, exist_ok=True)
        raw_stream_path.write_text(output, encoding="utf-8")
        return _failed_session_summary(
            attempt_id=workspace.attempt_id,
            model=_CLAUDE_MODEL,
            started_at=started_at,
            ended_at=ended_at,
            terminal_reason="timeout",
            details={"timeout_seconds": timeout_seconds},
        )
    except OSError:
        ended_at = datetime.now(UTC)
        raw_stream_path.parent.mkdir(parents=True, exist_ok=True)
        raw_stream_path.write_text("", encoding="utf-8")
        return _failed_session_summary(
            attempt_id=workspace.attempt_id,
            model=_CLAUDE_MODEL,
            started_at=started_at,
            ended_at=ended_at,
            terminal_reason="process_launch_failed",
        )

    ended_at = datetime.now(UTC)
    stdout = completed.stdout if isinstance(completed.stdout, str) else ""
    raw_stream_path.parent.mkdir(parents=True, exist_ok=True)
    raw_stream_path.write_text(stdout, encoding="utf-8")
    try:
        parsed = parse_claude_stream(
            stdout.splitlines(),
            attempt_id=workspace.attempt_id,
            catalog_mcp_tools=catalog_mcp_tools,
            allowed_mcp_tools=execution_tools,
        )
    except ReferenceAgentRunnerError:
        return _failed_session_summary(
            attempt_id=workspace.attempt_id,
            model=_CLAUDE_MODEL,
            started_at=started_at,
            ended_at=ended_at,
            terminal_reason="stream_contract_violation",
            details={"exit_code": completed.returncode},
        )

    successful = parsed.successful and completed.returncode == 0
    events = [
        ReferenceAgentLogEvent(
            attempt_id=workspace.attempt_id,
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
            attempt_id=workspace.attempt_id,
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
