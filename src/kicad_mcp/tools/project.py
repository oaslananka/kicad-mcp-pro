"""Project setup and discovery tools."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal, cast

import structlog
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel, Field

from .. import __version__
from ..config import get_config
from ..connection import KiCadConnectionError, get_kicad, reset_connection
from ..discovery import (
    discover_library_paths,
    find_kicad_version,
    find_recent_projects,
    scan_project_dir,
)
from ..file_formats import upgrade_generated_file
from ..models.component_contracts import find_component_contract
from ..models.intent import (
    ComplianceTarget,
    CostTarget,
    InterfaceSpec,
    MechanicalConstraint,
    PowerRailSpec,
    ThermalEnvelope,
)
from ..models.state import (
    DesignWorkflowState,
    WorkflowPhaseState,
    WorkflowPhaseStatus,
    WorkflowRole,
)
from ..models.verdict import Finding, SuggestedFix, Verdict, stable_finding_id
from ..operating_modes import OperatingMode, active_operating_mode
from ..path_safety import assert_within
from ..project.context import ProjectContextService
from ..project.creation import ProjectCreationService
from ..project.discovery import ProjectDiscoveryService
from ..prompts.workflows import render_professional_circuit_design_prompt
from ..utils.cache import clear_ttl_cache, ttl_cache
from . import project_context, project_creation, project_discovery
from .design_intent_state import (
    DecouplingPairIntent,
    ProjectDesignIntent,
    ProjectDesignSpec,
    ProjectSpecResolution,
    ProjectSpecSource,
    RFKeepoutIntent,
    set_design_intent_resolver,
)
from .export_support import _run_cli
from .fixers import fixers_for_gate, sampling_prompt_for_gate
from .metadata import headless_compatible
from .router import TOOL_CATEGORIES, available_profiles

logger = structlog.get_logger(__name__)
__all__ = [
    "DecouplingPairIntent",
    "ProjectDesignIntent",
    "ProjectDesignSpec",
    "ProjectSpecResolution",
    "ProjectSpecSource",
    "RFKeepoutIntent",
    "resolve_design_intent",
]

PROJECT_SPEC_DIRNAME = ".kicad-mcp"
PROJECT_SPEC_FILENAME = "project_spec.json"
LEGACY_DESIGN_INTENT_FILENAME = "design_intent.json"
DEFAULT_INFERRED_DECOUPLING_DISTANCE_MM = 6.0
_REPORTED_LEGACY_INTENT_PATHS: set[Path] = set()


class ProjectSpecPayload(BaseModel):
    """Structured design-spec payload returned to capable MCP clients."""

    text: str
    source: ProjectSpecSource = "none"
    path: str = ""
    explicit: ProjectDesignSpec = Field(default_factory=ProjectDesignSpec)
    inferred: ProjectDesignSpec = Field(default_factory=ProjectDesignSpec)
    resolved: ProjectDesignSpec = Field(default_factory=ProjectDesignSpec)
    notes: list[str] = Field(default_factory=list)


class ProjectSpecValidationPayload(BaseModel):
    """Structured project-spec validation payload."""

    text: str
    valid: bool
    issues: list[str] = Field(default_factory=list)


class ProjectImportDesignSpecPayload(BaseModel):
    """Structured result for conservative design-spec import."""

    text: str
    valid: bool
    dry_run: bool = True
    wrote: bool = False
    strict: bool = True
    path: str = ""
    missing: list[str] = Field(default_factory=list)
    ambiguous: list[str] = Field(default_factory=list)
    placeholders: list[str] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)
    parsed: ProjectDesignSpec = Field(default_factory=ProjectDesignSpec)


class ProjectNextActionPayload(BaseModel):
    """Structured next-action recommendation derived from the project gate."""

    text: str
    status: str
    verdict: Verdict = "PASS"
    gate: str = ""
    reason: str = ""
    suggested_tool: str = ""
    findings: list[Finding] = Field(default_factory=list)
    next_action: str = ""


class AutoFixAction(BaseModel):
    """One step in the auto-fix loop action plan."""

    gate: str
    status: str
    auto_fixed: bool = False
    auto_fix_description: str = ""
    agent_tool: str = ""
    agent_description: str = ""
    sampling_guidance: str = ""


class AutoFixLoopPayload(BaseModel):
    """Structured result returned by project_auto_fix_loop."""

    text: str
    gate_status: str
    iterations_used: int = 0
    actions: list[AutoFixAction] = Field(default_factory=list)
    remaining_issues: int = 0
    ready_for_release: bool = False


class DesignReportPayload(BaseModel):
    """Comprehensive design-status report combining intent, gates, and recommended actions."""

    text: str
    gate_status: str
    intent_source: ProjectSpecSource = "none"
    power_rails_count: int = 0
    interfaces_count: int = 0
    compliance_count: int = 0
    has_mechanical_constraint: bool = False
    next_tool: str = ""


_AGENT_WORKFLOW_PHASES: tuple[dict[str, object], ...] = (
    {
        "phase": "requirements_review",
        "role": "Planner",
        "high_level_tool": "review_requirements_and_missing_inputs",
        "next_action": "project_get_design_spec()",
        "gates": [],
    },
    {
        "phase": "schematic_capture",
        "role": "Builder",
        "high_level_tool": "create_schematic_from_intent",
        "next_action": "sch_build_circuit()",
        "gates": ["Schematic", "Connectivity"],
    },
    {
        "phase": "schematic_verification",
        "role": "Verifier",
        "high_level_tool": "verify_schematic_semantics",
        "next_action": "schematic_design_rule_check()",
        "gates": ["Schematic", "Connectivity"],
    },
    {
        "phase": "parts_and_footprints",
        "role": "Builder",
        "high_level_tool": "assign_parts_and_footprints_with_evidence",
        "next_action": "validate_footprints_vs_schematic()",
        "gates": ["PCB"],
    },
    {
        "phase": "constraints",
        "role": "Planner",
        "high_level_tool": "generate_board_constraints",
        "next_action": "drc_check_rule_conflicts()",
        "gates": ["DFM"],
    },
    {
        "phase": "placement",
        "role": "Builder",
        "high_level_tool": "place_board_professionally",
        "next_action": "pcb_placement_quality_report()",
        "gates": ["Placement"],
    },
    {
        "phase": "routing",
        "role": "Builder",
        "high_level_tool": "route_board_with_quality_gates",
        "next_action": "route_autoroute_freerouting()",
        "gates": ["PCB"],
    },
    {
        "phase": "full_verification",
        "role": "Verifier",
        "high_level_tool": "run_full_design_verification",
        "next_action": "project_quality_gate_report()",
        "gates": ["Schematic", "Connectivity", "PCB", "Placement", "DFM", "Manufacturing"],
    },
    {
        "phase": "fix_loop",
        "role": "Fixer",
        "high_level_tool": "fix_design_until_gate_passes",
        "next_action": "project_full_validation_loop()",
        "gates": ["Schematic", "Connectivity", "PCB", "Placement", "DFM", "Manufacturing"],
    },
    {
        "phase": "manufacturing_release",
        "role": "Release Manager",
        "high_level_tool": "prepare_manufacturing_release",
        "next_action": "export_manufacturing_package()",
        "gates": ["Manufacturing", "DFM"],
    },
)


def _build_design_workflow(completed_phases: list[str]) -> DesignWorkflowState:
    """Build the typed design-workflow state from the phases already completed.

    The first phase not in ``completed_phases`` becomes ``READY`` (the current
    step); earlier ones are ``COMPLETE`` and later ones ``PENDING``. With every
    phase complete the last phase is reported as the current one.
    """
    completed = {name.strip() for name in completed_phases if name.strip()}
    phases: list[WorkflowPhaseState] = []
    current_index: int | None = None
    for index, spec in enumerate(_AGENT_WORKFLOW_PHASES):
        name = str(spec["phase"])
        if name in completed:
            status: WorkflowPhaseStatus = "COMPLETE"
        elif current_index is None:
            status = "READY"
            current_index = index
        else:
            status = "PENDING"
        role = cast(WorkflowRole, spec["role"])
        phases.append(
            WorkflowPhaseState(
                phase=name,
                role=role,
                status=status,
                high_level_tool=str(spec["high_level_tool"]),
                next_action=str(spec["next_action"]),
                gates=list(cast("list[str]", spec["gates"])),
                human_gate_required=role == "Release Manager",
            )
        )

    if current_index is None:
        current = phases[-1]
        return DesignWorkflowState(
            current_phase=current.phase,
            current_role=current.role,
            overall_status="COMPLETE",
            phases=phases,
            next_action="All phases complete — the design is ready for release.",
            human_gate_required=False,
        )
    current = phases[current_index]
    return DesignWorkflowState(
        current_phase=current.phase,
        current_role=current.role,
        overall_status="READY",
        phases=phases,
        next_action=current.next_action,
        human_gate_required=current.human_gate_required,
    )


_PHASE_STATUS_MARKER: dict[WorkflowPhaseStatus, str] = {
    "COMPLETE": "x",
    "READY": ">",
    "PENDING": " ",
    "NEEDS_REVIEW": "?",
    "BLOCKED": "!",
}


def _render_design_workflow(state: DesignWorkflowState) -> str:
    lines = [
        "Professional PCB design workflow",
        f"- Current phase: {state.current_phase} ({state.current_role})",
        f"- Overall status: {state.overall_status}",
        f"- Next action: {state.next_action}",
    ]
    if state.human_gate_required:
        lines.append("- Human gate required before this phase can complete.")
    lines.append("")
    lines.append("Phases:")
    for phase in state.phases:
        marker = _PHASE_STATUS_MARKER.get(phase.status, " ")
        gates = f" — gates: {', '.join(phase.gates)}" if phase.gates else ""
        lines.append(f"  [{marker}] {phase.phase} ({phase.role}) -> {phase.next_action}{gates}")
    return "\n".join(lines)


def _render_project_info() -> str:
    cfg = get_config()
    cli_status = "found" if cfg.kicad_cli.exists() else "missing"
    operating_mode = active_operating_mode(cfg)
    experimental_enabled = operating_mode is OperatingMode.EXPERIMENTAL
    return "\n".join(
        [
            "Current project configuration:",
            f"- Project directory: {cfg.project_dir or '(not set)'}",
            f"- Project file: {cfg.project_file or '(not set)'}",
            f"- Resolved project: {cfg.project_file or '(not set)'}",
            f"- PCB file: {cfg.pcb_file or '(not set)'}",
            f"- Schematic file: {cfg.sch_file or '(not set)'}",
            f"- Output directory: {cfg.output_dir or '(not set)'}",
            f"- KiCad CLI: {cfg.kicad_cli} ({cli_status})",
            f"- Server profile: {cfg.profile}",
            f"- Experimental tools: {experimental_enabled}",
        ]
    )


def _new_project_files(project_dir: Path, name: str) -> tuple[Path, Path, Path]:
    project_file = project_dir / f"{name}.kicad_pro"
    pcb_file = project_dir / f"{name}.kicad_pcb"
    sch_file = project_dir / f"{name}.kicad_sch"
    return project_file, pcb_file, sch_file


def _minimal_project_payload(project_file: Path) -> dict[str, Any]:
    return {
        "board": {"design_settings": {}},
        "meta": {"filename": project_file.name, "version": 1},
        "schematic": {"legacy_lib_dir": "", "page_layout_descr_file": ""},
    }


def _new_project_payload(kicad_cli: Path, project_file: Path) -> dict[str, Any]:
    share_root = discover_library_paths(kicad_cli).get("root")
    if share_root is not None:
        template_file = share_root / "template" / "kicad.kicad_pro"
        if template_file.is_file():
            try:
                payload = json.loads(template_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                logger.warning(
                    "kicad_project_template_read_failed",
                    template=str(template_file),
                    error=str(exc),
                )
            else:
                if isinstance(payload, dict) and isinstance(payload.get("meta"), dict):
                    payload["meta"]["filename"] = project_file.name
                    return cast(dict[str, Any], payload)
                logger.warning(
                    "kicad_project_template_invalid",
                    template=str(template_file),
                )
    return _minimal_project_payload(project_file)


def _project_spec_dir() -> Path:
    cfg = get_config()
    if cfg.project_dir is None:
        raise ValueError(
            "No project is configured. "
            "Call kicad_set_project() or kicad_create_new_project() first."
        )
    return cfg.project_dir / PROJECT_SPEC_DIRNAME


def _project_spec_path() -> Path:
    return _project_spec_dir() / PROJECT_SPEC_FILENAME


def _legacy_design_intent_path() -> Path:
    cfg = get_config()
    if cfg.project_dir is None:
        raise ValueError(
            "No project is configured. "
            "Call kicad_set_project() or kicad_create_new_project() first."
        )
    output_dir = cfg.output_dir or (cfg.project_dir / "output")
    return output_dir / LEGACY_DESIGN_INTENT_FILENAME


def _normalized_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        cleaned = item.strip()
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(cleaned)
    return ordered


_IMPORT_SUPPORTED_KEYS = {
    "connector_refs",
    "decoupling_pairs",
    "critical_nets",
    "power_tree_refs",
    "analog_refs",
    "digital_refs",
    "sensor_cluster_refs",
    "required_sheets",
    "optional_sheets",
    "rf_keepout_regions",
    "manufacturer",
    "manufacturer_tier",
    "functional_spacing_mm",
    "thermal_hotspots",
    "critical_frequencies_mhz",
    "power_rails",
    "interfaces",
    "mechanical",
    "compliance",
    "cost",
    "thermal",
}
_IMPORT_EXTRA_KEYS = {
    "populate",
    "populate_refs",
    "dnp",
    "dnp_refs",
    "parts",
    "mpn",
    "lcsc",
    "acceptance_criteria",
    "missing_parameters",
    "notes",
}
_PLACEHOLDER_RE = re.compile(
    r"^\s*(?:\{\s*(?:\.\.\.|todo|tbd|unknown|[^{}]*)\s*\}|"
    r"<\s*(?:\.\.\.|todo|tbd|unknown|[^<>]*)\s*>|"
    r"\.\.\.|tbd|todo|unknown|verify|n/?a)\s*$",
    re.IGNORECASE,
)


def _strip_yaml_comment(line: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(line):
        if char == "\\" and in_double and not escaped:
            escaped = True
            continue
        if char == "'" and not in_double and not escaped:
            in_single = not in_single
        elif char == '"' and not in_single and not escaped:
            in_double = not in_double
        elif char == "#" and not in_single and not in_double:
            return line[:index].rstrip()
        escaped = False
    return line.rstrip()


def _parse_import_scalar(value: str) -> object:
    cleaned = value.strip()
    if cleaned == "":
        return ""
    if cleaned in {"[]", "{}"}:
        return [] if cleaned == "[]" else {}
    if cleaned[0:1] in {"'", '"'} and cleaned[-1:] == cleaned[0]:
        return cleaned[1:-1]
    lowered = cleaned.casefold()
    if lowered in {"true", "yes", "on"}:
        return True
    if lowered in {"false", "no", "off"}:
        return False
    if lowered in {"null", "none", "~"}:
        return None
    if cleaned.startswith("[") and cleaned.endswith("]"):
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            inner = cleaned[1:-1].strip()
            if not inner:
                return []
            return [_parse_import_scalar(part) for part in inner.split(",")]
    if cleaned.startswith("{") and cleaned.endswith("}"):
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return cleaned
    try:
        if any(token in cleaned for token in (".", "e", "E")):
            return float(cleaned)
        return int(cleaned)
    except ValueError:
        return cleaned


def _import_yaml_lines(text: str) -> list[tuple[int, str]]:
    rows: list[tuple[int, str]] = []
    for raw in text.splitlines():
        line = _strip_yaml_comment(raw.rstrip("\n"))
        if not line.strip():
            continue
        rows.append((len(line) - len(line.lstrip(" ")), line.strip()))
    return rows


def _parse_simple_yaml(text: str) -> object:
    """Parse a conservative YAML subset used for machine-readable spec blocks."""

    rows = _import_yaml_lines(text)
    if not rows:
        return {}

    def parse_block(index: int, indent: int) -> tuple[Any, int]:
        if index >= len(rows):
            return {}, index
        if rows[index][0] < indent:
            return {}, index
        if rows[index][1].startswith("- "):
            return parse_list(index, rows[index][0])
        return parse_dict(index, rows[index][0])

    def parse_dict(index: int, indent: int) -> tuple[dict[str, Any], int]:
        mapping: dict[str, Any] = {}
        while index < len(rows):
            current_indent, content = rows[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                index += 1
                continue
            if content.startswith("- "):
                break
            if ":" not in content:
                index += 1
                continue
            key, raw_value = content.split(":", 1)
            key = key.strip()
            raw_value = raw_value.strip()
            index += 1
            if raw_value:
                mapping[key] = _parse_import_scalar(raw_value)
            elif index < len(rows) and rows[index][0] > current_indent:
                child, index = parse_block(index, rows[index][0])
                mapping[key] = child
            else:
                mapping[key] = None
        return mapping, index

    def parse_list(index: int, indent: int) -> tuple[list[Any], int]:
        values: list[Any] = []
        while index < len(rows):
            current_indent, content = rows[index]
            if current_indent < indent:
                break
            if current_indent > indent or not content.startswith("- "):
                break
            item_text = content[2:].strip()
            index += 1
            if not item_text:
                if index < len(rows) and rows[index][0] > current_indent:
                    child, index = parse_block(index, rows[index][0])
                    values.append(child)
                else:
                    values.append(None)
                continue
            if ":" in item_text and not item_text.startswith(("'", '"', "[", "{")):
                key, raw_value = item_text.split(":", 1)
                item: dict[str, Any] = {}
                if raw_value.strip():
                    item[key.strip()] = _parse_import_scalar(raw_value.strip())
                elif index < len(rows) and rows[index][0] > current_indent:
                    child, index = parse_block(index, rows[index][0])
                    item[key.strip()] = child
                else:
                    item[key.strip()] = None
                if index < len(rows) and rows[index][0] > current_indent:
                    continuation, index = parse_dict(index, rows[index][0])
                    item.update(continuation)
                values.append(item)
            else:
                values.append(_parse_import_scalar(item_text))
        return values, index

    parsed, index = parse_block(0, rows[0][0])
    if index < len(rows):
        raise ValueError("Unsupported YAML layout in design-spec block.")
    return parsed


def _extract_structured_spec_block(markdown: str) -> tuple[dict[str, Any], str]:
    stripped = markdown.strip()
    if not stripped:
        raise ValueError("No design-spec content was provided.")
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed, "json"

    if stripped.startswith("---"):
        lines = stripped.splitlines()
        for index, line in enumerate(lines[1:], start=1):
            if line.strip() == "---":
                block = "\n".join(lines[1:index])
                parsed_yaml = _parse_simple_yaml(block)
                if isinstance(parsed_yaml, dict):
                    return parsed_yaml, "frontmatter"
                break

    fence = re.search(r"```(?:json|ya?ml)\s*(.*?)```", markdown, re.IGNORECASE | re.DOTALL)
    if fence is not None:
        block = fence.group(1).strip()
        try:
            parsed_fence = json.loads(block)
        except json.JSONDecodeError:
            parsed_fence = _parse_simple_yaml(block)
        if isinstance(parsed_fence, dict):
            return parsed_fence, "fenced"

    raise ValueError(
        "No structured design spec found. Provide JSON or YAML frontmatter/fenced block."
    )


def _select_design_intent_payload(payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    for key in ("design_intent", "project_design_intent", "project_spec", "intent"):
        value = payload.get(key)
        if isinstance(value, dict):
            extras = {k: v for k, v in payload.items() if k != key}
            return value, extras
    return payload, {}


def _is_placeholder_value(value: object) -> bool:
    return isinstance(value, str) and bool(_PLACEHOLDER_RE.match(value))


def _walk_import_values(value: object, path: str = "") -> list[str]:
    placeholders: list[str] = []
    if _is_placeholder_value(value):
        placeholders.append(path or "<root>")
    elif isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            placeholders.extend(_walk_import_values(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            placeholders.extend(_walk_import_values(child, f"{path}[{index}]"))
    return placeholders


_IMPORT_OMIT = object()


def _sanitize_import_placeholders(value: object) -> object:
    if _is_placeholder_value(value):
        return _IMPORT_OMIT
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, child in value.items():
            new_value = _sanitize_import_placeholders(child)
            if new_value is not _IMPORT_OMIT:
                sanitized[key] = new_value
        return sanitized
    if isinstance(value, list):
        values = []
        for child in value:
            new_value = _sanitize_import_placeholders(child)
            if new_value is not _IMPORT_OMIT:
                values.append(new_value)
        return values
    return value


def _validation_safe_import_payload(intent_payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = _sanitize_import_placeholders(intent_payload)
    if not isinstance(sanitized, dict):
        return {}
    safe = dict(sanitized)
    power_rails = []
    for rail in safe.get("power_rails") or []:
        if not isinstance(rail, dict):
            continue
        if all(
            rail.get(field) not in (None, "") for field in ("name", "voltage_v", "current_max_a")
        ):
            power_rails.append(rail)
    if "power_rails" in safe:
        safe["power_rails"] = power_rails
    interfaces = []
    for iface in safe.get("interfaces") or []:
        if isinstance(iface, dict) and iface.get("kind"):
            interfaces.append(iface)
    if "interfaces" in safe:
        safe["interfaces"] = interfaces
    return safe


def _import_spec_missing_fields(intent_payload: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    if not intent_payload.get("required_sheets"):
        missing.append("required_sheets")
    mechanical = intent_payload.get("mechanical")
    if not isinstance(mechanical, dict):
        missing.extend(["mechanical.board_width_mm", "mechanical.board_height_mm"])
    else:
        for field in ("board_width_mm", "board_height_mm"):
            if mechanical.get(field) in (None, "") or _is_placeholder_value(mechanical.get(field)):
                missing.append(f"mechanical.{field}")
    for index, rail in enumerate(intent_payload.get("power_rails") or []):
        if not isinstance(rail, dict):
            missing.append(f"power_rails[{index}]")
            continue
        for field in ("name", "voltage_v", "current_max_a"):
            if rail.get(field) in (None, "") or _is_placeholder_value(rail.get(field)):
                missing.append(f"power_rails[{index}].{field}")
    return missing


def _import_spec_extra_fields(
    intent_payload: dict[str, Any], outer_extras: dict[str, Any]
) -> dict[str, Any]:
    extras = dict(outer_extras)
    for key in list(intent_payload):
        if key in _IMPORT_EXTRA_KEYS:
            extras[key] = intent_payload[key]
    unsupported = sorted(
        key
        for key in intent_payload
        if key not in _IMPORT_SUPPORTED_KEYS and key not in _IMPORT_EXTRA_KEYS
    )
    if unsupported:
        extras["unsupported_fields"] = unsupported
    return extras


def _read_design_spec_markdown(path: str | None, markdown: str | None) -> tuple[str, str]:
    if markdown and markdown.strip():
        return markdown, "inline"
    if not path:
        raise ValueError("Provide either markdown or path.")
    cfg = get_config()
    raw_path = Path(path)
    if cfg.project_dir is not None and not raw_path.is_absolute():
        raw_path = cfg.project_dir / raw_path
    candidate = raw_path.expanduser().resolve()
    if cfg.project_dir is not None:
        assert_within(cfg.project_dir, candidate)
    return candidate.read_text(encoding="utf-8"), str(candidate)


def _render_import_result(
    *,
    source_kind: str,
    wrote: bool,
    strict: bool,
    dry_run: bool,
    missing: list[str],
    placeholders: list[str],
    ambiguous: list[str],
    extras: dict[str, Any],
    intent: ProjectDesignIntent,
) -> str:
    lines = ["Project design-spec import:"]
    lines.append(f"- Source format: {source_kind}")
    lines.append(f"- Mode: {'dry-run' if dry_run else 'write'}")
    lines.append(f"- Strict: {strict}")
    lines.append(f"- Wrote project spec: {wrote}")
    lines.append(f"- Missing mandatory fields: {len(missing)}")
    for item in missing[:20]:
        lines.append(f"  - {item}")
    lines.append(f"- Placeholder fields: {len(placeholders)}")
    for item in placeholders[:20]:
        lines.append(f"  - {item}")
    lines.append(f"- Ambiguous/extra fields: {len(ambiguous)}")
    for item in ambiguous[:20]:
        lines.append(f"  - {item}")
    if extras:
        lines.append("- Extras retained in response only: " + ", ".join(sorted(extras)))
    lines.append(_render_design_intent(intent))
    return "\n".join(lines)


def import_design_spec(
    *,
    path: str | None,
    markdown: str | None,
    strict: bool,
    dry_run: bool,
) -> ProjectImportDesignSpecPayload:
    content, resolved_path = _read_design_spec_markdown(path, markdown)
    parsed, source_kind = _extract_structured_spec_block(content)
    raw_intent, outer_extras = _select_design_intent_payload(parsed)
    intent_payload = {k: v for k, v in raw_intent.items() if k in _IMPORT_SUPPORTED_KEYS}
    extras = _import_spec_extra_fields(raw_intent, outer_extras)
    ambiguous = [
        f"{field}: retained in import response but not persisted"
        for field in sorted(extras.get("unsupported_fields", []))
    ]
    for field in sorted(set(extras) & _IMPORT_EXTRA_KEYS):
        ambiguous.append(f"{field}: not part of ProjectDesignIntent; not persisted")
    placeholders = _walk_import_values(intent_payload)
    missing = _import_spec_missing_fields(intent_payload)
    if strict and (missing or placeholders):
        valid = False
    else:
        valid = True
    safe_payload = _validation_safe_import_payload(intent_payload)
    intent = _normalize_design_intent(ProjectDesignIntent.model_validate(safe_payload))
    wrote = False
    if not dry_run:
        if not valid:
            raise ValueError(
                "Design spec import refused in strict mode: "
                f"missing={missing or 'none'}, placeholders={placeholders or 'none'}."
            )
        save_design_intent(intent)
        wrote = True
    return ProjectImportDesignSpecPayload(
        text=_render_import_result(
            source_kind=source_kind,
            wrote=wrote,
            strict=strict,
            dry_run=dry_run,
            missing=missing,
            placeholders=placeholders,
            ambiguous=ambiguous,
            extras=extras,
            intent=intent,
        ),
        valid=valid,
        dry_run=dry_run,
        wrote=wrote,
        strict=strict,
        path=resolved_path,
        missing=missing,
        ambiguous=ambiguous,
        placeholders=placeholders,
        extras=extras,
        parsed=intent,
    )


def _normalize_design_intent(intent: ProjectDesignIntent) -> ProjectDesignIntent:
    return ProjectDesignIntent.model_validate(
        {
            # v1 fields
            "connector_refs": _normalized_unique(intent.connector_refs),
            "decoupling_pairs": [
                {
                    "ic_ref": pair.ic_ref.strip(),
                    "cap_refs": _normalized_unique(pair.cap_refs),
                    "max_distance_mm": pair.max_distance_mm,
                }
                for pair in intent.decoupling_pairs
            ],
            "critical_nets": _normalized_unique(intent.critical_nets),
            "power_tree_refs": _normalized_unique(intent.power_tree_refs),
            "analog_refs": _normalized_unique(intent.analog_refs),
            "digital_refs": _normalized_unique(intent.digital_refs),
            "sensor_cluster_refs": _normalized_unique(intent.sensor_cluster_refs),
            "required_sheets": _normalized_unique(intent.required_sheets),
            "optional_sheets": _normalized_unique(intent.optional_sheets),
            "rf_keepout_regions": [region.model_dump() for region in intent.rf_keepout_regions],
            "manufacturer": intent.manufacturer.strip(),
            "manufacturer_tier": intent.manufacturer_tier.strip(),
            "functional_spacing_mm": intent.functional_spacing_mm,
            "thermal_hotspots": _normalized_unique(intent.thermal_hotspots),
            "critical_frequencies_mhz": intent.critical_frequencies_mhz,
            # v2 fields — pass through as-is (already validated by Pydantic)
            "power_rails": [rail.model_dump() for rail in intent.power_rails],
            "interfaces": [iface.model_dump() for iface in intent.interfaces],
            "mechanical": intent.mechanical.model_dump(),
            "compliance": [c.model_dump() for c in intent.compliance],
            "cost": intent.cost.model_dump(),
            "thermal": intent.thermal.model_dump(),
        }
    )


def _load_design_intent_from_path(path: Path) -> ProjectDesignIntent:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("design_intent_load_failed", path=str(path), error=str(exc))
        return ProjectDesignIntent()
    return _normalize_design_intent(ProjectDesignIntent.model_validate(payload))


def _load_saved_design_intent() -> tuple[
    ProjectDesignIntent,
    Path | None,
    ProjectSpecSource,
    list[str],
]:
    notes: list[str] = []
    path = _project_spec_path()
    if path.exists():
        return _load_design_intent_from_path(path), path, "project_spec", notes

    legacy_path = _legacy_design_intent_path()
    if legacy_path.exists():
        if legacy_path not in _REPORTED_LEGACY_INTENT_PATHS:
            _REPORTED_LEGACY_INTENT_PATHS.add(legacy_path)
            logger.info("legacy_design_intent_loaded", path=str(legacy_path))
        notes.append(
            "Loaded legacy output/design_intent.json. "
            "Run project_set_design_intent() to migrate it into .kicad-mcp/project_spec.json."
        )
        return (
            _load_design_intent_from_path(legacy_path),
            legacy_path,
            "legacy_design_intent",
            notes,
        )

    return ProjectDesignIntent(), None, "none", notes


def load_design_intent() -> ProjectDesignIntent:
    """Load the explicitly saved project design intent/spec, if any."""
    intent, _, _, _ = _load_saved_design_intent()
    return intent


def _persist_project_spec(intent: ProjectDesignIntent) -> Path:
    """Persist the normalized project spec to the canonical project_spec.json path."""
    path = _project_spec_path()
    normalized = _normalize_design_intent(intent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalized.model_dump(), indent=2), encoding="utf-8")
    return path


def save_design_intent(intent: ProjectDesignIntent) -> Path:
    """Persist the normalized project design spec inside the project root."""
    return _persist_project_spec(intent)


def _render_design_intent(intent: ProjectDesignIntent) -> str:
    lines = ["Project design spec:"]
    lines.append(
        "- Connector refs: "
        + (", ".join(intent.connector_refs) if intent.connector_refs else "(none)")
    )
    lines.append(
        "- Critical nets: "
        + (", ".join(intent.critical_nets) if intent.critical_nets else "(none)")
    )
    lines.append(
        "- Power-tree refs: "
        + (", ".join(intent.power_tree_refs) if intent.power_tree_refs else "(none)")
    )
    lines.append(
        "- Analog refs: " + (", ".join(intent.analog_refs) if intent.analog_refs else "(none)")
    )
    lines.append(
        "- Digital refs: " + (", ".join(intent.digital_refs) if intent.digital_refs else "(none)")
    )
    lines.append(
        "- Sensor cluster refs: "
        + (", ".join(intent.sensor_cluster_refs) if intent.sensor_cluster_refs else "(none)")
    )
    lines.append(
        "- Required sheets: "
        + (", ".join(intent.required_sheets) if intent.required_sheets else "(none)")
    )
    lines.append(
        "- Optional sheets: "
        + (", ".join(intent.optional_sheets) if intent.optional_sheets else "(none)")
    )
    lines.append(
        "- Manufacturer: "
        + (
            f"{intent.manufacturer} / {intent.manufacturer_tier}"
            if intent.manufacturer or intent.manufacturer_tier
            else "(none)"
        )
    )
    lines.append(f"- Functional spacing: {intent.functional_spacing_mm:.2f} mm")
    lines.append(
        "- Thermal hotspots: "
        + (", ".join(intent.thermal_hotspots) if intent.thermal_hotspots else "(none)")
    )
    lines.append(
        "- Critical frequencies: "
        + (
            ", ".join(f"{frequency:.2f} MHz" for frequency in intent.critical_frequencies_mhz)
            if intent.critical_frequencies_mhz
            else "(none)"
        )
    )
    lines.append(f"- Decoupling pairs: {len(intent.decoupling_pairs)}")
    for pair in intent.decoupling_pairs[:10]:
        lines.append(
            f"  {pair.ic_ref} <- {', '.join(pair.cap_refs)} (max {pair.max_distance_mm:.2f} mm)"
        )
    lines.append(f"- RF keepout regions: {len(intent.rf_keepout_regions)}")
    for region in intent.rf_keepout_regions[:10]:
        lines.append(
            f"  {region.name}: center=({region.x_mm:.2f}, {region.y_mm:.2f}) "
            f"size=({region.w_mm:.2f} x {region.h_mm:.2f}) mm"
        )

    # v2 fields
    if intent.power_rails:
        lines.append(f"- Power rails: {len(intent.power_rails)}")
        for rail in intent.power_rails[:12]:
            lines.append(
                f"  {rail.name}: {rail.voltage_v}V / {rail.current_max_a}A"
                + (f" via {rail.source_ref}" if rail.source_ref else "")
            )
    if intent.interfaces:
        lines.append(f"- Interfaces: {len(intent.interfaces)}")
        for iface in intent.interfaces[:10]:
            impedance = (
                f"  {iface.impedance_target_ohm}ohm" + (" diff" if iface.differential else "")
                if iface.impedance_target_ohm is not None
                else ""
            )
            lines.append(f"  {iface.kind}{impedance}")
    if intent.compliance:
        lines.append("- Compliance: " + ", ".join(c.kind for c in intent.compliance))
    if intent.cost.unit_cost_usd_max is not None:
        lines.append(f"- Cost target: <${intent.cost.unit_cost_usd_max:.2f}/unit")
    if intent.mechanical.max_height_mm is not None:
        lines.append(f"- Max height: {intent.mechanical.max_height_mm:.1f} mm")
    lines.append(
        f"- Thermal: {intent.thermal.ambient_c}°C ambient, "
        f"max {intent.thermal.max_component_c}°C component"
    )
    return "\n".join(lines)


def _entry_center(entry: dict[str, Any]) -> tuple[float, float] | None:
    x_mm = entry.get("x_mm")
    y_mm = entry.get("y_mm")
    if x_mm is None or y_mm is None:
        return None
    return float(x_mm), float(y_mm)


def _distance_mm(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_center = _entry_center(left)
    right_center = _entry_center(right)
    if left_center is None or right_center is None:
        return math.inf
    return math.hypot(left_center[0] - right_center[0], left_center[1] - right_center[1])


def _critical_nets_from_entries(entries: dict[str, dict[str, Any]]) -> list[str]:
    priority_tokens = ("USB", "CLK", "ETH", "PCIE", "HDMI", "RF", "ANT", "DDR")
    critical: set[str] = set()
    for entry in entries.values():
        for net_name in entry.get("net_names", []):
            candidate = str(net_name).strip()
            if candidate and any(token in candidate.upper() for token in priority_tokens):
                critical.add(candidate)
    return sorted(critical)


def _component_category(reference: str, entry: dict[str, Any]) -> str:
    footprint_name = str(entry.get("name", "")).strip()
    value_name = str(entry.get("value", "")).strip()
    contract = find_component_contract(footprint=footprint_name)
    if contract is not None:
        category = contract.category
        if category in {"mcu", "mcu_module"}:
            return "mcu"
        if category == "sensor":
            return "sensor"
        if category == "connector":
            return "connector"
        if category == "regulator":
            return "regulator"
        if category == "analog":
            return "analog"
        if category in {"memory", "interface"}:
            return "digital"

    upper_ref = reference.upper()
    upper_name = footprint_name.upper()
    upper_value = value_name.upper()
    if upper_ref.startswith("J") or "CONNECTOR" in upper_name or "USB" in upper_name:
        return "connector"
    if upper_ref.startswith("C") or "CAPACITOR" in upper_name:
        return "capacitor"
    if "SENSOR" in upper_name or "SENSOR" in upper_value:
        return "sensor"
    if any(token in upper_name for token in ("BME280", "ADXL", "MPU6050", "LIS3DH")):
        return "sensor"
    if any(token in upper_name for token in ("ESP32", "RP2040", "STM32", "NRF")):
        return "mcu"
    if "MCU" in upper_value:
        return "mcu"
    if "REGULATOR" in upper_name or "BUCK" in upper_value or "LDO" in upper_value:
        return "regulator"
    if upper_ref.startswith("U") and any(
        token in upper_name
        for token in ("QFP", "QFN", "BGA", "SOIC", "DFN", "LGA", "MODULE", "DIP")
    ):
        return "ic"
    return ""


def _infer_design_intent_from_board() -> tuple[ProjectDesignIntent, list[str]]:
    from .board_file import _normalize_board_content, _parse_board_footprint_blocks

    cfg = get_config()
    if cfg.pcb_file is None or not cfg.pcb_file.exists():
        return ProjectDesignIntent(), ["No PCB file was available for design-spec inference."]

    try:
        content = _normalize_board_content(
            cfg.pcb_file.read_text(encoding="utf-8", errors="ignore")
        )
    except OSError as exc:
        return ProjectDesignIntent(), [f"PCB file could not be read for inference ({exc})."]

    footprints = _parse_board_footprint_blocks(content)
    if not footprints:
        return (
            ProjectDesignIntent(),
            ["No PCB footprints were available for design-spec inference."],
        )

    categories = {
        reference: _component_category(reference, entry) for reference, entry in footprints.items()
    }
    connector_refs = sorted(
        reference for reference, category in categories.items() if category == "connector"
    )
    sensor_cluster_refs = sorted(
        reference for reference, category in categories.items() if category == "sensor"
    )
    analog_refs = sorted(
        reference for reference, category in categories.items() if category == "analog"
    )
    digital_refs = sorted(
        reference for reference, category in categories.items() if category in {"digital", "mcu"}
    )
    power_tree_refs = sorted(
        (
            reference
            for reference, category in categories.items()
            if category in {"connector", "regulator", "mcu"}
        ),
        key=lambda reference: (
            float(footprints[reference].get("x_mm", 0.0) or 0.0),
            reference,
        ),
    )

    capacitor_refs = [
        reference for reference, category in categories.items() if category == "capacitor"
    ]
    ic_candidates = [
        reference
        for reference, category in categories.items()
        if category in {"analog", "digital", "ic", "mcu", "regulator", "sensor"}
        or reference.upper().startswith("U")
    ]
    decoupling_pairs: list[dict[str, Any]] = []
    for reference in sorted(ic_candidates):
        if not capacitor_refs:
            continue
        nearest_caps = sorted(
            capacitor_refs,
            key=lambda capacitor_ref: _distance_mm(
                footprints[reference], footprints[capacitor_ref]
            ),
        )[:1]
        if nearest_caps:
            decoupling_pairs.append(
                {
                    "ic_ref": reference,
                    "cap_refs": nearest_caps,
                    "max_distance_mm": DEFAULT_INFERRED_DECOUPLING_DISTANCE_MM,
                }
            )

    notes = [
        f"Inferred {len(connector_refs)} connector refs from PCB footprints.",
        f"Inferred {len(decoupling_pairs)} decoupling pair candidates from PCB placement.",
        f"Inferred {len(sensor_cluster_refs)} sensor refs from PCB footprints.",
        f"Inferred {len(power_tree_refs)} power-tree refs from PCB placement order.",
    ]
    return (
        _normalize_design_intent(
            ProjectDesignIntent(
                connector_refs=connector_refs,
                decoupling_pairs=decoupling_pairs,
                critical_nets=_critical_nets_from_entries(footprints),
                power_tree_refs=power_tree_refs,
                analog_refs=analog_refs,
                digital_refs=digital_refs,
                sensor_cluster_refs=sensor_cluster_refs,
            )
        ),
        notes,
    )


def _merge_design_intent(
    explicit: ProjectDesignIntent,
    inferred: ProjectDesignIntent,
) -> ProjectDesignIntent:
    return _normalize_design_intent(
        ProjectDesignIntent(
            # v1 — explicit wins, fall back to inferred
            connector_refs=explicit.connector_refs or inferred.connector_refs,
            decoupling_pairs=explicit.decoupling_pairs or inferred.decoupling_pairs,
            critical_nets=explicit.critical_nets or inferred.critical_nets,
            power_tree_refs=explicit.power_tree_refs or inferred.power_tree_refs,
            analog_refs=explicit.analog_refs or inferred.analog_refs,
            digital_refs=explicit.digital_refs or inferred.digital_refs,
            sensor_cluster_refs=explicit.sensor_cluster_refs or inferred.sensor_cluster_refs,
            required_sheets=explicit.required_sheets,
            optional_sheets=explicit.optional_sheets,
            rf_keepout_regions=explicit.rf_keepout_regions or inferred.rf_keepout_regions,
            manufacturer=explicit.manufacturer or inferred.manufacturer,
            manufacturer_tier=explicit.manufacturer_tier or inferred.manufacturer_tier,
            functional_spacing_mm=explicit.functional_spacing_mm,
            thermal_hotspots=explicit.thermal_hotspots,
            critical_frequencies_mhz=explicit.critical_frequencies_mhz,
            # v2 — explicit only (inference does not produce these)
            power_rails=explicit.power_rails,
            interfaces=explicit.interfaces,
            mechanical=explicit.mechanical,
            compliance=explicit.compliance,
            cost=explicit.cost,
            thermal=explicit.thermal,
        )
    )


def resolve_design_intent() -> ProjectSpecResolution:
    """Resolve the saved and inferred design spec into a single view."""
    explicit, path, source, notes = _load_saved_design_intent()
    inferred, inference_notes = _infer_design_intent_from_board()
    resolved = _merge_design_intent(explicit, inferred)
    return ProjectSpecResolution(
        source=source,
        path=str(path) if path is not None else "",
        explicit=explicit,
        inferred=inferred,
        resolved=resolved,
        notes=[*notes, *inference_notes],
    )


set_design_intent_resolver(resolve_design_intent)


def validate_design_intent(intent: ProjectDesignIntent | None = None) -> list[str]:
    """Validate explicit or resolved design-spec references against the active board."""
    from .board_file import _normalize_board_content, _parse_board_footprint_blocks

    cfg = get_config()
    if cfg.pcb_file is None or not cfg.pcb_file.exists():
        return []

    try:
        board_text = _normalize_board_content(
            cfg.pcb_file.read_text(encoding="utf-8", errors="ignore")
        )
    except OSError as exc:
        return [f"PCB file could not be read while validating the design spec ({exc})."]

    references = set(_parse_board_footprint_blocks(board_text))
    candidate = intent or resolve_design_intent().resolved
    issues: list[str] = []
    for reference in candidate.connector_refs:
        if reference not in references:
            issues.append(f"Connector ref '{reference}' is not present on the PCB.")
    for reference in candidate.power_tree_refs:
        if reference not in references:
            issues.append(f"Power-tree ref '{reference}' is not present on the PCB.")
    for reference in candidate.analog_refs:
        if reference not in references:
            issues.append(f"Analog ref '{reference}' is not present on the PCB.")
    for reference in candidate.digital_refs:
        if reference not in references:
            issues.append(f"Digital ref '{reference}' is not present on the PCB.")
    for reference in candidate.sensor_cluster_refs:
        if reference not in references:
            issues.append(f"Sensor-cluster ref '{reference}' is not present on the PCB.")
    for pair in candidate.decoupling_pairs:
        if pair.ic_ref not in references:
            issues.append(f"Decoupling IC ref '{pair.ic_ref}' is not present on the PCB.")
        for reference in pair.cap_refs:
            if reference not in references:
                issues.append(f"Decoupling capacitor ref '{reference}' is not present on the PCB.")
    return issues


def _render_project_spec_resolution(resolution: ProjectSpecResolution) -> str:
    source_label = {
        "project_spec": ".kicad-mcp/project_spec.json",
        "legacy_design_intent": "legacy output/design_intent.json",
        "none": "(none)",
    }[resolution.source]
    lines = ["Project design spec resolution:"]
    lines.append(f"- Explicit source: {source_label}")
    lines.append(f"- Explicit path: {resolution.path or '(none)'}")
    if resolution.source == "none":
        lines.append(
            "- Warning: No design intent set. Call project_set_design_intent() "
            "to unlock full scoring."
        )
    lines.append(
        f"- Inferred connectors / decoupling / sensors: "
        f"{len(resolution.inferred.connector_refs)} / "
        f"{len(resolution.inferred.decoupling_pairs)} / "
        f"{len(resolution.inferred.sensor_cluster_refs)}"
    )
    for note in resolution.notes[:8]:
        lines.append(f"- Note: {note}")
    lines.append("")
    lines.append(_render_design_intent(resolution.resolved))
    return "\n".join(lines)


def _queue_reason_from_details(details: list[str], summary: str) -> str:
    for detail in details:
        cleaned = detail.strip()
        if cleaned.startswith("FAIL: "):
            return cleaned[6:]
        if cleaned.startswith("WARN: "):
            return cleaned[6:]
        if cleaned.startswith("BLOCKED: "):
            return cleaned[9:]
    return summary


def _suggested_tool_for_gate(name: str) -> str:
    return {
        "Schematic": "run_erc()",
        "Schematic connectivity": "schematic_connectivity_gate()",
        "PCB": "run_drc()",
        "Placement": "pcb_score_placement()",
        "PCB transfer": "pcb_transfer_quality_gate()",
        "Manufacturing": "manufacturing_quality_gate()",
        "Footprint parity": "validate_footprints_vs_schematic()",
    }.get(name, "project_quality_gate()")


def _tool_name_from_hint(tool_hint: str) -> str:
    return tool_hint.removesuffix("()")


def _next_action_finding(
    *,
    status: str,
    gate: str,
    reason: str,
    suggested_tool: str,
) -> Finding:
    severity = "warning" if status == "EMPTY" else "error"
    return Finding(
        id=stable_finding_id("project_next_action", gate or "project", status, reason),
        severity=severity,
        location=gate or "Project",
        description=reason,
        suggested_fix=SuggestedFix(tool=_tool_name_from_hint(suggested_tool), args={}),
    )


def _next_action_payload() -> ProjectNextActionPayload:
    from .validation import _evaluate_project_gate

    try:
        outcomes = _evaluate_project_gate()
    except Exception as exc:
        reason = f"Project quality gate could not be evaluated: {exc}"
        lines = [
            "Project next action:",
            "- Status: BLOCKED",
            "- Suggested tool: kicad_get_project_info()",
            f"- Reason: {reason}",
        ]
        return ProjectNextActionPayload(
            text="\n".join(lines),
            status="BLOCKED",
            verdict="FAIL",
            reason=reason,
            suggested_tool="kicad_get_project_info()",
            findings=[
                _next_action_finding(
                    status="BLOCKED",
                    gate="Project",
                    reason=reason,
                    suggested_tool="kicad_get_project_info()",
                )
            ],
            next_action="kicad_get_project_info()",
        )
    actionable = [outcome for outcome in outcomes if outcome.status != "PASS"]
    if not actionable:
        lines = [
            "Project next action:",
            "- Status: PASS",
            "- Suggested tool: export_manufacturing_package()",
            "- Reason: No blocking issues remain.",
        ]
        return ProjectNextActionPayload(
            text="\n".join(lines),
            status="PASS",
            verdict="PASS",
            reason="No blocking issues remain.",
            suggested_tool="export_manufacturing_package()",
            next_action="export_manufacturing_package()",
        )

    actionable.sort(key=lambda outcome: (0 if outcome.status == "BLOCKED" else 1, outcome.name))
    target = actionable[0]
    reason = _queue_reason_from_details(target.details, target.summary)
    suggested_tool = _suggested_tool_for_gate(target.name)
    lines = [
        "Project next action:",
        f"- Status: {target.status}",
        f"- Gate: {target.name}",
        f"- Suggested tool: {suggested_tool}",
        f"- Reason: {reason}",
    ]
    return ProjectNextActionPayload(
        text="\n".join(lines),
        status=target.status,
        verdict="WARN" if target.status == "EMPTY" else "FAIL",
        gate=target.name,
        reason=reason,
        suggested_tool=suggested_tool,
        findings=[
            _next_action_finding(
                status=target.status,
                gate=target.name,
                reason=reason,
                suggested_tool=suggested_tool,
            )
        ],
        next_action=suggested_tool,
    )


def register(mcp: FastMCP) -> None:
    """Register project management tools."""

    context_service = ProjectContextService(
        scan_project_dir=scan_project_dir,
        apply_project=lambda project_dir, **kwargs: get_config().apply_project(
            project_dir, **kwargs
        ),
        clear_cache=clear_ttl_cache,
        reset_connection=reset_connection,
        render_project_info=_render_project_info,
    )
    project_context.register(
        mcp,
        project_context.ProjectContextDependencies(service=context_service),
    )

    @mcp.tool()
    @headless_compatible
    def project_design_workflow(completed_phases: list[str] | None = None) -> str:
        """Return the professional PCB design workflow as a typed phase state machine.

        Lays out the canonical Planner -> Builder -> Verifier -> Fixer -> Release
        sequence, with the high-level tool and the quality gates each phase must pass.
        Pass the phases already finished in ``completed_phases``; the tool marks them
        COMPLETE, reports the first remaining phase as READY (the current step) with
        its next action and gates, and flags when a human gate is required. Read-only
        and headless — use it to drive an autonomous design run step by step.
        """
        state = _build_design_workflow(completed_phases or [])
        return _render_design_workflow(state)

    @mcp.tool()
    @headless_compatible
    def project_set_design_intent(
        connector_refs: list[str] | None = None,
        decoupling_pairs: list[dict[str, Any]] | None = None,
        critical_nets: list[str] | None = None,
        power_tree_refs: list[str] | None = None,
        analog_refs: list[str] | None = None,
        digital_refs: list[str] | None = None,
        sensor_cluster_refs: list[str] | None = None,
        required_sheets: list[str] | None = None,
        optional_sheets: list[str] | None = None,
        rf_keepout_regions: list[dict[str, Any]] | None = None,
        manufacturer: str | None = None,
        manufacturer_tier: str | None = None,
        functional_spacing_mm: float | None = None,
        thermal_hotspots: list[str] | None = None,
        critical_frequencies_mhz: list[float] | None = None,
        # v2 parameters
        power_rails: list[dict[str, Any]] | None = None,
        interfaces: list[dict[str, Any]] | None = None,
        mechanical: dict[str, Any] | None = None,
        compliance: list[dict[str, Any]] | None = None,
        cost: dict[str, Any] | None = None,
        thermal: dict[str, Any] | None = None,
    ) -> str:
        """Call this FIRST to store design intent for placement, routing, and gates.

        v1 parameters (all boards): connector_refs, decoupling_pairs, critical_nets,
        power_tree_refs, analog_refs, digital_refs, sensor_cluster_refs, required_sheets,
        optional_sheets, rf_keepout_regions, manufacturer, manufacturer_tier.

        v2 parameters (professional projects): power_rails (list of PowerRailSpec dicts),
        interfaces (list of InterfaceSpec dicts), mechanical (MechanicalConstraint dict),
        compliance (list of ComplianceTarget dicts), cost (CostTarget dict),
        thermal (ThermalEnvelope dict).
        """
        existing = load_design_intent()
        updated = ProjectDesignIntent(
            connector_refs=existing.connector_refs if connector_refs is None else connector_refs,
            decoupling_pairs=(
                existing.decoupling_pairs if decoupling_pairs is None else decoupling_pairs
            ),
            critical_nets=existing.critical_nets if critical_nets is None else critical_nets,
            power_tree_refs=(
                existing.power_tree_refs if power_tree_refs is None else power_tree_refs
            ),
            analog_refs=existing.analog_refs if analog_refs is None else analog_refs,
            digital_refs=existing.digital_refs if digital_refs is None else digital_refs,
            sensor_cluster_refs=(
                existing.sensor_cluster_refs if sensor_cluster_refs is None else sensor_cluster_refs
            ),
            required_sheets=(
                existing.required_sheets if required_sheets is None else required_sheets
            ),
            optional_sheets=(
                existing.optional_sheets if optional_sheets is None else optional_sheets
            ),
            rf_keepout_regions=(
                existing.rf_keepout_regions if rf_keepout_regions is None else rf_keepout_regions
            ),
            manufacturer=existing.manufacturer if manufacturer is None else manufacturer,
            manufacturer_tier=(
                existing.manufacturer_tier if manufacturer_tier is None else manufacturer_tier
            ),
            functional_spacing_mm=(
                existing.functional_spacing_mm
                if functional_spacing_mm is None
                else functional_spacing_mm
            ),
            thermal_hotspots=(
                existing.thermal_hotspots if thermal_hotspots is None else thermal_hotspots
            ),
            critical_frequencies_mhz=(
                existing.critical_frequencies_mhz
                if critical_frequencies_mhz is None
                else critical_frequencies_mhz
            ),
            # v2 fields
            power_rails=(
                existing.power_rails
                if power_rails is None
                else [PowerRailSpec.model_validate(r) for r in power_rails]
            ),
            interfaces=(
                existing.interfaces
                if interfaces is None
                else [InterfaceSpec.model_validate(i) for i in interfaces]
            ),
            mechanical=(
                existing.mechanical
                if mechanical is None
                else MechanicalConstraint.model_validate(mechanical)
            ),
            compliance=(
                existing.compliance
                if compliance is None
                else [ComplianceTarget.model_validate(c) for c in compliance]
            ),
            cost=(existing.cost if cost is None else CostTarget.model_validate(cost)),
            thermal=(
                existing.thermal if thermal is None else ThermalEnvelope.model_validate(thermal)
            ),
        )
        path = save_design_intent(updated)
        return (
            f"Stored project design spec at {path}.\n"
            f"{_render_design_intent(_normalize_design_intent(updated))}"
        )

    @mcp.tool()
    @headless_compatible
    def project_import_design_spec(
        path: str | None = None,
        markdown: str | None = None,
        strict: bool = True,
        dry_run: bool = True,
    ) -> ProjectImportDesignSpecPayload:
        """Import structured product/spec text into ProjectDesignIntent conservatively.

        Accepts JSON or YAML frontmatter/fenced blocks. The importer only persists
        explicit supported ProjectDesignIntent fields; it reports missing mandatory
        decisions, placeholders, and extra fields such as MPN/LCSC/populate lists
        without inventing values. Use ``dry_run=True`` first, then re-run with
        ``dry_run=False`` after reviewing the parsed result.
        """
        return import_design_spec(
            path=path,
            markdown=markdown,
            strict=strict,
            dry_run=dry_run,
        )

    @mcp.tool()
    @headless_compatible
    @ttl_cache(ttl_seconds=2)
    def project_get_design_intent() -> str:
        """Show the persisted project design intent used by placement and release gates."""
        intent = load_design_intent()
        if intent == ProjectDesignIntent():
            return (
                "No explicit project design intent is stored yet.\n"
                "Use `project_get_design_spec()` to inspect the resolved "
                "explicit + inferred view.\n"
                f"{_render_design_intent(intent)}"
            )
        return _render_design_intent(intent)

    @mcp.tool()
    @headless_compatible
    def project_get_design_spec() -> ProjectSpecPayload:
        """Return the resolved project design spec with explicit and inferred fields."""
        resolution = resolve_design_intent()
        text = _render_project_spec_resolution(resolution)
        return ProjectSpecPayload(
            text=text,
            source=resolution.source,
            path=resolution.path,
            explicit=resolution.explicit,
            inferred=resolution.inferred,
            resolved=resolution.resolved,
            notes=resolution.notes,
        )

    @mcp.tool()
    @headless_compatible
    def project_infer_design_spec() -> ProjectSpecPayload:
        """Infer a design spec from the active PCB without writing it to disk."""
        inferred, notes = _infer_design_intent_from_board()
        resolution = ProjectSpecResolution(
            source="none",
            explicit=ProjectDesignIntent(),
            inferred=inferred,
            resolved=inferred,
            notes=notes,
        )
        return ProjectSpecPayload(
            text=_render_project_spec_resolution(resolution),
            source=resolution.source,
            path=resolution.path,
            explicit=resolution.explicit,
            inferred=resolution.inferred,
            resolved=resolution.resolved,
            notes=resolution.notes,
        )

    @mcp.tool()
    @headless_compatible
    def project_assess_edit_impact(baseline_spec_json: str = "") -> str:
        """Scope re-validation after an edit: semantic-diff the design intent and report
        which gates must re-run.

        Compares a baseline design spec — the declared/saved intent, or an explicit
        baseline passed as ``baseline_spec_json`` — against the intent inferred from the
        current board, then maps each change to the gates it can invalidate. Re-run only
        the impacted gates and keep the rest as already-proven. Use after editing an
        existing project so a small change does not force a full re-validation.
        """
        from .edit_impact import impact_of_changes, render_impact_report, semantic_intent_diff

        if baseline_spec_json.strip():
            try:
                baseline = json.loads(baseline_spec_json)
            except json.JSONDecodeError as exc:
                return f"Invalid baseline_spec_json: {exc}"
            if not isinstance(baseline, dict):
                return "baseline_spec_json must be a JSON object (a design spec)."
        else:
            baseline = load_design_intent().model_dump()

        try:
            inferred, _notes = _infer_design_intent_from_board()
        except KiCadConnectionError as exc:
            return f"Could not infer the current board intent: {exc}"
        changes = semantic_intent_diff(baseline, inferred.model_dump())
        report = impact_of_changes(changes)
        return render_impact_report(report)

    @mcp.tool()
    @headless_compatible
    def project_revalidate_after_edit(
        baseline_spec_json: str = "",
        manufacturer: str = "",
        tier: str = "",
    ) -> str:
        """Re-run only the gates an edit could have invalidated; prove the rest preserved.

        Computes the semantic intent diff (like ``project_assess_edit_impact``), then
        actually re-runs only the impacted project gates -- skipping unaffected ones -- so
        a small edit does not force a full re-validation. Impacted analysis categories that
        the sign-off gate does not cover (signal integrity, power, thermal, EMC) are listed
        with the tool to re-run for each.
        """
        from .edit_impact import impact_of_changes, semantic_intent_diff
        from .gates import _combined_status
        from .validation import (
            PROJECT_GATE_CATEGORIES,
            _evaluate_project_gate,
            _format_gate,
        )

        analysis_tools = {
            "signal_integrity": "si_calculate_trace_impedance / si_analyze_high_speed_channel",
            "power": "check_power_integrity / pdn_calculate_voltage_drop",
            "thermal": "thermal_simulate_plane_spreading / thermal_calculate_via_count",
            "emc": "emc_run_full_compliance",
        }

        if baseline_spec_json.strip():
            try:
                baseline = json.loads(baseline_spec_json)
            except json.JSONDecodeError as exc:
                return f"Invalid baseline_spec_json: {exc}"
            if not isinstance(baseline, dict):
                return "baseline_spec_json must be a JSON object (a design spec)."
        else:
            baseline = load_design_intent().model_dump()

        try:
            inferred, _notes = _infer_design_intent_from_board()
        except KiCadConnectionError as exc:
            return f"Could not infer the current board intent: {exc}"

        changes = semantic_intent_diff(baseline, inferred.model_dump())
        report = impact_of_changes(changes)
        affected = set(report.affected_gates)
        runnable = affected & set(PROJECT_GATE_CATEGORIES)
        analysis_affected = sorted(affected - set(PROJECT_GATE_CATEGORIES))
        preserved = sorted(set(PROJECT_GATE_CATEGORIES) - runnable)

        lines = [f"Selective re-validation after edit: {report.summary}", ""]
        if not changes:
            lines.append("No gates were re-run; every previously-passing gate is preserved.")
            return "\n".join(lines)

        if runnable:
            outcomes = _evaluate_project_gate(
                manufacturer=manufacturer or None,
                tier=tier or None,
                only_categories=runnable,
            )
            status = _combined_status(outcomes)
            lines.append(f"Re-ran impacted project gates ({', '.join(sorted(runnable))}): {status}")
            lines.extend(_format_gate(outcome) for outcome in outcomes)
        else:
            lines.append("No bundled project gate was impacted by this edit.")

        if analysis_affected:
            lines.append("")
            lines.append("Impacted analysis categories to re-run with their own tools:")
            for category in analysis_affected:
                lines.append(f"- {category}: {analysis_tools.get(category, '(analysis tool)')}")

        lines.append("")
        lines.append(f"Preserved project gates (not re-run): {', '.join(preserved) or '(none)'}")
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def project_validate_design_spec() -> ProjectSpecValidationPayload:
        """Validate the resolved design spec against the active project PCB."""
        issues = validate_design_intent()
        lines = ["Project design spec validation:"]
        lines.append(f"- Valid: {'yes' if not issues else 'no'}")
        if issues:
            lines.extend(f"- {issue}" for issue in issues[:20])
        else:
            lines.append("- No reference mismatches were found.")
        return ProjectSpecValidationPayload(
            text="\n".join(lines),
            valid=not issues,
            issues=issues,
        )

    @mcp.tool()
    @headless_compatible
    def project_generate_design_prompt(
        circuit_description: str = "",
        target_fab: str = "",
    ) -> str:
        """Generate a professional workflow prompt tailored to the resolved project spec."""
        resolution = resolve_design_intent()
        intent = resolution.resolved
        mechanical = intent.mechanical
        board_size = (
            f"{mechanical.board_width_mm:g}x{mechanical.board_height_mm:g}"
            if mechanical.board_width_mm is not None and mechanical.board_height_mm is not None
            else "100x80"
        )
        fab = target_fab.strip()
        if not fab:
            manufacturer = (intent.manufacturer or "jlcpcb").strip().lower()
            tier = (intent.manufacturer_tier or "standard").strip().lower()
            fab = f"{manufacturer}_{tier}"
        notes = [
            "- Critical nets: "
            + (", ".join(intent.critical_nets) if intent.critical_nets else "(none)"),
            "- Power rails: "
            + (
                ", ".join(
                    f"{rail.name} {rail.voltage_v:g}V/{rail.current_max_a:g}A"
                    for rail in intent.power_rails
                )
                if intent.power_rails
                else "(none)"
            ),
            "- Interfaces: "
            + (
                ", ".join(
                    f"{iface.kind}"
                    + (
                        f" {iface.impedance_target_ohm:g}ohm"
                        if iface.impedance_target_ohm is not None
                        else ""
                    )
                    for iface in intent.interfaces
                )
                if intent.interfaces
                else "(none)"
            ),
            "- Thermal hotspots: "
            + (", ".join(intent.thermal_hotspots) if intent.thermal_hotspots else "(none)"),
        ]
        return render_professional_circuit_design_prompt(
            circuit_description=circuit_description or "KiCad project",
            board_size_mm=board_size,
            layer_count="2",
            target_fab=fab,
            design_notes="\n".join(notes),
        )

    @mcp.tool()
    @headless_compatible
    def project_get_next_action() -> ProjectNextActionPayload:
        """Return the next high-priority action derived from the current project gate."""
        return _next_action_payload()

    @mcp.tool()
    @headless_compatible
    async def project_auto_fix_loop(
        max_iterations: int = 5,
        ctx: Context[Any, Any, Any] | None = None,
    ) -> AutoFixLoopPayload:
        """Run the project quality gate and automatically apply server-side fixes.

        Each iteration:
        1. Evaluates all project quality gates.
        2. For **auto-applicable** gates (annotation, zone refill) — calls the
           underlying fix implementation directly on the server, then re-evaluates.
        3. For gates requiring **agent action** — returns the tool name and
           description so the agent can call it, then the agent must call this
           tool again to continue.

        The loop runs up to ``max_iterations`` times applying auto-fixes.  It
        stops early when all gates pass or when no further auto-fix is possible
        without agent involvement.

        Args:
            max_iterations: Maximum number of auto-fix + re-evaluate cycles to
                attempt before returning control to the agent (1–20).
        """
        import importlib

        from .gates import GateOutcome, _combined_status
        from .validation import _evaluate_project_gate

        max_iterations = max(1, min(max_iterations, 20))
        iterations_used = 0
        auto_fix_log: list[str] = []

        # ------------------------------------------------------------------ #
        # Helper: resolve a "tools.module:function" import string to callable  #
        # ------------------------------------------------------------------ #
        def _resolve_callable(import_str: str) -> Callable[[], object] | None:
            if not import_str:
                return None
            try:
                mod_path, func_name = import_str.rsplit(":", 1)
                full_mod = f"kicad_mcp.{mod_path}"
                mod = importlib.import_module(full_mod)
                candidate = getattr(mod, func_name, None)
                return candidate if callable(candidate) else None
            except Exception:
                return None

        async def _sample_guidance(outcome: GateOutcome) -> str:
            if ctx is None:
                return ""
            sample = getattr(ctx, "sample", None)
            if not callable(sample):
                return ""
            try:
                result = await sample(
                    messages=[
                        {
                            "role": "user",
                            "content": sampling_prompt_for_gate(
                                outcome.name,
                                outcome.summary,
                                outcome.details,
                            ),
                        }
                    ],
                    max_tokens=256,
                    system_prompt="You are a KiCad expert. Reply briefly and directly.",
                )
            except Exception:
                return ""

            content = getattr(result, "content", None)
            if isinstance(content, list) and content:
                return str(getattr(content[0], "text", "") or "")
            return ""

        async def _report_progress(progress: float, total: float, message: str) -> None:
            if ctx is None:
                return
            try:
                await ctx.report_progress(progress, total, message)
            except ValueError:
                return

        await _report_progress(0, 100, "Project quality gate is being evaluated...")

        outcomes = _evaluate_project_gate()
        iterations_used += 1

        for _iter in range(max_iterations - 1):  # -1 because we already ran once above
            # Find the first failing gate that has an auto-applicable fixer
            applied_any = False
            for outcome in outcomes:
                if outcome.status == "PASS":
                    continue
                fixers = fixers_for_gate(outcome.name)
                auto_fixer = next((f for f in fixers if f.auto_applicable), None)
                if auto_fixer is None:
                    continue
                fn = _resolve_callable(auto_fixer.callable_import)
                if fn is None:
                    continue
                try:
                    fix_result = fn()
                    auto_fix_log.append(
                        f"[iter {iterations_used}] Auto-fixed '{outcome.name}' "
                        f"via {auto_fixer.tool}: {fix_result}"
                    )
                    applied_any = True
                except Exception as exc:
                    auto_fix_log.append(
                        f"[iter {iterations_used}] Auto-fix '{auto_fixer.tool}' "
                        f"for '{outcome.name}' raised: {exc}"
                    )

            if not applied_any:
                break  # Nothing left for the server to do — hand off to agent

            # Re-evaluate after applying fixes
            progress = min(90, 10 + (iterations_used * 15))
            await _report_progress(
                progress,
                100,
                f"Re-evaluating quality gates after iteration {iterations_used}...",
            )
            outcomes = _evaluate_project_gate()
            iterations_used += 1

            if all(o.status == "PASS" for o in outcomes):
                break  # All gates green — done

        # ------------------------------------------------------------------ #
        # Build the final action list for the agent                           #
        # ------------------------------------------------------------------ #
        actions: list[AutoFixAction] = []
        for outcome in outcomes:
            if outcome.status == "PASS":
                continue
            fixers = fixers_for_gate(outcome.name)
            auto_fixer = next((f for f in fixers if f.auto_applicable), None)
            agent_fixer = next((f for f in fixers if not f.auto_applicable), None)
            sampling_guidance = await _sample_guidance(outcome)
            actions.append(
                AutoFixAction(
                    gate=outcome.name,
                    status=outcome.status,
                    auto_fixed=False,
                    auto_fix_description=(auto_fixer.description if auto_fixer is not None else ""),
                    agent_tool=(
                        (agent_fixer.tool if agent_fixer is not None else "")
                        or (auto_fixer.tool if auto_fixer is not None else "")
                    ),
                    agent_description=(
                        (agent_fixer.description if agent_fixer is not None else "")
                        or (auto_fixer.description if auto_fixer is not None else "")
                    ),
                    sampling_guidance=sampling_guidance,
                )
            )

        remaining = sum(1 for a in actions if not a.auto_fixed)
        ready = len(actions) == 0

        lines = [f"project_auto_fix_loop: {iterations_used}/{max_iterations} iteration(s) used."]
        if auto_fix_log:
            lines.append("Server-side auto-fixes applied:")
            lines.extend(f"  {entry}" for entry in auto_fix_log)
        if ready:
            lines.append("Status: PASS — all gates pass. Ready for manufacturing release.")
        else:
            lines.append(
                f"Status: {len(actions)} gate(s) still failing ({remaining} require agent action)."
            )
            for action in actions:
                lines.append(
                    f"  [AGENT] {action.gate}: call {action.agent_tool}() "
                    f"— {action.agent_description}"
                )
                if action.sampling_guidance:
                    lines.append(f"    Sampling guidance: {action.sampling_guidance}")
            lines.append("After applying the recommended tool, call project_auto_fix_loop() again.")

        combined = _combined_status(
            [
                GateOutcome(
                    name=o.name,
                    status=o.status,
                    summary=o.summary,
                    details=o.details,
                )
                for o in outcomes
            ]
        )

        await _report_progress(100, 100, "Project auto-fix loop completed.")

        return AutoFixLoopPayload(
            text="\n".join(lines),
            gate_status=combined,
            iterations_used=iterations_used,
            actions=actions,
            remaining_issues=remaining,
            ready_for_release=ready,
        )

    @mcp.tool()
    @headless_compatible
    def project_full_validation_loop(
        max_iterations: int = 5,
        fix_tier: Literal["auto_only", "suggest"] = "auto_only",
    ) -> AutoFixLoopPayload:
        """Run ERC/DRC/project gates in a bounded fix-and-rerun validation loop."""
        import importlib

        from .gates import GateOutcome, _combined_status
        from .validation import _evaluate_project_gate

        max_iterations = max(1, min(max_iterations, 20))
        outcomes = _evaluate_project_gate()
        fix_log: list[str] = []
        iterations_used = 1

        def _resolve_callable(import_str: str) -> Callable[[], object] | None:
            if not import_str:
                return None
            try:
                mod_path, func_name = import_str.rsplit(":", 1)
                module = importlib.import_module(f"kicad_mcp.{mod_path}")
                candidate = getattr(module, func_name, None)
                return candidate if callable(candidate) else None
            except Exception:
                return None

        while iterations_used < max_iterations:
            if all(outcome.status == "PASS" for outcome in outcomes):
                break
            blocker = next((outcome for outcome in outcomes if outcome.status != "PASS"), None)
            if blocker is None:
                break
            fixers = fixers_for_gate(blocker.name)
            auto_fixer = next((fixer for fixer in fixers if fixer.auto_applicable), None)
            if auto_fixer is None or fix_tier == "suggest":
                break
            fn = _resolve_callable(auto_fixer.callable_import)
            if fn is None:
                break
            try:
                fix_result = fn()
                fix_log.append(
                    f"[iter {iterations_used}] {blocker.name}: {auto_fixer.tool} -> {fix_result}"
                )
            except Exception as exc:
                fix_log.append(
                    f"[iter {iterations_used}] {blocker.name}: {auto_fixer.tool} raised {exc}"
                )
                break
            outcomes = _evaluate_project_gate()
            iterations_used += 1

        actions: list[AutoFixAction] = []
        for outcome in outcomes:
            if outcome.status == "PASS":
                continue
            fixers = fixers_for_gate(outcome.name)
            agent_fixer = next((fixer for fixer in fixers if not fixer.auto_applicable), None)
            auto_fixer = next((fixer for fixer in fixers if fixer.auto_applicable), None)
            chosen = agent_fixer or auto_fixer
            actions.append(
                AutoFixAction(
                    gate=outcome.name,
                    status=outcome.status,
                    auto_fixed=False,
                    auto_fix_description=auto_fixer.description if auto_fixer else "",
                    agent_tool=chosen.tool if chosen else "project_quality_gate",
                    agent_description=chosen.description if chosen else outcome.summary,
                )
            )

        combined = _combined_status(
            [
                GateOutcome(
                    name=outcome.name,
                    status=outcome.status,
                    summary=outcome.summary,
                    details=outcome.details,
                )
                for outcome in outcomes
            ]
        )
        lines = [
            f"project_full_validation_loop: {iterations_used}/{max_iterations} iteration(s) used.",
        ]
        if fix_log:
            lines.append("Auto-fixes applied:")
            lines.extend(f"  {entry}" for entry in fix_log)
        if not actions:
            lines.append("PASS after validation loop.")
        elif fix_tier == "suggest":
            lines.append("Suggested fixes:")
            lines.extend(
                f"  [SUGGEST] {action.gate}: call {action.agent_tool}() "
                f"- {action.agent_description}"
                for action in actions
            )
        else:
            lines.append("PARTIAL: remaining issues require agent or manual action.")
            lines.extend(
                f"  [REMAINING] {action.gate}: call {action.agent_tool}() "
                f"- {action.agent_description}"
                for action in actions
            )
        return AutoFixLoopPayload(
            text="\n".join(lines),
            gate_status=combined,
            iterations_used=iterations_used,
            actions=actions,
            remaining_issues=len(actions),
            ready_for_release=not actions,
        )

    @mcp.tool()
    @headless_compatible
    def project_gate_trend(gate_name: str, last_n: int = 10) -> str:
        """Return persisted quality-gate trend history for one gate."""
        from ..resources.gate_history import GateHistory

        history = GateHistory.for_active_project()
        payload = {
            "gate_name": gate_name,
            "history": history.trend(gate_name, max(1, min(last_n, 100))),
            "regressions": history.regression_check(),
        }
        return json.dumps(payload, indent=2, sort_keys=True)

    @mcp.tool()
    @headless_compatible
    def project_design_report() -> DesignReportPayload:
        """Generate a comprehensive design-status report.

        Combines intent summary, v2 spec richness, project gate evaluation, and
        a prioritised list of next steps into a single structured report.
        This is the recommended first call after opening a project to understand
        its current state.
        """
        from .gates import GateOutcome, _combined_status
        from .validation import _evaluate_project_gate

        resolution = resolve_design_intent()
        intent = resolution.resolved

        outcomes = _evaluate_project_gate()
        combined = _combined_status(
            [
                GateOutcome(
                    name=o.name,
                    status=o.status,
                    summary=o.summary,
                    details=o.details,
                )
                for o in outcomes
            ]
        )
        failing = [o for o in outcomes if o.status != "PASS"]

        lines = [
            "# Project Design Report",
            "",
            "## Design Intent",
            _render_design_intent(intent),
            "",
            f"## Gate Status: {combined}",
        ]
        if failing:
            lines.append(f"Failing gates ({len(failing)}):")
            for outcome in failing:
                fixers = fixers_for_gate(outcome.name)
                hint = fixers[0].tool if fixers else "project_quality_gate"
                lines.append(f"- [{outcome.status}] {outcome.name}: {outcome.summary}")
                lines.append(f"  -> Suggested: {hint}()")
        else:
            lines.append("All gates PASS — ready for export_manufacturing_package().")

        lines += [
            "",
            "## Resolution Notes",
            *[f"- {n}" for n in resolution.notes[:8]],
        ]

        next_tool = failing[0].name if failing else "export_manufacturing_package"
        if failing:
            fixers = fixers_for_gate(failing[0].name)
            next_tool = fixers[0].tool if fixers else "project_quality_gate"

        return DesignReportPayload(
            text="\n".join(lines),
            gate_status=combined,
            intent_source=resolution.source,
            power_rails_count=len(intent.power_rails),
            interfaces_count=len(intent.interfaces),
            compliance_count=len(intent.compliance),
            has_mechanical_constraint=(
                bool(intent.mechanical.mount_holes)
                or bool(intent.mechanical.connector_placement)
                or intent.mechanical.max_height_mm is not None
            ),
            next_tool=next_tool,
        )

    discovery_service = ProjectDiscoveryService(
        find_recent_projects=find_recent_projects,
        scan_project_dir=scan_project_dir,
    )
    project_discovery.register(
        mcp,
        project_discovery.ProjectDiscoveryDependencies(service=discovery_service),
    )

    creation_service = ProjectCreationService(
        get_config=lambda: get_config(),
        assert_within=lambda root, candidate: assert_within(root, candidate),
        new_project_files=lambda project_dir, name: _new_project_files(project_dir, name),
        new_project_payload=lambda kicad_cli, project_file: _new_project_payload(
            kicad_cli, project_file
        ),
        upgrade_file=lambda path, kind, allowed_root: upgrade_generated_file(
            path, kind, _run_cli, allowed_root=allowed_root
        ),
        reset_connection=lambda: reset_connection(),
    )
    project_creation.register(
        mcp,
        project_creation.ProjectCreationDependencies(service=creation_service),
    )

    @mcp.tool()
    @headless_compatible
    def kicad_get_version() -> str:
        """Get KiCad version information and current connection status."""
        cfg = get_config()
        lines = [f"# KiCad MCP Pro Server v{__version__}", f"CLI path: {cfg.kicad_cli}"]

        cli_version = find_kicad_version(cfg.kicad_cli)
        lines.append(f"CLI version: {cli_version or 'unavailable'}")

        try:
            from kipy.proto.common.types.base_types_pb2 import DocumentType

            kicad = get_kicad()
            lines.append(f"IPC version: {kicad.get_version()}")

            try:
                pcb_docs = kicad.get_open_documents(DocumentType.DOCTYPE_PCB)
                lines.append(f"Open PCB documents: {len(pcb_docs)}")
            except Exception:
                lines.append("Open PCB documents: unavailable")

            try:
                sch_docs = kicad.get_open_documents(DocumentType.DOCTYPE_SCHEMATIC)
                lines.append(f"Open schematic documents: {len(sch_docs)}")
            except Exception:
                lines.append("Open schematic documents: unavailable")

        except KiCadConnectionError as exc:
            lines.append(f"IPC connection: unavailable ({exc})")
        except Exception as exc:
            logger.debug("kicad_version_ipc_probe_failed", error=str(exc))
            lines.append("IPC connection: unavailable")

        lines.append("")
        lines.append("Use `kicad_set_project()` to configure an active project.")
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def kicad_help() -> str:
        """Show a concise startup guide and all tool categories."""
        lines = [
            "# KiCad MCP Pro Quick Start",
            "",
            "1. Call `kicad_get_version()` to verify the runtime.",
            "2. Call `kicad_set_project()` or `kicad_create_new_project()`.",
            "3. Inspect `kicad://project/info` and `kicad://board/summary`.",
            "4. Call `kicad_list_tool_categories()` to discover the right tool family.",
            "",
            "Available categories:",
        ]
        for category, info in TOOL_CATEGORIES.items():
            lines.append(f"- `{category}`: {info['description']}")
        lines.append("")
        lines.append("Profiles:")
        lines.extend(f"- `{profile}`" for profile in available_profiles())
        return "\n".join(lines)
