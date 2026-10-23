"""Validation and design-check tools."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from mcp.server.mcpserver import MCPServer as FastMCP
from pydantic import BaseModel, Field

from .. import __version__
from ..config import get_config
from ..discovery import get_cli_capabilities
from ..models.component_contracts import find_component_contract
from ..models.verdict import Finding, SuggestedFix, Verdict, VerdictReport, stable_finding_id
from ..path_safety import resolve_under
from ..project.connector_mating_review import evaluate_connector_mating
from ..project.release_evidence_store import (
    ProjectReleaseEvidenceResolution,
    resolve_project_release_evidence,
)
from ..utils.dru import (
    SExprNode,
    delete_rule,
    dump_dru,
    find_rule,
    iter_rule_nodes,
    parse_dru,
    upsert_rule,
)
from ..utils.schematic_rules import rail_voltage
from ..validation import drc_runner
from ..validation.drc_report import (
    courtyard_violations,
    normalize_report_severity,
    report_entries,
)
from ..validation.policy_state import ValidationPolicyStateService
from . import validation_policy_state
from .export_support import _ensure_output_dir, _get_pcb_file, _get_sch_file, _run_cli_variants
from .gates import GateOutcome, GateStatus, _combined_status
from .metadata import headless_compatible
from .schematic_transfer import _collect_schematic_components, _export_schematic_net_map

if TYPE_CHECKING:
    from .design_intent_state import DecouplingPairIntent, ProjectDesignIntent


# Stable validation messages and gate labels shared across reports.
_PCB_TRANSFER_GATE = "PCB transfer"
_STACKUP_CONSISTENCY_GATE = "Stackup consistency"
_WARNING_PREFIX = "WARN: "
_ROUTE_CORNER_STYLE_GATE = "Route corner style"
_FOOTPRINT_PARITY_GATE = "Footprint parity"
_SCHEMATIC_CONNECTIVITY_GATE = "Schematic connectivity"
_SCHEMATIC_COSMETICS_GATE = "Schematic cosmetics"
_TOP_LEVEL_SHEET = "Top level"
_SCHEMATIC_DESIGN_RULES_GATE = "Schematic design rules"
_MISSING_PLACEMENT_ANALYSIS = "Placement analysis unexpectedly returned no result."
_NO_ACTIVE_PROJECT_ERROR = "No active project is configured."
_DRC_CLI_RECOVERY_HINT = "Make kicad-cli/report generation available, then rerun run_drc()."
_ERC_CLI_RECOVERY_HINT = "Make kicad-cli/report generation available, then rerun run_erc()."


@dataclass(slots=True)
class PlacementAnalysis:
    """Detailed placement scoring used by both the gate and the score tool."""

    footprint_count: int
    board_width_mm: float
    board_height_mm: float
    board_area_mm2: float
    footprint_area_mm2: float
    density_pct: float
    score: int
    hard_failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checked_connectors: int = 0
    checked_decoupling_pairs: int = 0
    checked_keepouts: int = 0
    checked_power_tree_refs: int = 0
    checked_analog_refs: int = 0
    checked_digital_refs: int = 0
    checked_sensor_cluster_refs: int = 0
    critical_net_proxy_mm: float = 0.0
    critical_net_proxy_density: float = 0.0
    checked_thermal_hotspot_refs: int = 0
    thermal_proximity_sum: float = 0.0
    # High-speed interface grouping and return-path checks (P4-T2 expansion)
    checked_hs_interfaces: int = 0
    hs_grouping_violations: list[str] = field(default_factory=list)
    return_path_warnings: list[str] = field(default_factory=list)
    # Mechanical constraint checks
    mount_hole_violations: list[str] = field(default_factory=list)
    connector_edge_spec_violations: list[str] = field(default_factory=list)
    # Before/after delta for auto-placement workflows
    score_before: int | None = None


class GateOutcomePayload(BaseModel):
    """Machine-readable gate outcome for MCP clients that support structured output."""

    name: str
    status: GateStatus
    summary: str
    details: list[str] = Field(default_factory=list)


class ProjectGateReportPayload(BaseModel):
    """Structured project-quality-gate report."""

    text: str
    status: GateStatus
    summary: str
    outcomes: list[GateOutcomePayload] = Field(default_factory=list)


class ReadinessEvidencePayload(BaseModel):
    """Evidence block used by the release-readiness bundle."""

    available: bool = False
    summary: str = ""
    path: str = ""
    details: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BomReadinessPayload(BaseModel):
    """BOM completeness evidence for release readiness."""

    summary: str = ""
    total_refs: int = 0
    populated_refs: int = 0
    dnp_refs: int = 0
    missing_mpn_refs: list[str] = Field(default_factory=list)
    missing_lcsc_refs: list[str] = Field(default_factory=list)
    missing_footprint_refs: list[str] = Field(default_factory=list)


class ProjectReleaseReadinessPayload(BaseModel):
    """Structured release-readiness evidence package."""

    text: str
    summary: str
    verdict: Verdict
    status: GateStatus
    drc: ReadinessEvidencePayload
    erc: ReadinessEvidencePayload
    manufacturing: GateOutcomePayload
    project_gate: ProjectGateReportPayload
    bom: BomReadinessPayload
    waivers: ReadinessEvidencePayload
    artifacts: ReadinessEvidencePayload
    manifest: ReadinessEvidencePayload
    approval_checklist: list[str] = Field(default_factory=list)
    open_risks: list[str] = Field(default_factory=list)
    advisory_notes: list[str] = Field(default_factory=list)
    exported_report_path: str = ""


class PlacementGateReportPayload(BaseModel):
    """Structured placement analysis payload."""

    text: str
    status: GateStatus
    summary: str
    score: int | None = None
    footprint_count: int | None = None
    checked_connectors: int = 0
    checked_decoupling_pairs: int = 0
    checked_keepouts: int = 0
    checked_power_tree_refs: int = 0
    checked_analog_refs: int = 0
    checked_digital_refs: int = 0
    checked_sensor_cluster_refs: int = 0
    critical_net_proxy_mm: float = 0.0
    critical_net_proxy_density: float = 0.0
    checked_thermal_hotspot_refs: int = 0
    thermal_proximity_sum: float = 0.0
    hard_failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _pcb_transfer_helpers() -> tuple[
    Callable[[], tuple[list[dict[str, Any]], list[str]]],
    Callable[[], tuple[dict[tuple[str, str], str], str]],
]:
    """Return transfer helpers while honoring the legacy pcb monkeypatch path."""
    pcb_module = sys.modules.get("kicad_mcp.tools.pcb")
    if pcb_module is None:
        return _collect_schematic_components, _export_schematic_net_map

    collect = getattr(pcb_module, "_collect_schematic_components", _collect_schematic_components)
    export = getattr(pcb_module, "_export_schematic_net_map", _export_schematic_net_map)
    return cast(Callable[[], tuple[list[dict[str, Any]], list[str]]], collect), cast(
        Callable[[], tuple[dict[tuple[str, str], str], str]],
        export,
    )


def _load_report(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _entries(report: dict[str, object], key: str) -> list[dict[str, object]]:
    return report_entries(report, key)


def _normalize_erc_sheet_id(value: object) -> str:
    return str(value or "").strip().strip("/").replace("\\", "/")


def _erc_sheet_matches_any(sheet: dict[str, object], ignored_sheet_ids: set[str]) -> bool:
    if not ignored_sheet_ids:
        return False
    candidates = {
        _normalize_erc_sheet_id(sheet.get("path")),
        _normalize_erc_sheet_id(sheet.get("sheet")),
        _normalize_erc_sheet_id(sheet.get("name")),
        _normalize_erc_sheet_id(sheet.get("file")),
        _normalize_erc_sheet_id(sheet.get("filename")),
    }
    return any(candidate and candidate in ignored_sheet_ids for candidate in candidates)


def _erc_violations(
    report: dict[str, object],
    ignored_sheet_ids: set[str] | None = None,
) -> list[dict[str, object]]:
    ignored = ignored_sheet_ids or set()
    violations = list(_entries(report, "violations"))
    for sheet in cast(list[dict[str, object]], report.get("sheets", [])):
        if _erc_sheet_matches_any(sheet, ignored):
            continue

        sheet_path = str(sheet.get("path") or sheet.get("name") or "")
        sheet_violations = cast(list[dict[str, object]], sheet.get("violations", []))

        if sheet_path:
            for violation in sheet_violations:
                copied = dict(violation)
                copied["sheet_path"] = sheet_path
                violations.append(copied)
        else:
            violations.extend(sheet_violations)

    return violations


def _erc_severity_summary(violations: list[dict[str, object]]) -> dict[str, int]:
    """Return violation counts keyed by severity (e.g. ``{"error": 2, "warning": 1}``).

    Preserves whatever severity strings the report carries (so severities beyond
    error/warning still surface), defaulting to ``"error"`` when a violation omits one —
    matching the conservative default used when turning violations into findings.
    """
    counts: dict[str, int] = {}
    for violation in violations:
        severity = str(violation.get("severity") or "error").casefold()
        if severity in {"warning", "warn", "marginal"}:
            severity = "warning"
        counts[severity] = counts.get(severity, 0) + 1
    return counts


def _type_breakdown(entries: list[dict[str, object]]) -> str:
    counts: dict[str, int] = {}
    for entry in entries:
        issue_type = str(entry.get("type", "unknown"))
        counts[issue_type] = counts.get(issue_type, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ", ".join(f"{name}={count}" for name, count in ordered[:8])


def _format_violations(title: str, entries: list[dict[str, object]]) -> str:
    if not entries:
        return f"{title}: none"
    lines = [f"{title} ({len(entries)} total):"]
    for entry in entries[: get_config().max_items_per_response]:
        severity = str(entry.get("severity", "?"))
        description = str(entry.get("description", "(no description)"))
        lines.append(f"- [{severity}] {description}")
    return "\n".join(lines)


def _entry_location(entry: dict[str, object], fallback: str) -> str:
    for key in ("uuid", "location", "sheet", "path", "item", "ref", "reference"):
        value = entry.get(key)
        if value:
            return str(value)
    return fallback


def _extract_report_entry_metadata(entry: dict[str, object]) -> dict[str, object]:
    metadata: dict[str, object] = {}
    if sheet_path := entry.get("sheet_path"):
        metadata["sheet_path"] = str(sheet_path)

    keys = ("ref", "pin", "net", "uuid", "position")
    plural = {
        "ref": "refs",
        "pin": "pins",
        "net": "nets",
        "uuid": "uuids",
        "position": "positions",
    }
    buckets: dict[str, list[object]] = {p: [] for p in plural.values()}

    for item in cast(list[dict[str, object]], entry.get("items", [])):
        for key in keys:
            if val := item.get(key):
                buckets[plural[key]].append(str(val) if key != "position" else val)

    for k, v in buckets.items():
        if v:
            metadata[k] = v
    return metadata


def _report_entry_finding(
    source: str,
    entry: dict[str, object],
    *,
    default_severity: str = "error",
    fix_tool: str,
) -> Finding:
    issue_type = str(entry.get("type") or source)
    description = str(entry.get("description") or entry.get("message") or issue_type)
    severity = normalize_report_severity(entry.get("severity", default_severity))
    location = _entry_location(entry, source)
    metadata = _extract_report_entry_metadata(entry)

    return Finding(
        id=stable_finding_id(source, issue_type, location, description),
        severity=severity,
        location=location,
        description=description,
        evidence=[{"source": source, "entry": dict(entry)}],
        remediation=f"Fix the {source} finding and rerun {fix_tool}(save_report=True).",
        retryable=False,
        failure_mode="design",
        suggested_fix=SuggestedFix(tool=fix_tool, args={"save_report": True}),
        metadata=metadata,
    )


def _gate_status_verdict(status: GateStatus) -> Verdict:
    if status == "PASS":
        return "PASS"
    if status in ("EMPTY", "WARN"):
        return "WARN"
    return "FAIL"


def _fix_for_gate(gate_name: str) -> SuggestedFix | None:
    from .fixers import fixers_for_gate

    fixer = next(iter(fixers_for_gate(gate_name)), None)
    if fixer is None:
        return None
    return SuggestedFix(tool=fixer.tool, args=fixer.args)


def _finding_for_gate_detail(outcome: GateOutcome, detail: str) -> Finding:
    cleaned = detail.strip()
    severity = (
        "warning" if outcome.status == "EMPTY" or cleaned.startswith(_WARNING_PREFIX) else "error"
    )
    description = (
        cleaned.removeprefix("FAIL: ")
        .removeprefix(_WARNING_PREFIX)
        .removeprefix("BLOCKED: ")
        .strip()
        or outcome.summary
    )
    suggested_fix = _fix_for_gate(outcome.name)
    remediation = (
        f"Run {suggested_fix.tool} and re-run this gate."
        if suggested_fix is not None
        else "Inspect this gate and re-run it after remediation."
    )
    return Finding(
        id=stable_finding_id("gate", outcome.name, outcome.status, description),
        severity=severity,
        location=outcome.name,
        description=description,
        evidence=[{"gate": outcome.name, "status": outcome.status, "detail": cleaned}],
        remediation=remediation,
        retryable=False,
        failure_mode="configuration" if outcome.status == "BLOCKED" else "design",
        suggested_fix=suggested_fix,
    )


def _gate_findings(outcome: GateOutcome) -> list[Finding]:
    # Detail lines are often informational metrics (counts, score, zero-count
    # summaries). Only explicit FAIL/WARN/BLOCKED lines should become actionable
    # findings. When a non-passing gate has no tagged detail, fall back to a
    # single summary finding rather than promoting every metric line to errors.
    tagged = [
        detail
        for detail in outcome.details
        if detail.strip().startswith(("FAIL: ", _WARNING_PREFIX, "BLOCKED: "))
    ]
    if outcome.status == "PASS":
        actionable = tagged
    else:
        actionable = tagged or [outcome.summary]
    return [_finding_for_gate_detail(outcome, detail) for detail in actionable]


def _gate_report(outcome: GateOutcome) -> VerdictReport:
    findings = _gate_findings(outcome)
    verdict = VerdictReport.verdict_for([finding.severity for finding in findings])
    if verdict == "PASS":
        verdict = _gate_status_verdict(outcome.status)
    next_action = "Proceed to the next gate."
    if outcome.status != "PASS":
        fixer = _fix_for_gate(outcome.name)
        next_action = (
            f"Call {fixer.tool} and re-run this gate."
            if fixer is not None
            else "Inspect this gate and re-run it after remediation."
        )
    failure_mode = "none" if verdict == "PASS" else "design"
    if verdict != "PASS" and outcome.status == "BLOCKED":
        failure_mode = "configuration"
    return VerdictReport(
        text=_format_gate(outcome),
        summary=outcome.summary,
        verdict=verdict,
        failure_mode=failure_mode,
        retryable=False,
        evidence=[{"gate": outcome.name, "status": outcome.status, "details": outcome.details}],
        remediation="" if verdict == "PASS" else next_action,
        findings=findings,
        next_action=next_action,
        metadata={"gate": outcome.name, "status": outcome.status, "details": outcome.details},
    )


def _drc_report_payload(
    path: Path,
    report: dict[str, object] | None,
    error: str | None,
    *,
    save_report: bool,
) -> VerdictReport:
    report_status, classification_error = drc_runner.classify_legacy_drc_result(report, error)
    if report_status == "malformed":
        detail = classification_error or "unknown schema error"
        message = f"DRC report malformed: {detail}"
        remediation = "Regenerate the DRC report with a supported KiCad CLI, then rerun run_drc()."
        return VerdictReport(
            text=message,
            summary="DRC report is malformed.",
            verdict="FAIL",
            findings=[
                Finding(
                    id=stable_finding_id("drc", "malformed", detail),
                    severity="error",
                    location=str(path),
                    description=message,
                    evidence=[{"report_path": str(path), "error": detail}],
                    remediation=remediation,
                    retryable=False,
                    failure_mode="configuration",
                    suggested_fix=SuggestedFix(tool="run_drc", args={"save_report": True}),
                )
            ],
            failure_mode="configuration",
            retryable=False,
            remediation=remediation,
            next_action=remediation,
            metadata={
                "report_path": str(path),
                "available": False,
                "failure_mode": "configuration",
                "report_status": "malformed",
            },
        )

    if report_status == "unavailable":
        message = f"DRC report unavailable: {classification_error or 'unknown error'}"
        return VerdictReport(
            text=message,
            summary="DRC report is unavailable.",
            verdict="FAIL",
            findings=[
                Finding(
                    id=stable_finding_id("drc", "unavailable", classification_error or "unknown"),
                    severity="error",
                    location=str(path),
                    description=message,
                    evidence=[
                        {
                            "report_path": str(path),
                            "error": classification_error or "unknown error",
                        }
                    ],
                    remediation=_DRC_CLI_RECOVERY_HINT,
                    retryable=True,
                    failure_mode="environment",
                    suggested_fix=SuggestedFix(tool="run_drc", args={"save_report": True}),
                )
            ],
            failure_mode="environment",
            retryable=True,
            remediation=_DRC_CLI_RECOVERY_HINT,
            next_action=_DRC_CLI_RECOVERY_HINT,
            metadata={
                "report_path": str(path),
                "available": False,
                "failure_mode": "environment",
                "report_status": "unavailable",
            },
        )

    validated_report = cast(dict[str, object], report)
    violations = _entries(validated_report, "violations")
    unconnected = _entries(validated_report, "unconnected_items")
    courtyard = courtyard_violations(validated_report)
    lines = [
        "DRC summary:",
        f"- Violations: {len(violations)}",
        f"- Unconnected items: {len(unconnected)}",
        f"- Courtyard issues: {len(courtyard)}",
    ]
    if violations:
        lines.append(_format_violations("Violations", violations))
    if save_report:
        lines.append(f"Saved report: {path}")
    findings = [_report_entry_finding("drc", entry, fix_tool="run_drc") for entry in violations]
    findings.extend(
        _report_entry_finding(
            "drc.unconnected",
            entry,
            default_severity="error",
            fix_tool="get_unconnected_nets",
        )
        for entry in unconnected
    )
    findings.extend(
        _report_entry_finding(
            "drc.courtyard",
            entry,
            default_severity="error",
            fix_tool="get_courtyard_violations",
        )
        for entry in courtyard
        if entry not in violations
    )
    verdict = VerdictReport.verdict_for([finding.severity for finding in findings])
    return VerdictReport(
        text="\n".join(lines),
        summary=(
            "DRC is clean."
            if verdict == "PASS"
            else f"DRC reported {len(findings)} actionable finding(s)."
        ),
        verdict=verdict,
        failure_mode="none" if verdict == "PASS" else "design",
        retryable=False,
        evidence=[{"report_path": str(path), "violations": validated_report}],
        remediation=(
            "" if verdict == "PASS" else "Fix DRC findings and rerun run_drc(save_report=True)."
        ),
        findings=findings,
        next_action=(
            "No DRC action required."
            if verdict == "PASS"
            else "Fix DRC findings and rerun run_drc(save_report=True)."
        ),
        metadata={
            "report_path": str(path),
            "available": True,
            "violations": len(violations),
            "unconnected_items": len(unconnected),
            "courtyard_issues": len(courtyard),
            "report_status": report_status,
        },
    )


def _erc_report_payload(
    path: Path,
    report: dict[str, object] | None,
    error: str | None,
    *,
    save_report: bool,
) -> VerdictReport:
    if report is None:
        message = f"ERC report unavailable: {error or 'unknown error'}"
        return VerdictReport(
            text=message,
            summary="ERC report is unavailable.",
            verdict="FAIL",
            findings=[
                Finding(
                    id=stable_finding_id("erc", "unavailable", error or "unknown"),
                    severity="error",
                    location=str(path),
                    description=message,
                    evidence=[{"report_path": str(path), "error": error or "unknown error"}],
                    remediation=_ERC_CLI_RECOVERY_HINT,
                    retryable=True,
                    failure_mode="environment",
                    suggested_fix=SuggestedFix(tool="run_erc", args={"save_report": True}),
                )
            ],
            failure_mode="environment",
            retryable=True,
            remediation=_ERC_CLI_RECOVERY_HINT,
            next_action=_ERC_CLI_RECOVERY_HINT,
            metadata={"report_path": str(path), "available": False, "failure_mode": "environment"},
        )

    violations = _erc_violations(report)
    severity_summary = _erc_severity_summary(violations)
    lines = ["ERC summary:", f"- Violations: {len(violations)}"]
    if violations:
        lines.append(_format_violations("Violations", violations))
    if save_report:
        lines.append(f"Saved report: {path}")
    findings = [_report_entry_finding("erc", entry, fix_tool="run_erc") for entry in violations]
    verdict = VerdictReport.verdict_for([finding.severity for finding in findings])
    return VerdictReport(
        text="\n".join(lines),
        summary=(
            "ERC is clean."
            if verdict == "PASS"
            else f"ERC reported {len(findings)} actionable finding(s)."
        ),
        verdict=verdict,
        failure_mode="none" if verdict == "PASS" else "design",
        retryable=False,
        evidence=[{"report_path": str(path), "violations": report}],
        remediation=(
            "" if verdict == "PASS" else "Fix ERC findings and rerun run_erc(save_report=True)."
        ),
        findings=findings,
        next_action=(
            "No ERC action required."
            if verdict == "PASS"
            else "Fix ERC findings and rerun run_erc(save_report=True)."
        ),
        metadata={
            "report_path": str(path),
            "available": True,
            # ``violations`` is the aggregated flat list across all sheets (each entry
            # retains its ``sheet_path`` plus existing fields); ``violation_count`` keeps
            # the previous scalar so nothing that read it silently breaks. ``summary``
            # gives counts by severity so a consumer sees a non-clean schematic at a
            # glance instead of missing per-sheet violations.
            "violation_count": len(violations),
            "violations": violations,
            "summary": severity_summary,
        },
    )


def _run_drc_report(report_name: str) -> tuple[Path, dict[str, object] | None, str | None]:
    pcb_file = _get_pcb_file()
    cfg = get_config()
    result = drc_runner.run_drc_report(
        report_name,
        pcb_file=pcb_file,
        output_dir=_ensure_output_dir(),
        run_cli_variants=_run_cli_variants,
        capabilities=get_cli_capabilities(cfg.kicad_cli),
    )
    return result.as_legacy_tuple()


def _run_erc_report(report_name: str) -> tuple[Path, dict[str, object] | None, str | None]:
    sch_file = _get_sch_file()
    out_file = _ensure_output_dir() / report_name
    code, _, stderr = _run_cli_variants(
        [
            [
                "sch",
                "erc",
                "--output",
                str(out_file),
                "--format",
                "json",
                "--severity-all",
                "--exit-code-violations",
                str(sch_file),
            ],
            [
                "sch",
                "erc",
                "--input",
                str(sch_file),
                "--output",
                str(out_file),
                "--format",
                "json",
                "--severity-all",
                "--exit-code-violations",
            ],
        ]
    )
    if not out_file.exists():
        return out_file, None, stderr if code != 0 else "ERC report was not produced."
    return out_file, _load_report(out_file), None


def _format_gate(outcome: GateOutcome) -> str:
    lines = [f"{outcome.name} quality gate: {outcome.status}", f"- {outcome.summary}"]
    for detail in outcome.details:
        lines.append(f"- {detail}")
    return "\n".join(lines)


def _gate_outcome_payload(outcome: GateOutcome) -> GateOutcomePayload:
    return GateOutcomePayload(
        name=outcome.name,
        status=outcome.status,
        summary=outcome.summary,
        details=outcome.details,
    )


def _board_footprint_references() -> tuple[set[str], str, str | None]:
    """Compare the saved project PCB, never a potentially unrelated active GUI board."""
    from ..utils.sexpr import _extract_block
    from .board_file import _parse_board_footprint_blocks, _validate_board_text

    try:
        board_text = _get_pcb_file().read_text(encoding="utf-8")
        _validate_board_text(board_text)
        document = board_text.strip()
        if not re.match(r"\(kicad_pcb(?=[\s)])", document):
            raise ValueError("The configured file is not a KiCad PCB document.")
        _, root_length = _extract_block(document, 0)
        if root_length != len(document):
            raise ValueError("The configured PCB must contain exactly one root expression.")
    except (OSError, ValueError) as exc:
        return set(), "file", str(exc)
    return set(_parse_board_footprint_blocks(board_text)), "file", None


def _footprint_parity_outcome() -> GateOutcome:
    from .schematic import parse_schematic_file, project_schematic_files

    cfg = get_config()
    if cfg.sch_file is None or cfg.pcb_file is None:
        return GateOutcome(
            name=_FOOTPRINT_PARITY_GATE,
            status="BLOCKED",
            summary="Both schematic and PCB files must be configured first.",
        )

    schematic_files = project_schematic_files()
    schematic_refs: set[str] = set()
    for sch_file in schematic_files:
        schematic = parse_schematic_file(sch_file)
        schematic_refs.update(
            str(symbol["reference"])
            for symbol in schematic["symbols"]
            if str(symbol["reference"]).strip()
            and not str(symbol["reference"]).startswith("#")
            and str(symbol["footprint"]).strip()
        )
    board_refs, source, error = _board_footprint_references()
    if error is not None:
        return GateOutcome(
            name=_FOOTPRINT_PARITY_GATE,
            status="BLOCKED",
            summary=f"PCB references were unavailable via {source} mode ({error}).",
        )

    missing_on_board = sorted(schematic_refs - board_refs)
    missing_in_schematic = sorted(board_refs - schematic_refs)
    status: GateStatus = "PASS" if not missing_on_board and not missing_in_schematic else "FAIL"
    details = [
        f"Schematic files scanned: {len(schematic_files)}",
        f"Schematic refs with footprints: {len(schematic_refs)}",
        f"PCB footprint refs ({source}): {len(board_refs)}",
        f"Missing on board: {len(missing_on_board)}",
        f"Missing in schematic: {len(missing_in_schematic)}",
    ]
    if missing_on_board:
        details.append("Missing on board refs: " + ", ".join(missing_on_board[:20]))
    if missing_in_schematic:
        details.append("Missing in schematic refs: " + ", ".join(missing_in_schematic[:20]))
    return GateOutcome(
        name=_FOOTPRINT_PARITY_GATE,
        status=status,
        summary="PCB and schematic references are aligned."
        if status == "PASS"
        else "Schematic and PCB references are out of sync.",
        details=details,
    )


def _collect_pcb_transfer_prerequisites() -> (
    tuple[set[str], dict[tuple[str, str], str], dict[str, Any]] | GateOutcome
):
    from .board_file import _parse_board_footprint_blocks

    collect_schematic_components, export_schematic_net_map = _pcb_transfer_helpers()

    cfg = get_config()
    if cfg.sch_file is None or cfg.pcb_file is None:
        return GateOutcome(
            name=_PCB_TRANSFER_GATE,
            status="BLOCKED",
            summary="Both schematic and PCB files must be configured first.",
        )

    try:
        components, issues = collect_schematic_components()
    except ValueError as exc:
        return GateOutcome(
            name=_PCB_TRANSFER_GATE,
            status="BLOCKED",
            summary=str(exc),
        )
    if issues:
        return GateOutcome(
            name=_PCB_TRANSFER_GATE,
            status="FAIL",
            summary="Schematic component metadata is not stable enough for pad-net transfer.",
            details=issues[:12],
        )

    expected_map, note = export_schematic_net_map()
    if note:
        return GateOutcome(
            name=_PCB_TRANSFER_GATE,
            status="BLOCKED",
            summary=note,
        )
    if not expected_map:
        return GateOutcome(
            name=_PCB_TRANSFER_GATE,
            status="BLOCKED",
            summary="The schematic did not export any named pad nets to compare against the PCB.",
        )

    try:
        board_text = cfg.pcb_file.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return GateOutcome(
            name=_PCB_TRANSFER_GATE,
            status="BLOCKED",
            summary=f"Could not read the PCB file ({exc}).",
        )

    footprints = _parse_board_footprint_blocks(board_text)
    component_refs = {str(component["reference"]) for component in components}
    return component_refs, expected_map, footprints


def _check_pad_net_match(
    reference: str,
    pad_number: str,
    expected_net: str,
    actual_net: str,
) -> tuple[bool, str | None]:
    expected_unconnected = expected_net.startswith("unconnected-(")
    if expected_unconnected:
        # KiCad can retain a generated unconnected-(...) net on the PCB pad.
        # Schematic and PCB exporters may each escape '/' as '{slash}' in
        # generated no-connect names; normalize both before comparing.
        # Never treat a named real net as an intentional no-connect.
        if not actual_net or actual_net.replace("{slash}", "/") == expected_net.replace(
            "{slash}", "/"
        ):
            return True, None
        return (
            False,
            f"{reference}.{pad_number}: PCB has '{actual_net}', "
            f"expected unconnected net '{expected_net}' or no net.",
        )
    if not actual_net:
        return False, f"{reference}.{pad_number}: missing net '{expected_net}' on PCB."
    if actual_net != expected_net:
        return (
            False,
            f"{reference}.{pad_number}: PCB has '{actual_net}', expected '{expected_net}'.",
        )
    return True, None


def _compare_ref_pad_nets(
    reference: str,
    expected_for_ref: Sequence[tuple[str, str]],
    actual_pad_nets: Mapping[str, str],
) -> tuple[int, list[str]]:
    matched = 0
    mismatches: list[str] = []
    for pad_number, expected_net in expected_for_ref:
        actual_net = actual_pad_nets.get(pad_number, "")
        is_match, err = _check_pad_net_match(reference, pad_number, expected_net, actual_net)
        if is_match:
            matched += 1
        elif err is not None:
            mismatches.append(err)
    return matched, mismatches


def _build_pcb_transfer_outcome(
    total_expected_pads: int,
    matched_pads: int,
    missing_refs: list[str],
    mismatches: list[str],
) -> GateOutcome:
    if total_expected_pads == 0:
        return GateOutcome(
            name=_PCB_TRANSFER_GATE,
            status="BLOCKED",
            summary="No expected named pads were available for transfer comparison.",
        )

    coverage_pct = round((matched_pads / total_expected_pads) * 100, 1)
    status: GateStatus = "PASS" if not missing_refs and not mismatches else "FAIL"
    details = [
        f"Expected named pad nets: {total_expected_pads}",
        f"Matched pad nets on PCB: {matched_pads}",
        f"Transfer coverage: {coverage_pct}%",
        f"Missing footprint refs on PCB: {len(missing_refs)}",
        f"Pad-net mismatches: {len(mismatches)}",
    ]
    if missing_refs:
        details.append("Missing footprint refs: " + ", ".join(missing_refs[:20]))
    details.extend(f"FAIL: {item}" for item in mismatches[:12])
    return GateOutcome(
        name=_PCB_TRANSFER_GATE,
        status=status,
        summary="Named schematic pad nets match the PCB footprint pads."
        if status == "PASS"
        else "Named schematic pad nets did not transfer cleanly to the PCB.",
        details=details,
    )


def _evaluate_pcb_transfer_gate() -> GateOutcome:
    prereqs = _collect_pcb_transfer_prerequisites()
    if isinstance(prereqs, GateOutcome):
        return prereqs

    component_refs, expected_map, footprints = prereqs
    missing_refs: list[str] = []
    mismatches: list[str] = []
    matched_pads = 0
    total_expected_pads = 0

    for reference in sorted(component_refs):
        expected_for_ref = sorted(
            (pad_number, net_name)
            for (ref, pad_number), net_name in expected_map.items()
            if ref == reference and net_name
        )
        if not expected_for_ref:
            continue
        entry = footprints.get(reference)
        if entry is None:
            missing_refs.append(reference)
            total_expected_pads += len(expected_for_ref)
            continue

        actual_pad_nets = cast(dict[str, str], entry.get("pad_nets", {}))
        total_expected_pads += len(expected_for_ref)
        ref_matched, ref_mismatches = _compare_ref_pad_nets(
            reference, expected_for_ref, actual_pad_nets
        )
        matched_pads += ref_matched
        mismatches.extend(ref_mismatches)

    return _build_pcb_transfer_outcome(total_expected_pads, matched_pads, missing_refs, mismatches)


def _evaluate_schematic_gate() -> GateOutcome:
    from .schematic import _build_connectivity_groups, parse_schematic_file

    _, report, error = _run_erc_report("schematic_quality_gate.json")
    if report is None:
        return GateOutcome(
            name="Schematic",
            status="BLOCKED",
            summary=f"ERC report was unavailable ({error or 'unknown error'}).",
        )

    cfg = get_config()
    ignored_empty_sheets: set[str] = set()
    if cfg.sch_file is not None:
        ignored_empty_sheets = _empty_child_sheet_ids(cfg.sch_file)
    raw_violations = _erc_violations(report)
    violations = _erc_violations(report, ignored_empty_sheets)
    ignored_violation_count = len(raw_violations) - len(violations)
    details = [f"ERC violations: {len(violations)}"]
    if ignored_violation_count:
        details.append(f"Ignored empty child-sheet ERC violations: {ignored_violation_count}")
    if cfg.sch_file is not None:
        try:
            data = parse_schematic_file(cfg.sch_file)
            groups = _build_connectivity_groups(cfg.sch_file)
            orphan_groups = [
                group
                for group in groups
                if len(cast(list[dict[str, object]], group["pins"])) == 1
                and not cast(list[str], group["names"])
            ]
            details.extend(
                [
                    f"Symbols: {len(data['symbols'])}",
                    f"Power symbols: {len(data['power_symbols'])}",
                    f"Wires: {len(data['wires'])}",
                    f"Labels: {len(data['labels'])}",
                    f"Connectivity groups: {len(groups)}",
                    f"Unnamed single-pin groups: {len(orphan_groups)}",
                ]
            )
        except (OSError, ValueError) as exc:
            details.append(f"Connectivity summary unavailable ({exc})")

    status: GateStatus = "PASS" if not violations else "FAIL"
    if violations:
        details.append(f"Violation types: {_type_breakdown(violations)}")
    return GateOutcome(
        name="Schematic",
        status=status,
        summary="ERC is clean." if status == "PASS" else "ERC reported blocking issues.",
        details=details,
    )


def _sheet_contracts(sch_file: Path) -> list[dict[str, object]]:
    from ..utils.sexpr import _extract_block, _unescape_sexpr_string

    content = sch_file.read_text(encoding="utf-8", errors="ignore")
    contracts: list[dict[str, object]] = []
    for match in re.finditer(r"\(sheet(?=\s)", content):
        block, _ = _extract_block(content, match.start())
        if not block:
            continue
        name_match = re.search(r'\(property\s+"Sheetname"\s+"((?:\\.|[^"\\])*)"', block)
        file_match = re.search(r'\(property\s+"Sheetfile"\s+"((?:\\.|[^"\\])*)"', block)
        if file_match is None:
            continue
        pin_names = [
            _unescape_sexpr_string(value)
            for value in re.findall(r'\(pin\s+"((?:\\.|[^"\\])*)"\s+\w+', block)
        ]
        contracts.append(
            {
                "name": _unescape_sexpr_string(name_match.group(1))
                if name_match is not None
                else Path(_unescape_sexpr_string(file_match.group(1))).stem,
                "filename": _unescape_sexpr_string(file_match.group(1)),
                "pins": sorted(pin_names),
            }
        )
    return contracts


def _sheet_match_key(value: object) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    candidate = Path(raw).stem if raw.lower().endswith(".kicad_sch") else raw
    return re.sub(r"[^a-z0-9]+", "", candidate.casefold())


def _sheet_contract_keys(contract: dict[str, object]) -> set[str]:
    filename = str(contract.get("filename", ""))
    keys = {
        _sheet_match_key(contract.get("name", "")),
        _sheet_match_key(filename),
        _sheet_match_key(Path(filename).stem if filename else ""),
    }
    return {key for key in keys if key}


def _sheet_intent_contract() -> tuple[bool, list[str], set[str], set[str]]:
    try:
        from .design_intent_state import resolve_design_intent

        resolution = resolve_design_intent()
    except Exception:
        return False, [], set(), set()
    if resolution.source == "none":
        return False, [], set(), set()
    intent = resolution.resolved
    required = list(getattr(intent, "required_sheets", []) or [])
    optional = list(getattr(intent, "optional_sheets", []) or [])
    return (
        bool(required or optional),
        required,
        {_sheet_match_key(sheet) for sheet in required if _sheet_match_key(sheet)},
        {_sheet_match_key(sheet) for sheet in optional if _sheet_match_key(sheet)},
    )


def _hierarchical_labels(sch_file: Path) -> set[str]:
    from ..utils.sexpr import _unescape_sexpr_string

    content = sch_file.read_text(encoding="utf-8", errors="ignore")
    return {
        _unescape_sexpr_string(match.group(1))
        for match in re.finditer(r'\(hierarchical_label\s+"((?:\\.|[^"\\])*)"', content)
    }


def _empty_child_sheet_ids(top_file: Path) -> set[str]:
    from .schematic import parse_schematic_file

    ignored: set[str] = set()
    try:
        contracts = _sheet_contracts(top_file)
    except OSError:
        return ignored

    for contract in contracts:
        filename = str(contract.get("filename", ""))
        if not filename:
            continue
        child_path = top_file.parent / filename
        if not child_path.exists():
            continue
        try:
            data = parse_schematic_file(child_path)
        except (OSError, RuntimeError, ValueError):
            continue
        item_count = (
            len(cast(list[object], data.get("symbols", [])))
            + len(cast(list[object], data.get("power_symbols", [])))
            + len(cast(list[object], data.get("wires", [])))
            + len(cast(list[object], data.get("labels", [])))
        )
        if item_count != 0:
            continue
        name = str(contract.get("name", ""))
        for candidate in {name, filename, child_path.name, child_path.stem}:
            normalized = _normalize_erc_sheet_id(candidate)
            if normalized:
                ignored.add(normalized)
    return ignored


# Sheets scoring below this are flagged (advisory only — cosmetic quality never
# blocks release).
_COSMETIC_GATE_THRESHOLD = 80.0


def _evaluate_schematic_cosmetics_gate() -> GateOutcome:
    """Advisory gate on schematic cosmetic quality (never blocks release).

    Scores every sheet with the deterministic cosmetic engine and reports the
    worst. Below the threshold it returns WARN with the worst category, so the
    fix queue surfaces the cosmetic tools without gating manufacturing.
    """
    from ..models.visual_qa import run_cosmetic_qa
    from .schematic import project_schematic_files

    try:
        sheets = project_schematic_files()
    except Exception:
        sheets = []
    if not sheets:
        return GateOutcome(_SCHEMATIC_COSMETICS_GATE, "PASS", "No schematic sheets to score.")

    worst_score = 100.0
    worst_sheet = ""
    worst_category = ""
    details: list[str] = []
    for sch in sheets:
        try:
            text = sch.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        report = run_cosmetic_qa(text)
        score = float(cast(float, report["cosmetic_score"]))
        category = str(report.get("worst_category") or "")
        details.append(f"{sch.name}: score {score:.0f} (worst: {category or 'none'})")
        if score < worst_score:
            worst_score, worst_sheet, worst_category = score, sch.name, category

    if worst_score >= _COSMETIC_GATE_THRESHOLD:
        return GateOutcome(
            _SCHEMATIC_COSMETICS_GATE,
            "PASS",
            f"Cosmetic score {worst_score:.0f}/100 across all sheets.",
            details,
        )
    return GateOutcome(
        _SCHEMATIC_COSMETICS_GATE,
        "WARN",
        f"Cosmetic score {worst_score:.0f}/100 on {worst_sheet} "
        f"(worst category: {worst_category or 'none'}). Advisory — does not block release.",
        details,
    )


def _process_sheet_contracts(
    top_file: Path,
    contracts: list[dict[str, object]],
    pages: list[tuple[str, Path]],
    sheet_keys_by_path: dict[Path, set[str]],
    available_sheet_keys: set[str],
    blocked: list[str],
    failures: list[str],
) -> None:
    for contract in contracts:
        child_path = top_file.parent / str(contract["filename"])
        sheet_keys = _sheet_contract_keys(contract)
        sheet_keys_by_path[child_path] = sheet_keys
        available_sheet_keys.update(sheet_keys)
        pages.append((str(contract["name"]), child_path))
        if not child_path.exists():
            blocked.append(f"Child sheet '{contract['name']}' is missing: {child_path.name}.")
            continue
        try:
            child_labels = _hierarchical_labels(child_path)
        except OSError as exc:
            blocked.append(
                f"Child sheet '{contract['name']}' could not be read for contract checks ({exc})."
            )
            continue

        top_pins = set(cast(list[str], contract["pins"]))
        if top_pins != child_labels:
            missing_on_top = sorted(child_labels - top_pins)
            missing_in_child = sorted(top_pins - child_labels)
            mismatch = [f"Hierarchy contract mismatch for '{contract['name']}'."]
            if missing_on_top:
                mismatch.append("top missing " + ", ".join(missing_on_top[:12]))
            if missing_in_child:
                mismatch.append("child missing " + ", ".join(missing_in_child[:12]))
            failures.append("; ".join(mismatch))


def _classify_empty_sheet(
    page_keys: set[str],
    required_sheet_keys: set[str],
    optional_sheet_keys: set[str],
    page_name: str,
    failures: list[str],
) -> tuple[int, int, int]:
    """Return (required_empty, optional_empty, placeholder_empty)."""
    if page_keys & required_sheet_keys:
        failures.append(
            f"Sheet '{page_name}' is required by design intent but contains no "
            "symbols, labels, or wires."
        )
        return 1, 0, 0
    if page_keys & optional_sheet_keys:
        return 0, 1, 0
    return 0, 0, 1


def _check_connectivity_group_smells(
    page_name: str,
    groups: list[dict[str, Any]],
    failures: list[str],
) -> tuple[int, int]:
    label_only_groups = [
        group
        for group in groups
        if group["names"] and not group["pins"] and len(group["points"]) == 1
    ]
    for group in label_only_groups[:8]:
        failures.append(
            f"{page_name}: unattached label/group at {group['points'][0]} -> "
            + ", ".join(cast(list[str], group["names"])[:4])
        )

    unnamed_groups = [
        group
        for group in groups
        if not group["names"]
        and len(group["pins"]) == 1
        and not group.get("no_connect")
        and str(group["pins"][0].get("etype", "")).lower() != "no_connect"
    ]
    for group in unnamed_groups[:8]:
        pin = cast(dict[str, str], group["pins"][0])
        failures.append(
            f"{page_name}: unnamed single-pin group at {group['points'][0]} -> "
            f"{pin['reference']}:{pin['pin']}"
        )
    return len(label_only_groups), len(unnamed_groups)


def _check_symbol_connectivity_and_contracts(
    page_name: str,
    symbols: list[dict[str, Any]],
    groups: list[dict[str, Any]],
    failures: list[str],
) -> tuple[int, int, int]:
    matched_contracts = 0
    isolated_symbols = 0
    contract_violations = 0
    for symbol in symbols:
        footprint = str(symbol.get("footprint", "")).strip()
        lib_id = str(symbol.get("lib_id", "")).strip()
        if not footprint:
            continue
        reference = str(symbol.get("reference", "")).strip()
        component_contract = find_component_contract(lib_id=lib_id, footprint=footprint)
        if component_contract is not None:
            matched_contracts += 1
        relevant_groups = [
            group
            for group in groups
            if any(
                str(pin["reference"]) == reference
                for pin in cast(list[dict[str, object]], group["pins"])
            )
        ]
        meaningful = any(group["names"] or len(group["pins"]) > 1 for group in relevant_groups)
        if not meaningful:
            isolated_symbols += 1
            failures.append(
                f"{page_name}: {reference} has footprint '{footprint}' but no meaningful "
                "net/power connectivity."
            )
        if component_contract is None:
            continue
        group_names_upper = {
            str(name).upper()
            for group in relevant_groups
            for name in cast(list[str], group["names"])
        }
        missing_groups = [
            "/".join(options)
            for options in component_contract.required_net_groups
            if not any(option.upper() in group_names_upper for option in options)
        ]
        if missing_groups:
            contract_violations += 1
            failures.append(
                f"{page_name}: {reference} matched contract '{component_contract.key}' "
                f"but is missing required nets: {', '.join(missing_groups)}."
            )
    return matched_contracts, isolated_symbols, contract_violations


@dataclass
class _ConnectivityGateCounters:
    required_empty_sheets: int = 0
    optional_empty_sheets: int = 0
    placeholder_empty_sheets: int = 0
    zero_wire_pages: int = 0
    dangling_labels: int = 0
    unnamed_single_pin_groups: int = 0
    matched_component_contracts: int = 0
    isolated_footprint_symbols: int = 0
    contract_violations: int = 0


def _analyze_single_page_connectivity(
    page_name: str,
    page_path: Path,
    counters: _ConnectivityGateCounters,
    *,
    sheet_keys_by_path: dict[Path, set[str]],
    has_sheet_contract: bool,
    required_sheet_keys: set[str],
    optional_sheet_keys: set[str],
    blocked: list[str],
    failures: list[str],
    page_summaries: list[str],
) -> None:
    from .schematic import _build_connectivity_groups, parse_schematic_file

    if not page_path.exists():
        return
    try:
        data = parse_schematic_file(page_path)
        groups = _build_connectivity_groups(page_path)
    except (OSError, RuntimeError, ValueError) as exc:
        blocked.append(f"{page_name}: connectivity data was unavailable ({exc}).")
        return

    symbol_count = len(data["symbols"]) + len(data["power_symbols"])
    label_count = len(data["labels"])
    wire_count = len(data["wires"])
    page_summaries.append(
        f"{page_name}: {symbol_count} symbol(s), {label_count} label(s), {wire_count} wire(s)"
    )

    page_keys = sheet_keys_by_path.get(page_path, set())
    is_child_sheet = page_name != _TOP_LEVEL_SHEET
    is_empty_sheet = symbol_count == 0 and label_count == 0 and wire_count == 0
    if has_sheet_contract and is_child_sheet and is_empty_sheet:
        req_e, opt_e, plc_e = _classify_empty_sheet(
            page_keys, required_sheet_keys, optional_sheet_keys, page_name, failures
        )
        counters.required_empty_sheets += req_e
        counters.optional_empty_sheets += opt_e
        counters.placeholder_empty_sheets += plc_e

    if wire_count == 0 and (symbol_count >= 2 or label_count >= 3):
        counters.zero_wire_pages += 1
        failures.append(
            f"{page_name}: has {symbol_count} symbol(s) and {label_count} label(s) but 0 wires."
        )

    dangling_cnt, unnamed_cnt = _check_connectivity_group_smells(page_name, groups, failures)
    counters.dangling_labels += dangling_cnt
    counters.unnamed_single_pin_groups += unnamed_cnt

    matched_c, isolated_s, violations_c = _check_symbol_connectivity_and_contracts(
        page_name, cast(list[dict[str, object]], data["symbols"]), groups, failures
    )
    counters.matched_component_contracts += matched_c
    counters.isolated_footprint_symbols += isolated_s
    counters.contract_violations += violations_c


def _evaluate_schematic_connectivity_gate() -> GateOutcome:
    try:
        top_file = _get_sch_file()
    except ValueError as exc:
        return GateOutcome(
            name=_SCHEMATIC_CONNECTIVITY_GATE,
            status="BLOCKED",
            summary=str(exc),
        )

    pages: list[tuple[str, Path]] = [(_TOP_LEVEL_SHEET, top_file)]
    blocked: list[str] = []
    failures: list[str] = []
    page_summaries: list[str] = []
    try:
        contracts = _sheet_contracts(top_file)
    except OSError as exc:
        return GateOutcome(
            name=_SCHEMATIC_CONNECTIVITY_GATE,
            status="BLOCKED",
            summary=f"Top-level sheet contract data was unavailable ({exc}).",
        )

    has_sheet_contract, required_sheets, required_sheet_keys, optional_sheet_keys = (
        _sheet_intent_contract()
    )
    sheet_keys_by_path: dict[Path, set[str]] = {}
    available_sheet_keys: set[str] = set()
    _process_sheet_contracts(
        top_file,
        contracts,
        pages,
        sheet_keys_by_path,
        available_sheet_keys,
        blocked,
        failures,
    )

    required_missing_sheets = 0
    if has_sheet_contract:
        for sheet in required_sheets:
            key = _sheet_match_key(sheet)
            if key and key not in available_sheet_keys:
                required_missing_sheets += 1
                failures.append(
                    f"Required sheet '{sheet}' is not present in the schematic hierarchy."
                )

    counters = _ConnectivityGateCounters()
    for page_name, page_path in pages:
        _analyze_single_page_connectivity(
            page_name,
            page_path,
            counters,
            sheet_keys_by_path=sheet_keys_by_path,
            has_sheet_contract=has_sheet_contract,
            required_sheet_keys=required_sheet_keys,
            optional_sheet_keys=optional_sheet_keys,
            blocked=blocked,
            failures=failures,
            page_summaries=page_summaries,
        )

    hierarchy_mismatches = sum("Hierarchy contract mismatch" in item for item in failures)
    details = [f"Pages analysed: {len(pages)}"]
    details.extend(page_summaries[:12])
    details.extend(
        [
            f"Dangling label groups: {counters.dangling_labels}",
            f"Zero-wire pages: {counters.zero_wire_pages}",
            f"Unnamed single-pin groups: {counters.unnamed_single_pin_groups}",
            f"Isolated footprint symbols: {counters.isolated_footprint_symbols}",
            f"Hierarchy contract mismatches: {hierarchy_mismatches}",
            f"Matched component contracts: {counters.matched_component_contracts}",
            f"Component contract violations: {counters.contract_violations}",
        ]
    )
    if has_sheet_contract:
        details.extend(
            [
                f"Required missing sheets: {required_missing_sheets}",
                f"Required empty sheets: {counters.required_empty_sheets}",
                f"Optional empty sheets: {counters.optional_empty_sheets}",
                f"Placeholder empty sheets: {counters.placeholder_empty_sheets}",
            ]
        )
    if blocked:
        details.extend(f"BLOCKED: {item}" for item in blocked[:12])
        return GateOutcome(
            name=_SCHEMATIC_CONNECTIVITY_GATE,
            status="BLOCKED",
            summary="Connectivity checks could not complete for every sheet.",
            details=details,
        )
    if failures:
        details.extend(f"FAIL: {item}" for item in failures[:20])
        return GateOutcome(
            name=_SCHEMATIC_CONNECTIVITY_GATE,
            status="FAIL",
            summary=(
                "Connectivity smells suggest the schematic is not ready for PCB or release work."
            ),
            details=details,
        )
    return GateOutcome(
        name=_SCHEMATIC_CONNECTIVITY_GATE,
        status="PASS",
        summary="Connectivity structure looks consistent across the active schematic set.",
        details=details,
    )


def _evaluate_schematic_design_rule_gate() -> GateOutcome:
    """Check the schematic against professional electrical-design rules (advisory).

    Goes beyond ERC connectivity: flags supply rails that feed ICs without a
    decoupling capacitor and I2C buses without pull-up resistors. Advisory by
    design — findings are surfaced as WARN, not a hard release blocker.
    """
    from ..utils.schematic_rules import run_schematic_design_rules
    from .schematic import _build_connectivity_groups, _iter_child_sheet_paths

    try:
        top_file = _get_sch_file()
    except ValueError as exc:
        return GateOutcome(name=_SCHEMATIC_DESIGN_RULES_GATE, status="BLOCKED", summary=str(exc))

    pages: list[tuple[str, Path]] = [(_TOP_LEVEL_SHEET, top_file)]
    notes: list[str] = []
    try:
        pages.extend(_iter_child_sheet_paths(top_file))
    except Exception as exc:  # pragma: no cover - sheet discovery is best-effort
        notes.append(f"Child-sheet discovery skipped ({exc}); analysed top sheet only.")

    all_nets: list[dict[str, object]] = []
    for page_name, page_path in pages:
        if not page_path.exists():
            continue
        try:
            all_nets.extend(_build_connectivity_groups(page_path))
        except (OSError, RuntimeError, ValueError) as exc:
            notes.append(f"{page_name}: connectivity data unavailable ({exc}).")

    if notes and not all_nets:
        return GateOutcome(
            name=_SCHEMATIC_DESIGN_RULES_GATE,
            status="BLOCKED",
            summary="Design-rule checks could not read the schematic connectivity.",
            details=notes,
        )

    findings = run_schematic_design_rules(all_nets)
    details = [f"Pages analysed: {len(pages)}", f"Findings: {len(findings)}"]
    details.extend(
        f"{finding.severity.upper()} [{finding.rule_id}] {finding.message}"
        for finding in findings[:30]
    )
    details.extend(f"NOTE: {note}" for note in notes[:6])

    if not findings:
        return GateOutcome(
            name=_SCHEMATIC_DESIGN_RULES_GATE,
            status="PASS",
            summary="No electrical-design-rule issues detected.",
            details=details,
        )
    return GateOutcome(
        name=_SCHEMATIC_DESIGN_RULES_GATE,
        status="WARN",
        summary=(
            f"{len(findings)} electrical-design-rule advisory finding(s); "
            "review before PCB or release work."
        ),
        details=details,
    )


def _evaluate_pre_sync_gate() -> GateOutcome:
    """Validate that schematic state is safe to transfer into PCB footprints."""
    outcomes = [_evaluate_schematic_gate(), _evaluate_schematic_connectivity_gate()]
    blocking = [outcome for outcome in outcomes if outcome.status != "PASS"]
    if blocking:
        details: list[str] = []
        for outcome in blocking:
            details.append(f"{outcome.name} quality gate: {outcome.status}")
            details.append(outcome.summary)
            details.extend(outcome.details[:6])
        return GateOutcome(
            name="Pre-sync",
            status="FAIL",
            summary=(
                "Schematic checks must pass before PCB sync to avoid transferring "
                "a stale or broken netlist."
            ),
            details=details,
        )
    return GateOutcome(
        name="Pre-sync",
        status="PASS",
        summary="Schematic is ready for PCB sync.",
        details=["ERC/connectivity blockers: 0"],
    )


def _evaluate_pcb_gate() -> GateOutcome:
    _, report, error = _run_drc_report("pcb_quality_gate.json")
    if report is None:
        return GateOutcome(
            name="PCB",
            status="BLOCKED",
            summary=f"DRC report was unavailable ({error or 'unknown error'}).",
        )

    violations = _entries(report, "violations")
    unconnected = _entries(report, "unconnected_items")
    courtyard = courtyard_violations(report)
    legacy_only_courtyard = [entry for entry in courtyard if entry not in violations]
    blocking_count = len(violations) + len(unconnected) + len(legacy_only_courtyard)
    status: GateStatus = "PASS" if blocking_count == 0 else "FAIL"
    details = [
        f"DRC violations: {len(violations)}",
        f"Unconnected items: {len(unconnected)}",
        f"Courtyard issues: {len(courtyard)}",
    ]
    if violations:
        details.append(f"DRC types: {_type_breakdown(violations)}")
    return GateOutcome(
        name="PCB",
        status=status,
        summary="PCB passes DRC, unconnected, and courtyard checks."
        if status == "PASS"
        else "PCB still has blocking physical-rule issues.",
        details=details,
    )


def _nearest_edge_distance(
    entry: dict[str, object],
    frame: tuple[float, float, float, float],
) -> float | None:
    if entry["x_mm"] is None or entry["y_mm"] is None:
        return None
    min_x, min_y, max_x, max_y = frame
    x_mm = float(cast(float, entry["x_mm"]))
    y_mm = float(cast(float, entry["y_mm"]))
    width_mm = float(cast(float, entry["width_mm"]))
    height_mm = float(cast(float, entry["height_mm"]))
    return min(
        x_mm - (width_mm / 2) - min_x,
        max_x - (x_mm + (width_mm / 2)),
        y_mm - (height_mm / 2) - min_y,
        max_y - (y_mm + (height_mm / 2)),
    )


def _entry_center(entry: dict[str, object]) -> tuple[float, float] | None:
    if entry["x_mm"] is None or entry["y_mm"] is None:
        return None
    return float(cast(float, entry["x_mm"])), float(cast(float, entry["y_mm"]))


def _bbox_gap_mm(left_entry: dict[str, object], right_entry: dict[str, object]) -> float | None:
    left_center = _entry_center(left_entry)
    right_center = _entry_center(right_entry)
    if left_center is None or right_center is None:
        return None
    left_x, left_y = left_center
    right_x, right_y = right_center
    left_w = float(cast(float, left_entry["width_mm"]))
    left_h = float(cast(float, left_entry["height_mm"]))
    right_w = float(cast(float, right_entry["width_mm"]))
    right_h = float(cast(float, right_entry["height_mm"]))
    gap_x = abs(left_x - right_x) - ((left_w + right_w) / 2.0)
    gap_y = abs(left_y - right_y) - ((left_h + right_h) / 2.0)
    return max(max(gap_x, 0.0), max(gap_y, 0.0))


def _group_spread_mm(
    refs: list[str],
    footprints: dict[str, dict[str, object]],
) -> tuple[float, list[str]]:
    present_refs = [
        reference
        for reference in refs
        if reference in footprints and _entry_center(footprints[reference]) is not None
    ]
    if len(present_refs) < 2:
        return 0.0, present_refs
    max_spread = 0.0
    for index, left_ref in enumerate(present_refs):
        left_center = _entry_center(footprints[left_ref])
        if left_center is None:
            continue
        for right_ref in present_refs[index + 1 :]:
            right_center = _entry_center(footprints[right_ref])
            if right_center is None:
                continue
            max_spread = max(
                max_spread,
                math.hypot(left_center[0] - right_center[0], left_center[1] - right_center[1]),
            )
    return max_spread, present_refs


def _manhattan_mst_length(points: list[tuple[float, float]]) -> float:
    """Approximate a ratsnest length using Manhattan-distance MST wiring."""
    if len(points) < 2:
        return 0.0

    visited = {0}
    total = 0.0
    while len(visited) < len(points):
        best_distance: float | None = None
        best_index: int | None = None
        for left_index in visited:
            left_point = points[left_index]
            for right_index, right_point in enumerate(points):
                if right_index in visited:
                    continue
                distance = abs(left_point[0] - right_point[0]) + abs(left_point[1] - right_point[1])
                if best_distance is None or distance < best_distance:
                    best_distance = distance
                    best_index = right_index
        if best_distance is None or best_index is None:
            break
        visited.add(best_index)
        total += best_distance
    return total


@dataclass(frozen=True)
class _PlacementScoreInputs:
    overlaps: list[str]
    outside: list[str]
    connector_edge_violations: list[str]
    decoupling_distance_violations: list[str]
    keepout_violations: list[str]
    power_tree_violations: list[str]
    sensor_cluster_violations: list[str]
    analog_digital_violations: list[str]
    warnings: list[str]
    thermal_proximity_sum: float
    critical_net_proxy_density: float
    hs_grouping_violations: list[str]
    mount_hole_violations: list[str]
    connector_edge_spec_violations: list[str]


class _PlacementEvaluator:
    """Evaluate PCB placement quality, design intent rules, and mechanical constraints."""

    def __init__(
        self,
        content: str,
        footprints: dict[str, dict[str, Any]],
        intent: ProjectDesignIntent,
    ) -> None:
        from .board_file import _board_frame_mm

        self.content = content
        self.footprints = footprints
        self.intent = intent
        self.min_x, self.min_y, self.max_x, self.max_y = _board_frame_mm(content, footprints)
        self.frame = (self.min_x, self.min_y, self.max_x, self.max_y)
        self.board_width_mm = self.max_x - self.min_x
        self.board_height_mm = self.max_y - self.min_y
        self.board_area_mm2 = max(self.board_width_mm * self.board_height_mm, 1.0)
        self.board_diagonal = math.hypot(self.board_width_mm, self.board_height_mm)
        self.footprint_area_mm2 = sum(
            float(entry["width_mm"]) * float(entry["height_mm"]) for entry in footprints.values()
        )
        self.density_pct = round((self.footprint_area_mm2 / self.board_area_mm2) * 100.0, 2)
        self.warnings: list[str] = []

    def _is_outside_frame(self, x: float, y: float, w: float, h: float) -> bool:
        half_w = w / 2.0
        half_h = h / 2.0
        return (
            x - half_w < self.min_x
            or x + half_w > self.max_x
            or y - half_h < self.min_y
            or y + half_h > self.max_y
        )

    def _collect_pair_overlaps(
        self,
        index: int,
        left_ref: str,
        left_box: tuple[float, float, float, float],
        items: list[tuple[str, dict[str, Any]]],
    ) -> list[str]:
        from .board_file import _placement_boxes_overlap

        lx, ly, lw, lh = left_box
        overlaps: list[str] = []
        for right_ref, right_entry in items[index + 1 :]:
            if right_entry["x_mm"] is None or right_entry["y_mm"] is None:
                continue
            if _placement_boxes_overlap(
                lx,
                ly,
                lw,
                lh,
                float(right_entry["x_mm"]),
                float(right_entry["y_mm"]),
                float(right_entry["width_mm"]),
                float(right_entry["height_mm"]),
                0.0,
            ):
                overlaps.append(f"{left_ref}/{right_ref}")
        return overlaps

    @staticmethod
    def _courtyard_bounds(entry: dict[str, Any]) -> tuple[float, float, float, float]:
        measured = entry.get("courtyard_bounds_mm")
        if measured is not None:
            return cast(tuple[float, float, float, float], measured)
        # Legacy fallback for footprints without supported courtyard graphics.
        x = float(entry["x_mm"])
        y = float(entry["y_mm"])
        half_w = float(entry["width_mm"]) / 2
        half_h = float(entry["height_mm"]) / 2
        return x - half_w, y - half_h, x + half_w, y + half_h

    def _classify_outside_courtyard(
        self,
        reference: str,
        entry: dict[str, Any],
        box: tuple[float, float, float, float],
        outside: list[str],
    ) -> None:
        lx0, ly0, lx1, ly1 = box
        if not (lx0 < self.min_x or lx1 > self.max_x or ly0 < self.min_y or ly1 > self.max_y):
            return
        name = str(entry.get("name", ""))
        if reference.startswith("J") and name.startswith(("Connector", "TerminalBlock")):
            self.warnings.append(
                f"Connector '{reference}' courtyard crosses board edge; "
                "verify intentional shell/plug overhang and mating."
            )
        else:
            outside.append(reference)

    @classmethod
    def _courtyard_overlaps_with_later(
        cls,
        reference: str,
        left_box: tuple[float, float, float, float],
        later: list[tuple[str, dict[str, Any]]],
    ) -> list[str]:
        lx0, ly0, lx1, ly1 = left_box
        overlaps: list[str] = []
        for right_ref, right_entry in later:
            if right_entry["x_mm"] is None or right_entry["y_mm"] is None:
                continue
            rx0, ry0, rx1, ry1 = cls._courtyard_bounds(right_entry)
            if lx0 < rx1 and rx0 < lx1 and ly0 < ry1 and ry0 < ly1:
                overlaps.append(f"{reference}/{right_ref}")
        return overlaps

    def _evaluate_geometry_and_overlaps(self) -> tuple[list[str], list[str], list[str]]:
        missing_position = [
            reference
            for reference, entry in self.footprints.items()
            if entry["x_mm"] is None or entry["y_mm"] is None
        ]
        overlaps: list[str] = []
        outside: list[str] = []
        items = sorted(self.footprints.items())
        for index, (left_ref, left_entry) in enumerate(items):
            if left_entry["x_mm"] is None or left_entry["y_mm"] is None:
                continue
            box = self._courtyard_bounds(left_entry)
            self._classify_outside_courtyard(left_ref, left_entry, box, outside)
            overlaps.extend(self._courtyard_overlaps_with_later(left_ref, box, items[index + 1 :]))
        return missing_position, overlaps, outside

    def _evaluate_connectors(self) -> tuple[list[str], int]:
        connector_edge_violations: list[str] = []
        checked_connectors = 0
        for reference in self.intent.connector_refs:
            entry = self.footprints.get(reference)
            if entry is None:
                connector_edge_violations.append(f"Connector intent ref '{reference}' is missing.")
                continue
            checked_connectors += 1
            distance = _nearest_edge_distance(entry, self.frame)
            if distance is None:
                connector_edge_violations.append(
                    f"Connector '{reference}' has no resolved placement to evaluate."
                )
                continue
            if distance > 5.0:
                connector_edge_violations.append(
                    f"Connector '{reference}' is {distance:.2f} mm from the nearest edge."
                )
        return connector_edge_violations, checked_connectors

    @staticmethod
    def _matching_supply_pad_distance(
        ic_entry: dict[str, Any], cap_entry: dict[str, Any]
    ) -> float | None:
        """Measure a same-net power pad pair; ground-only matches are excluded."""
        ic_pads = ic_entry.get("pad_positions_mm", ())
        cap_pads = cap_entry.get("pad_positions_mm", ())
        matches: list[float] = []
        for left in ic_pads:
            net = str(left["net"]).lstrip("/").upper()
            if (
                not net
                or "GND" in net
                or "VSS" in net
                or net.startswith("UNCONNECTED-(")
                or not (
                    (rail_voltage(net) or 0) > 0
                    or net
                    in {
                        "VBUS",
                        "USB_VBUS",
                        "VBAT",
                        "VDD",
                        "VCC",
                        "VDDA",
                        "VCORE",
                        "VIN",
                        "VREF",
                        "VCCIO",
                        "AVDD",
                        "DVDD",
                    }
                )
            ):
                continue
            for right in cap_pads:
                if net != str(right["net"]).lstrip("/").upper():
                    continue
                matches.append(
                    math.hypot(
                        float(left["x_mm"]) - float(right["x_mm"]),
                        float(left["y_mm"]) - float(right["y_mm"]),
                    )
                )
        return min(matches) if matches else None

    def _evaluate_decoupling_pair(
        self,
        pair: DecouplingPairIntent,
        ic_entry: dict[str, Any],
    ) -> list[str]:
        """Fail for missing capacitors, but never fail on a centroid-only proxy."""
        violations: list[str] = []
        cap_distances: list[float] = []
        matched_pad_distances: list[float] = []
        missing_caps: list[str] = []
        for cap_ref in pair.cap_refs:
            cap_entry = self.footprints.get(cap_ref)
            if cap_entry is None or cap_entry["x_mm"] is None or cap_entry["y_mm"] is None:
                missing_caps.append(cap_ref)
                continue
            cap_distances.append(
                math.hypot(
                    float(ic_entry["x_mm"]) - float(cap_entry["x_mm"]),
                    float(ic_entry["y_mm"]) - float(cap_entry["y_mm"]),
                )
            )
            pad_distance = self._matching_supply_pad_distance(ic_entry, cap_entry)
            if pad_distance is not None:
                matched_pad_distances.append(pad_distance)
        if missing_caps:
            violations.append(
                f"{pair.ic_ref}: missing or unresolved decoupling caps -> "
                + ", ".join(missing_caps[:12])
            )
        if matched_pad_distances:
            nearest = min(matched_pad_distances)
            if nearest > pair.max_distance_mm:
                self.warnings.append(
                    f"{pair.ic_ref}: nearest same-supply-net power-pad to decoupling-pad "
                    f"distance is {nearest:.2f} mm (intent limit {pair.max_distance_mm:.2f} mm); "
                    "physical copper path, return loop and device guidance require review."
                )
        elif cap_distances:
            self.warnings.append(
                f"{pair.ic_ref}: nearest decoupling cap is {min(cap_distances):.2f} mm "
                f"by footprint-center proxy (intent limit {pair.max_distance_mm:.2f} mm); "
                "power-pad geometry unavailable, cannot infer the decoupling loop."
            )
        return violations

    def _evaluate_decoupling(self) -> tuple[list[str], int]:
        decoupling_distance_violations: list[str] = []
        checked_decoupling_pairs = 0
        for pair in self.intent.decoupling_pairs:
            ic_entry = self.footprints.get(pair.ic_ref)
            if ic_entry is None:
                decoupling_distance_violations.append(
                    f"Decoupling IC ref '{pair.ic_ref}' is missing on the board."
                )
                continue
            if ic_entry["x_mm"] is None or ic_entry["y_mm"] is None:
                decoupling_distance_violations.append(
                    f"Decoupling IC ref '{pair.ic_ref}' has no resolved placement."
                )
                continue
            checked_decoupling_pairs += 1
            decoupling_distance_violations.extend(self._evaluate_decoupling_pair(pair, ic_entry))
        return decoupling_distance_violations, checked_decoupling_pairs

    def _evaluate_keepouts(self) -> tuple[list[str], int]:
        from .board_file import _placement_boxes_overlap

        keepout_violations: list[str] = []
        checked_keepouts = 0
        for region in self.intent.rf_keepout_regions:
            checked_keepouts += 1
            for reference, entry in self.footprints.items():
                if entry["x_mm"] is None or entry["y_mm"] is None:
                    continue
                if _placement_boxes_overlap(
                    float(entry["x_mm"]),
                    float(entry["y_mm"]),
                    float(entry["width_mm"]),
                    float(entry["height_mm"]),
                    region.x_mm,
                    region.y_mm,
                    region.w_mm,
                    region.h_mm,
                    0.0,
                ):
                    keepout_violations.append(f"{reference} overlaps RF keepout '{region.name}'.")
        return keepout_violations, checked_keepouts

    def _evaluate_power_tree(self) -> tuple[list[str], int]:
        power_tree_violations: list[str] = []
        checked_power_tree_refs = 0
        present_power_tree: list[str] = []
        for reference in self.intent.power_tree_refs:
            entry = self.footprints.get(reference)
            if entry is None:
                power_tree_violations.append(f"Power-tree intent ref '{reference}' is missing.")
                continue
            if _entry_center(entry) is None:
                power_tree_violations.append(
                    f"Power-tree intent ref '{reference}' has no resolved placement."
                )
                continue
            checked_power_tree_refs += 1
            present_power_tree.append(reference)
        for left_ref, right_ref in zip(present_power_tree, present_power_tree[1:], strict=False):
            left_center = _entry_center(self.footprints[left_ref])
            right_center = _entry_center(self.footprints[right_ref])
            if left_center is None or right_center is None:
                continue
            step_distance = math.hypot(
                left_center[0] - right_center[0],
                left_center[1] - right_center[1],
            )
            if step_distance > self.board_diagonal * 0.75:
                power_tree_violations.append(
                    f"Power-tree step '{left_ref} -> {right_ref}' spans {step_distance:.2f} mm."
                )
            elif step_distance > self.board_diagonal * 0.5:
                self.warnings.append(
                    f"Power-tree step '{left_ref} -> {right_ref}' spans {step_distance:.2f} mm."
                )
        return power_tree_violations, checked_power_tree_refs

    def _evaluate_sensor_clusters(self) -> tuple[list[str], int]:
        sensor_cluster_violations: list[str] = []
        missing_sensor_refs = [
            reference
            for reference in self.intent.sensor_cluster_refs
            if reference not in self.footprints or _entry_center(self.footprints[reference]) is None
        ]
        if missing_sensor_refs:
            sensor_cluster_violations.append(
                "Sensor-cluster refs missing or unresolved: " + ", ".join(missing_sensor_refs[:12])
            )
        sensor_cluster_spread, present_sensor_refs = _group_spread_mm(
            self.intent.sensor_cluster_refs,
            self.footprints,
        )
        checked_sensor_cluster_refs = len(present_sensor_refs)
        if checked_sensor_cluster_refs >= 2:
            if sensor_cluster_spread > self.board_diagonal * 0.6:
                sensor_cluster_violations.append(
                    f"Sensor cluster spreads {sensor_cluster_spread:.2f} mm across the board."
                )
            elif sensor_cluster_spread > self.board_diagonal * 0.35:
                self.warnings.append(
                    f"Sensor cluster spreads {sensor_cluster_spread:.2f} mm across the board."
                )
        return sensor_cluster_violations, checked_sensor_cluster_refs

    def _find_nearest_mixed_gap(
        self,
        analog_refs: list[str],
        digital_refs: list[str],
    ) -> tuple[float, str, str] | None:
        nearest_mixed_gap: tuple[float, str, str] | None = None
        for analog_ref in analog_refs:
            analog_entry = self.footprints[analog_ref]
            for digital_ref in digital_refs:
                digital_entry = self.footprints[digital_ref]
                gap = _bbox_gap_mm(analog_entry, digital_entry)
                if gap is None:
                    continue
                candidate = (gap, analog_ref, digital_ref)
                if nearest_mixed_gap is None or candidate[0] < nearest_mixed_gap[0]:
                    nearest_mixed_gap = candidate
        return nearest_mixed_gap

    def _evaluate_analog_digital(self) -> tuple[list[str], int, int]:
        analog_digital_violations: list[str] = []
        analog_refs = [
            r
            for r in self.intent.analog_refs
            if r in self.footprints and _entry_center(self.footprints[r]) is not None
        ]
        digital_refs = [
            r
            for r in self.intent.digital_refs
            if r in self.footprints and _entry_center(self.footprints[r]) is not None
        ]
        nearest_mixed_gap = self._find_nearest_mixed_gap(analog_refs, digital_refs)
        if nearest_mixed_gap is not None:
            gap, analog_ref, digital_ref = nearest_mixed_gap
            msg = (
                f"Analog ref '{analog_ref}' is only {gap:.2f} mm away from digital ref "
                f"'{digital_ref}'."
            )
            if gap < 1.0:
                analog_digital_violations.append(msg)
            elif gap < 3.0:
                self.warnings.append(msg)
        return analog_digital_violations, len(analog_refs), len(digital_refs)

    def _evaluate_clustering_and_density(self) -> None:
        if self.density_pct > 70.0:
            self.warnings.append(f"Footprint density is high ({self.density_pct:.2f}%).")
        elif self.density_pct < 5.0 and len(self.footprints) >= 6:
            self.warnings.append(f"Footprint density is sparse ({self.density_pct:.2f}%).")

        placed_x = [
            float(entry["x_mm"]) for entry in self.footprints.values() if entry["x_mm"] is not None
        ]
        placed_y = [
            float(entry["y_mm"]) for entry in self.footprints.values() if entry["y_mm"] is not None
        ]
        if len(placed_x) >= 2 and len(placed_y) >= 2:
            span_x = max(placed_x) - min(placed_x)
            span_y = max(placed_y) - min(placed_y)
            if len(self.footprints) >= 6 and (
                span_x > self.board_width_mm * 0.7 or span_y > self.board_height_mm * 0.7
            ):
                self.warnings.append("Placement spans most of the board; clustering looks weak.")

    def _evaluate_critical_nets(self) -> tuple[float, float]:
        critical_net_proxy_mm = 0.0
        for net_name in self.intent.critical_nets:
            refs = sorted(
                reference
                for reference, entry in self.footprints.items()
                if net_name in cast(list[str], entry.get("net_names", []))
                and entry["x_mm"] is not None
                and entry["y_mm"] is not None
            )
            if len(refs) < 2:
                continue
            points = [
                (
                    float(cast(float, self.footprints[ref]["x_mm"])),
                    float(cast(float, self.footprints[ref]["y_mm"])),
                )
                for ref in refs
            ]
            critical_net_proxy_mm += _manhattan_mst_length(points)
            max_spread = 0.0
            for index, left_ref in enumerate(refs):
                left_entry = self.footprints[left_ref]
                for right_ref in refs[index + 1 :]:
                    right_entry = self.footprints[right_ref]
                    max_spread = max(
                        max_spread,
                        math.hypot(
                            float(left_entry["x_mm"]) - float(right_entry["x_mm"]),
                            float(left_entry["y_mm"]) - float(right_entry["y_mm"]),
                        ),
                    )
            if max_spread > self.board_diagonal * 0.6:
                self.warnings.append(
                    f"Critical net '{net_name}' spans {max_spread:.2f} mm across the board."
                )

        density = round(
            critical_net_proxy_mm / max(self.board_area_mm2 / 1000.0, 1.0),
            2,
        )
        if density > 80.0:
            self.warnings.append(
                "Critical nets require a long Manhattan ratsnest relative to board area "
                f"({density:.2f} mm per 1000 mm^2)."
            )
        return round(critical_net_proxy_mm, 2), density

    def _evaluate_thermal_hotspots(self) -> tuple[list[str], float]:
        thermal_hotspot_refs = [
            reference
            for reference in self.intent.thermal_hotspots
            if reference in self.footprints
            and _entry_center(self.footprints[reference]) is not None
        ]
        thermal_proximity_sum = 0.0
        for index, left_ref in enumerate(thermal_hotspot_refs):
            left_center = _entry_center(self.footprints[left_ref])
            if left_center is None:
                continue
            for right_ref in thermal_hotspot_refs[index + 1 :]:
                right_center = _entry_center(self.footprints[right_ref])
                if right_center is None:
                    continue
                distance = max(
                    math.hypot(left_center[0] - right_center[0], left_center[1] - right_center[1]),
                    0.5,
                )
                thermal_proximity_sum += 1.0 / distance
        if (
            thermal_hotspot_refs
            and thermal_proximity_sum > max(len(thermal_hotspot_refs) - 1, 1) * 0.2
        ):
            self.warnings.append(
                "Thermal hotspots are clustered tightly "
                f"(proximity sum {thermal_proximity_sum:.3f})."
            )
        return thermal_hotspot_refs, round(thermal_proximity_sum, 4)

    def _interface_spread(self, valid_centers: list[tuple[float, float]]) -> float:
        max_spread = 0.0
        for idx_a, ca in enumerate(valid_centers):
            for cb in valid_centers[idx_a + 1 :]:
                d = math.hypot(ca[0] - cb[0], ca[1] - cb[1])
                if d > max_spread:
                    max_spread = d
        return max_spread

    def _evaluate_high_speed(self) -> tuple[list[str], list[str], int]:
        hs_grouping_violations: list[str] = []
        return_path_warnings: list[str] = []
        checked_hs_interfaces = 0
        for iface in self.intent.interfaces:
            present_refs = [r for r in iface.refs if r in self.footprints]
            if len(present_refs) < 2:
                continue
            checked_hs_interfaces += 1
            centers = [_entry_center(self.footprints[r]) for r in present_refs]
            valid_centers = [c for c in centers if c is not None]
            if len(valid_centers) < 2:
                continue
            max_spread = self._interface_spread(valid_centers)
            limit_hard = self.board_diagonal * 0.5
            limit_warn = self.board_diagonal * 0.3
            iface_label = f"{iface.kind} ({', '.join(present_refs[:4])})"
            if max_spread > limit_hard:
                hs_grouping_violations.append(
                    f"High-speed interface {iface_label} spans {max_spread:.1f} mm "
                    f"(limit {limit_hard:.1f} mm) — return current path will be long."
                )
            elif max_spread > limit_warn:
                return_path_warnings.append(
                    f"High-speed interface {iface_label} spans {max_spread:.1f} mm "
                    f"(warn {limit_warn:.1f} mm) — consider tighter grouping."
                )
        return hs_grouping_violations, return_path_warnings, checked_hs_interfaces

    def _evaluate_mount_holes(self) -> list[str]:
        violations: list[str] = []
        for hole in self.intent.mechanical.mount_holes:
            clearance_mm = max(hole.diameter_mm, 2.0)
            for reference, entry in self.footprints.items():
                center = _entry_center(entry)
                if center is None:
                    continue
                dist = math.hypot(center[0] - hole.x_mm, center[1] - hole.y_mm)
                footprint_radius = math.hypot(
                    float(entry.get("width_mm", 0.0)) / 2,
                    float(entry.get("height_mm", 0.0)) / 2,
                )
                if dist < clearance_mm + footprint_radius:
                    violations.append(
                        f"'{reference}' is {dist:.1f} mm from mount hole at "
                        f"({hole.x_mm:.1f}, {hole.y_mm:.1f}) — clearance {clearance_mm:.1f} mm "
                        f"required."
                    )
        return violations

    def _dist_to_edge(self, cx: float, cy: float, edge: str) -> float:
        if edge == "top":
            return abs(cy - self.min_y)
        if edge == "bottom":
            return abs(cy - self.max_y)
        if edge == "left":
            return abs(cx - self.min_x)
        return abs(cx - self.max_x)

    def _has_rectangular_outline(self) -> bool:
        """Mechanical intent needs one actual rectangle, not inferred PCB bounds."""
        from ..utils.sexpr import _extract_block

        primitives: list[str] = []
        for found in re.finditer(r"\(gr_(?:rect|line|arc|circle|poly|curve)\b", self.content):
            block, _ = _extract_block(self.content, found.start())
            if block and '(layer "Edge.Cuts")' in block:
                primitives.append(found.group().removeprefix("("))
        return primitives == ["gr_rect"] and self.max_x > self.min_x and self.max_y > self.min_y

    def _evaluate_connector_edge_specs(self) -> list[str]:
        violations: list[str] = []
        for edge_spec in self.intent.mechanical.connector_placement:
            edge_entry = self.footprints.get(edge_spec.ref)
            if edge_entry is None:
                continue
            center = _entry_center(edge_entry)
            if center is None:
                continue
            dist_to_edge = self._dist_to_edge(center[0], center[1], edge_spec.edge)
            if dist_to_edge > edge_spec.margin_mm:
                violations.append(
                    f"Connector '{edge_spec.ref}' is {dist_to_edge:.1f} mm from the "
                    f"{edge_spec.edge} edge (limit {edge_spec.margin_mm:.1f} mm)."
                )
        if self.intent.mechanical.connector_mating:
            rectangular = self._has_rectangular_outline()
            for spec in self.intent.mechanical.connector_mating:
                violations.extend(
                    evaluate_connector_mating(
                        spec,
                        self.footprints.get(spec.ref),
                        self.frame,
                        rectangular_outline_verified=rectangular,
                    )
                )
        return violations

    def _evaluate_mechanical(self) -> tuple[list[str], list[str]]:
        return self._evaluate_mount_holes(), self._evaluate_connector_edge_specs()

    def _calculate_score(self, inputs: _PlacementScoreInputs) -> int:
        score = 100
        score -= min(len(inputs.overlaps) * 20, 40)
        score -= min(len(inputs.outside) * 20, 40)
        score -= min(len(inputs.connector_edge_violations) * 15, 30)
        score -= min(len(inputs.decoupling_distance_violations) * 15, 30)
        score -= min(len(inputs.keepout_violations) * 15, 30)
        score -= min(len(inputs.power_tree_violations) * 15, 30)
        score -= min(len(inputs.sensor_cluster_violations) * 15, 30)
        score -= min(len(inputs.analog_digital_violations) * 15, 30)
        score -= min(len(inputs.warnings) * 5, 20)
        score -= min(int(round(inputs.thermal_proximity_sum * 10.0)), 10)
        score -= min(int(inputs.critical_net_proxy_density // 20), 10)
        score -= min(len(inputs.hs_grouping_violations) * 10, 20)
        score -= min(len(inputs.mount_hole_violations) * 10, 20)
        score -= min(len(inputs.connector_edge_spec_violations) * 10, 20)
        return max(score, 0)

    def evaluate(self) -> PlacementAnalysis:
        missing_position, overlaps, outside = self._evaluate_geometry_and_overlaps()
        connector_edge_violations, checked_connectors = self._evaluate_connectors()
        decoupling_distance_violations, checked_decoupling_pairs = self._evaluate_decoupling()
        keepout_violations, checked_keepouts = self._evaluate_keepouts()
        power_tree_violations, checked_power_tree_refs = self._evaluate_power_tree()
        sensor_cluster_violations, checked_sensor_cluster_refs = self._evaluate_sensor_clusters()
        analog_digital_violations, checked_analog_refs, checked_digital_refs = (
            self._evaluate_analog_digital()
        )
        self._evaluate_clustering_and_density()
        critical_net_proxy_mm, critical_net_proxy_density = self._evaluate_critical_nets()
        thermal_hotspot_refs, thermal_proximity_sum = self._evaluate_thermal_hotspots()
        hs_grouping_violations, return_path_warnings, checked_hs_interfaces = (
            self._evaluate_high_speed()
        )
        mount_hole_violations, connector_edge_spec_violations = self._evaluate_mechanical()

        hard_failures: list[str] = []
        if missing_position:
            hard_failures.append("Missing positions: " + ", ".join(missing_position[:20]))
        if overlaps:
            hard_failures.append("Overlap refs: " + ", ".join(overlaps[:20]))
        if outside:
            hard_failures.append("Outside-board refs: " + ", ".join(outside[:20]))
        hard_failures.extend(connector_edge_violations)
        hard_failures.extend(decoupling_distance_violations)
        hard_failures.extend(keepout_violations)
        hard_failures.extend(power_tree_violations)
        hard_failures.extend(sensor_cluster_violations)
        hard_failures.extend(analog_digital_violations)
        hard_failures.extend(hs_grouping_violations)
        hard_failures.extend(mount_hole_violations)
        hard_failures.extend(connector_edge_spec_violations)
        warnings = list(self.warnings)
        warnings.extend(return_path_warnings)

        score = self._calculate_score(
            _PlacementScoreInputs(
                overlaps=overlaps,
                outside=outside,
                connector_edge_violations=connector_edge_violations,
                decoupling_distance_violations=decoupling_distance_violations,
                keepout_violations=keepout_violations,
                power_tree_violations=power_tree_violations,
                sensor_cluster_violations=sensor_cluster_violations,
                analog_digital_violations=analog_digital_violations,
                warnings=warnings,
                thermal_proximity_sum=thermal_proximity_sum,
                critical_net_proxy_density=critical_net_proxy_density,
                hs_grouping_violations=hs_grouping_violations,
                mount_hole_violations=mount_hole_violations,
                connector_edge_spec_violations=connector_edge_spec_violations,
            )
        )

        return PlacementAnalysis(
            footprint_count=len(self.footprints),
            board_width_mm=self.board_width_mm,
            board_height_mm=self.board_height_mm,
            board_area_mm2=self.board_area_mm2,
            footprint_area_mm2=self.footprint_area_mm2,
            density_pct=self.density_pct,
            score=score,
            hard_failures=hard_failures,
            warnings=warnings,
            checked_connectors=checked_connectors,
            checked_decoupling_pairs=checked_decoupling_pairs,
            checked_keepouts=checked_keepouts,
            checked_power_tree_refs=checked_power_tree_refs,
            checked_analog_refs=checked_analog_refs,
            checked_digital_refs=checked_digital_refs,
            checked_sensor_cluster_refs=checked_sensor_cluster_refs,
            critical_net_proxy_mm=critical_net_proxy_mm,
            critical_net_proxy_density=critical_net_proxy_density,
            checked_thermal_hotspot_refs=len(thermal_hotspot_refs),
            thermal_proximity_sum=thermal_proximity_sum,
            checked_hs_interfaces=checked_hs_interfaces,
            hs_grouping_violations=hs_grouping_violations,
            return_path_warnings=return_path_warnings,
            mount_hole_violations=mount_hole_violations,
            connector_edge_spec_violations=connector_edge_spec_violations,
        )


def _placement_analysis() -> tuple[PlacementAnalysis | None, GateOutcome | None]:
    from .board_file import _normalize_board_content, _parse_board_footprint_blocks
    from .design_intent_state import ProjectDesignIntent, resolve_design_intent

    try:
        content = _normalize_board_content(
            _get_pcb_file().read_text(encoding="utf-8", errors="ignore")
        )
    except OSError as exc:
        return None, GateOutcome(
            name="Placement",
            status="BLOCKED",
            summary=f"PCB file could not be read ({exc}).",
        )

    footprints = _parse_board_footprint_blocks(content)
    if not footprints:
        return None, GateOutcome(
            name="Placement",
            status="BLOCKED",
            summary="No PCB footprints were found to evaluate.",
        )

    try:
        intent = resolve_design_intent().resolved
    except ValueError:
        intent = ProjectDesignIntent()

    return _PlacementEvaluator(content, footprints, intent).evaluate(), None


def _format_placement_score(analysis: PlacementAnalysis) -> str:
    lines = [
        f"Placement score: {analysis.score}/100",
    ]
    if analysis.score_before is not None:
        delta = analysis.score - analysis.score_before
        sign = "+" if delta >= 0 else ""
        lines.append(f"- Score before auto-placement: {analysis.score_before}/100 ({sign}{delta})")
    lines += [
        f"- Footprints analysed: {analysis.footprint_count}",
        f"- Board frame: {analysis.board_width_mm:.2f} x {analysis.board_height_mm:.2f} mm",
        f"- Density: {analysis.density_pct:.2f}%",
        f"- Connector checks: {analysis.checked_connectors}",
        f"- Decoupling pair checks: {analysis.checked_decoupling_pairs}",
        f"- RF keepout checks: {analysis.checked_keepouts}",
        f"- Power-tree refs checked: {analysis.checked_power_tree_refs}",
        f"- Analog refs checked: {analysis.checked_analog_refs}",
        f"- Digital refs checked: {analysis.checked_digital_refs}",
        f"- Sensor-cluster refs checked: {analysis.checked_sensor_cluster_refs}",
        f"- Critical-net Manhattan proxy: {analysis.critical_net_proxy_mm:.2f} mm",
        f"- Critical-net proxy density: {analysis.critical_net_proxy_density:.2f} mm per 1000 mm^2",
        f"- Thermal hotspot refs checked: {analysis.checked_thermal_hotspot_refs}",
        f"- Thermal hotspot proximity: {analysis.thermal_proximity_sum:.4f}",
        f"- High-speed interfaces checked: {analysis.checked_hs_interfaces}",
        f"- Mount-hole clearance checks: {len(analysis.mount_hole_violations)}",
        f"- Connector edge-spec checks: {len(analysis.connector_edge_spec_violations)}",
        f"- Hard failures: {len(analysis.hard_failures)}",
        f"- Warnings: {len(analysis.warnings)}",
    ]
    lines.extend(f"- FAIL: {item}" for item in analysis.hard_failures[:12])
    lines.extend(f"- WARN: {item}" for item in analysis.warnings[:12])
    return "\n".join(lines)


def _placement_gate_verdict(analysis: PlacementAnalysis) -> tuple[GateStatus, str]:
    """Give measured hard failures priority over advisory placement warnings."""
    if analysis.hard_failures:
        return "FAIL", "Footprint placement still violates hard physical or intent-aware checks."
    if analysis.warnings:
        return "WARN", "Placement measurements require manual review; no hard failure was proven."
    return "PASS", "Footprint placement is geometrically and contextually sane."


def _evaluate_pcb_placement_gate() -> GateOutcome:
    analysis, blocked = _placement_analysis()
    if blocked is not None:
        return blocked
    if analysis is None:
        raise RuntimeError(_MISSING_PLACEMENT_ANALYSIS)

    status, summary = _placement_gate_verdict(analysis)
    details = [
        f"Footprints analysed: {analysis.footprint_count}",
        f"Board frame: {analysis.board_width_mm:.2f} x {analysis.board_height_mm:.2f} mm",
        f"Density: {analysis.density_pct:.2f}%",
        f"Connector checks: {analysis.checked_connectors}",
        f"Decoupling pair checks: {analysis.checked_decoupling_pairs}",
        f"RF keepout checks: {analysis.checked_keepouts}",
        f"Power-tree refs checked: {analysis.checked_power_tree_refs}",
        f"Analog refs checked: {analysis.checked_analog_refs}",
        f"Digital refs checked: {analysis.checked_digital_refs}",
        f"Sensor-cluster refs checked: {analysis.checked_sensor_cluster_refs}",
        f"Critical-net Manhattan proxy: {analysis.critical_net_proxy_mm:.2f} mm",
        f"Critical-net proxy density: {analysis.critical_net_proxy_density:.2f} mm per 1000 mm^2",
        f"Thermal hotspot refs checked: {analysis.checked_thermal_hotspot_refs}",
        f"Thermal hotspot proximity: {analysis.thermal_proximity_sum:.4f}",
        f"Placement score: {analysis.score}/100",
    ]
    details.extend(f"FAIL: {item}" for item in analysis.hard_failures[:12])
    details.extend(f"WARN: {item}" for item in analysis.warnings[:12])
    return GateOutcome(
        name="Placement",
        status=status,
        summary=summary,
        details=details,
    )


def _evaluate_manufacturing_gate(
    *,
    manufacturer: str | None = None,
    tier: str | None = None,
) -> GateOutcome:
    from .design_intent_state import resolve_design_intent
    from .dfm import _dfm_check_lines, _load_profile, _selected_profile

    if manufacturer is None or tier is None:
        try:
            intent = resolve_design_intent().resolved
        except ValueError:
            intent = None
        if intent is not None:
            manufacturer = manufacturer or intent.manufacturer or None
            tier = tier or intent.manufacturer_tier or None
    profile = (
        _load_profile(manufacturer, tier)
        if manufacturer and tier
        else cast(dict[str, object], _selected_profile())
    )
    lines = _dfm_check_lines(
        cast(dict[str, object], profile),
        heading="Manufacturing quality gate:",
    )
    fail_lines = [line[8:] for line in lines if line.startswith("- FAIL: ")]
    warn_lines = [line[8:] for line in lines if line.startswith("- WARN: ")]
    status: GateStatus = "PASS" if not fail_lines else "FAIL"
    details = [f"Profile: {profile['manufacturer']} / {profile['tier']}"]
    details.extend(f"FAIL: {line}" for line in fail_lines[:12])
    details.extend(f"WARN: {line}" for line in warn_lines[:12])
    return GateOutcome(
        name="Manufacturing",
        status=status,
        summary="DFM checks passed."
        if status == "PASS"
        else f"DFM reported {len(fail_lines)} failing checks.",
        details=details,
    )


def _is_project_empty() -> bool:
    from .board_file import _edge_cuts_bounds, _parse_board_footprint_blocks
    from .schematic import parse_schematic_file, project_schematic_files

    # Check schematic
    try:
        sch_files = project_schematic_files()
        if sch_files:
            for sch_file in sch_files:
                if sch_file.exists():
                    data = parse_schematic_file(sch_file)
                    if (
                        data.get("symbols")
                        or data.get("power_symbols")
                        or data.get("wires")
                        or data.get("labels")
                    ):
                        return False
    except Exception:  # noqa: S110
        pass

    # Check PCB
    try:
        pcb_file = _get_pcb_file()
        if pcb_file.exists():
            content = pcb_file.read_text(encoding="utf-8", errors="ignore")
            footprints = _parse_board_footprint_blocks(content)
            if footprints:
                return False
            if _edge_cuts_bounds(content) is not None:
                return False
    except Exception:  # noqa: S110
        pass

    return True


def _empty_project_onboarding_outcome() -> GateOutcome:
    return GateOutcome(
        name="Project Onboarding",
        status="EMPTY",
        summary="Your KiCad Studio project is currently empty or newly created.",
        details=[
            "Suggested Onboarding Steps:",
            "1. Define your design intent by calling the 'project_set_design_intent' tool.",
            "2. Add schematic symbols, connect them with wires, and add labels.",
            "3. Place components onto the PCB and define the board outline.",
            "4. Re-run project_quality_gate to see your progress!",
        ],
    )


# The edit-impact categories that the bundled project gate can actually re-run. The
# remaining categories (signal_integrity, power, thermal, emc) are covered by separate
# analysis tools, not by this sign-off gate.
PROJECT_GATE_CATEGORIES: frozenset[str] = frozenset(
    {"schematic", "connectivity", "pcb", "manufacturing", "dfm"}
)


def _evaluate_project_gate(
    *,
    manufacturer: str | None = None,
    tier: str | None = None,
    only_categories: set[str] | frozenset[str] | None = None,
) -> list[GateOutcome]:
    """Evaluate the project gate. When ``only_categories`` is given, run only the
    evaluators whose edit-impact category is in that set (selective re-validation)."""
    if _is_project_empty():
        return [_empty_project_onboarding_outcome()]

    # (edit-impact category, evaluator) — order is the report order.
    evaluators: tuple[tuple[str, Callable[[], GateOutcome]], ...] = (
        ("schematic", _evaluate_schematic_gate),
        ("connectivity", _evaluate_schematic_connectivity_gate),
        ("connectivity", _evaluate_pre_sync_gate),
        ("schematic", _evaluate_schematic_cosmetics_gate),
        ("pcb", _evaluate_pcb_gate),
        ("pcb", _evaluate_pcb_placement_gate),
        ("pcb", _evaluate_pcb_transfer_gate),
        (
            "manufacturing",
            lambda: _evaluate_manufacturing_gate(manufacturer=manufacturer, tier=tier),
        ),
        ("dfm", _footprint_parity_outcome),
    )
    return [
        evaluator()
        for category, evaluator in evaluators
        if only_categories is None or category in only_categories
    ]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _signoff_provenance(intent: ProjectDesignIntent) -> dict[str, Any]:
    """Build deterministic sign-off provenance (no timestamps, so the hash is stable)."""
    cfg = get_config()
    caps = get_cli_capabilities(cfg.kicad_cli)
    intent_hash = hashlib.sha256(
        json.dumps(intent.model_dump(), sort_keys=True).encode()
    ).hexdigest()[:16]
    source_hashes = {
        label: _sha256_file(path)
        for label, path in (
            ("project", cfg.project_file),
            ("pcb", cfg.pcb_file),
            ("schematic", cfg.sch_file),
        )
        if path is not None and path.exists()
    }
    return {
        "kicad_mcp_version": __version__,
        "kicad_cli": str(cfg.kicad_cli),
        "kicad_cli_version": caps.version,
        "rule_profile": f"{cfg.profile}/{cfg.operating_mode}",
        "intent_hash": intent_hash,
        "source_hashes": source_hashes,
    }


def _render_project_gate_report(
    outcomes: list[GateOutcome],
    *,
    summary: str | None = None,
) -> str:
    status = _combined_status(outcomes)
    lines = [
        f"Project quality gate: {status}",
        summary
        or (
            "- This project is ready for the next stage."
            if status == "PASS"
            else "- Blocking issues remain. Do not treat this design as production-ready yet."
        ),
    ]
    if _design_intent_warning():
        lines.append("WARN: Design intent not set - placement scoring will use defaults.")
    lines.extend(_format_gate(outcome) for outcome in outcomes)
    return "\n\n".join(lines)


def _design_intent_warning() -> bool:
    try:
        from .design_intent_state import resolve_design_intent

        return resolve_design_intent().source == "none"
    except Exception:
        return False


def _project_gate_report_payload(
    outcomes: list[GateOutcome],
    *,
    summary: str | None = None,
) -> ProjectGateReportPayload:
    text = _render_project_gate_report(outcomes, summary=summary)
    status = _combined_status(outcomes)
    headline = summary or (
        "This project is ready for the next stage."
        if status == "PASS"
        else "Blocking issues remain. Do not treat this design as production-ready yet."
    )
    return ProjectGateReportPayload(
        text=text,
        status=status,
        summary=headline.lstrip("- ").strip(),
        outcomes=[_gate_outcome_payload(outcome) for outcome in outcomes],
    )


def _project_gate_verdict_report(
    outcomes: list[GateOutcome],
    *,
    summary: str | None = None,
) -> VerdictReport:
    text = _render_project_gate_report(outcomes, summary=summary)
    status = _combined_status(outcomes)
    headline = summary or (
        "This project is ready for the next stage."
        if status == "PASS"
        else "Blocking issues remain. Do not treat this design as production-ready yet."
    )
    findings = [finding for outcome in outcomes for finding in _gate_findings(outcome)]
    if _design_intent_warning():
        findings.append(
            Finding(
                id=stable_finding_id("gate", "project", "design-intent-missing"),
                severity="warning",
                location="Project design intent",
                description="Design intent is not set; placement scoring will use defaults.",
                suggested_fix=SuggestedFix(tool="project_set_design_intent", args={}),
            )
        )
    verdict = VerdictReport.verdict_for([finding.severity for finding in findings])
    if verdict == "PASS":
        verdict = _gate_status_verdict(status)
    first_blocker = next((outcome for outcome in outcomes if outcome.status != "PASS"), None)
    if first_blocker is None:
        next_action = "Proceed to export_manufacturing_package()."
    else:
        fixer = _fix_for_gate(first_blocker.name)
        next_action = (
            f"Call {fixer.tool} and re-run project_quality_gate()."
            if fixer is not None
            else "Fix the first blocking gate and re-run project_quality_gate()."
        )
    return VerdictReport(
        text=text,
        summary=headline.lstrip("- ").strip(),
        verdict=verdict,
        findings=findings,
        next_action=next_action,
        metadata={
            "status": status,
            "outcomes": [_gate_outcome_payload(outcome).model_dump() for outcome in outcomes],
        },
    )


def _readiness_evidence_from_verdict(report: VerdictReport) -> ReadinessEvidencePayload:
    metadata = dict(report.metadata)
    return ReadinessEvidencePayload(
        available=bool(metadata.get("available", False)),
        summary=report.summary,
        path=str(metadata.get("report_path", "")),
        metadata=metadata,
    )


def _release_bom_readiness() -> BomReadinessPayload:
    from .library import _schematic_component_rows

    rows = _schematic_component_rows()
    populated_rows = [row for row in rows if str(row.get("populate", "")).strip().upper() != "DNP"]
    missing_mpn = sorted(
        str(row["reference"]) for row in populated_rows if not str(row.get("mpn", "")).strip()
    )
    missing_lcsc = sorted(
        str(row["reference"]) for row in populated_rows if not str(row.get("lcsc", "")).strip()
    )
    missing_footprint = sorted(
        str(row["reference"]) for row in populated_rows if not str(row.get("footprint", "")).strip()
    )
    if not rows:
        summary = "No schematic references were available for BOM evidence."
    elif missing_mpn or missing_lcsc or missing_footprint:
        unresolved = sorted(set(missing_mpn + missing_lcsc + missing_footprint))
        summary = (
            "BOM evidence is incomplete for populated references: "
            + ", ".join(unresolved[:8])
            + ("..." if len(unresolved) > 8 else "")
        )
    else:
        summary = "Populated BOM references include MPN, LCSC, and footprint fields."
    return BomReadinessPayload(
        summary=summary,
        total_refs=len(rows),
        populated_refs=len(populated_rows),
        dnp_refs=sum(1 for row in rows if str(row.get("populate", "")).strip().upper() == "DNP"),
        missing_mpn_refs=missing_mpn,
        missing_lcsc_refs=missing_lcsc,
        missing_footprint_refs=missing_footprint,
    )


def _release_artifact_evidence() -> ReadinessEvidencePayload:
    from ..manufacturing.release_evidence import find_release_files

    cfg = get_config()
    if cfg.project_dir is None:
        raise ValueError(_NO_ACTIVE_PROJECT_ERROR)
    output_dir = cfg.output_dir or (cfg.project_dir / "output")
    if not output_dir.exists():
        return ReadinessEvidencePayload(
            available=False,
            summary="Release output directory does not exist yet.",
            path=str(output_dir),
            metadata={"missing_categories": ["bom", "pick_and_place", "manufacturing"]},
        )

    release_files = find_release_files(output_dir)
    bom_paths: list[str] = []
    pick_and_place_paths: list[str] = []
    manufacturing_paths: list[str] = []
    for file_path in release_files:
        lowered = file_path.name.casefold()
        if "bom" in lowered:
            bom_paths.append(str(file_path))
        elif any(token in lowered for token in ("pos", "cpl", "pick", "place")):
            pick_and_place_paths.append(str(file_path))
        else:
            manufacturing_paths.append(str(file_path))
    missing_categories = [
        name
        for name, paths in (
            ("bom", bom_paths),
            ("pick_and_place", pick_and_place_paths),
            ("manufacturing", manufacturing_paths),
        )
        if not paths
    ]
    available = bool(release_files) and not missing_categories
    summary = (
        "Found "
        f"{len(release_files)} release files covering BOM, pick-and-place, "
        "and manufacturing outputs."
        if available
        else "Release artifacts are incomplete for a gated handoff."
    )
    return ReadinessEvidencePayload(
        available=available,
        summary=summary,
        path=str(output_dir),
        details=[str(path) for path in release_files[:12]],
        metadata={
            "release_files": [str(path) for path in release_files],
            "bom_paths": bom_paths,
            "pick_and_place_paths": pick_and_place_paths,
            "manufacturing_paths": manufacturing_paths,
            "missing_categories": missing_categories,
        },
    )


def _release_manifest_evidence(output_dir: str) -> ReadinessEvidencePayload:
    manifest_json_path = Path(output_dir) / "manifest.json"
    manifest_txt_path = Path(output_dir) / "MANIFEST.txt"
    if not manifest_json_path.exists() or not manifest_txt_path.exists():
        return ReadinessEvidencePayload(
            available=False,
            summary="Release manifest is missing or incomplete.",
            path=str(manifest_json_path),
            metadata={
                "manifest_txt_path": str(manifest_txt_path),
                "file_count": 0,
                "content_hash": "",
            },
        )
    try:
        payload = cast(dict[str, Any], json.loads(manifest_json_path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        return ReadinessEvidencePayload(
            available=False,
            summary=f"Release manifest could not be parsed: {exc}",
            path=str(manifest_json_path),
            metadata={"manifest_txt_path": str(manifest_txt_path), "file_count": 0},
        )
    return ReadinessEvidencePayload(
        available=True,
        summary="Release manifest is present and parseable.",
        path=str(manifest_json_path),
        metadata={
            "manifest_txt_path": str(manifest_txt_path),
            "file_count": len(cast(list[dict[str, Any]], payload.get("files", []))),
            "content_hash": str(payload.get("content_hash", "")),
        },
    )


def _release_waiver_evidence() -> ReadinessEvidencePayload:
    cfg = get_config()
    if cfg.project_dir is None:
        raise ValueError(_NO_ACTIVE_PROJECT_ERROR)
    path = cfg.project_dir / ".kicad-mcp" / "drc_exclusions.json"
    if not path.exists():
        return ReadinessEvidencePayload(
            available=True,
            summary="No DRC exclusions are recorded for this project.",
            path=str(path),
            metadata={"count": 0, "uuids": []},
        )
    try:
        payload = cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))
    except json.JSONDecodeError as exc:
        return ReadinessEvidencePayload(
            available=False,
            summary=f"DRC exclusion file is invalid JSON: {exc}",
            path=str(path),
            metadata={"count": 0, "uuids": []},
        )
    exclusions = cast(list[dict[str, Any]], payload.get("exclusions", []))
    return ReadinessEvidencePayload(
        available=True,
        summary=(
            "No DRC exclusions are recorded for this project."
            if not exclusions
            else f"{len(exclusions)} DRC exclusion(s) require explicit human review."
        ),
        path=str(path),
        metadata={
            "count": len(exclusions),
            "uuids": [str(entry.get("uuid", "")) for entry in exclusions if entry.get("uuid")],
        },
    )


def _release_readiness_summary(
    verdict: Verdict,
    *,
    required_failures: list[str],
    waiver_count: int,
    dnp_refs: int,
) -> str:
    if verdict == "PASS":
        return "Release evidence is complete for human manufacturing review."
    if verdict == "WARN":
        return "Release evidence is mostly complete, but human review is still required."
    summary_parts = required_failures[:]
    if waiver_count:
        summary_parts.append(f"{waiver_count} DRC exclusion(s) need review")
    if dnp_refs:
        summary_parts.append(f"{dnp_refs} reference(s) are marked DNP")
    return "Required release evidence is missing or failing: " + "; ".join(summary_parts)


def _render_release_readiness_text(
    *,
    verdict: Verdict,
    summary: str,
    drc: ReadinessEvidencePayload,
    erc: ReadinessEvidencePayload,
    manufacturing: GateOutcomePayload,
    project_gate: ProjectGateReportPayload,
    bom: BomReadinessPayload,
    waivers: ReadinessEvidencePayload,
    artifacts: ReadinessEvidencePayload,
    manifest: ReadinessEvidencePayload,
    approval_checklist: list[str],
    open_risks: list[str],
    advisory_notes: list[str],
) -> str:
    lines = [
        f"Project release readiness: {verdict}",
        f"- Gate status: {project_gate.status}",
        f"- Summary: {summary}",
        "",
        "## Gate evidence",
        f"- Project gate: {project_gate.status} | {project_gate.summary}",
        f"- Manufacturing profile: {manufacturing.status} | {manufacturing.summary}",
        f"- DRC: {'available' if drc.available else 'missing'} | {drc.summary}",
        f"- ERC: {'available' if erc.available else 'missing'} | {erc.summary}",
        "",
        "## BOM evidence",
        f"- Total references: {bom.total_refs}",
        f"- Populated references: {bom.populated_refs}",
        f"- DNP references: {bom.dnp_refs}",
        f"- BOM summary: {bom.summary}",
        "",
        "## Release artifacts",
        "- Artifact bundle: "
        f"{'ready' if artifacts.available else 'incomplete'} | {artifacts.summary}",
        f"- Artifact directory: {artifacts.path}",
        f"- Release manifest: {'ready' if manifest.available else 'missing'} | {manifest.summary}",
        f"- Manifest path: {manifest.path}",
        "",
        "## Waivers and approval",
        f"- DRC exclusions: {waivers.metadata.get('count', 0)}",
    ]
    if open_risks:
        lines.extend(["", "## Open risks", *[f"- {risk}" for risk in open_risks]])
    lines.extend(["", "## Human approval checklist", *[f"- {item}" for item in approval_checklist]])
    lines.extend(["", "## Advisory notes", *[f"- {note}" for note in advisory_notes]])
    return "\n".join(lines)


def _export_release_readiness_report(
    payload: ProjectReleaseReadinessPayload,
    *,
    output_path: str,
    export_format: str,
) -> str:
    cfg = get_config()
    target = cfg.resolve_within_project(output_path, allow_absolute=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    normalized = export_format.casefold().strip()
    if not normalized:
        normalized = {
            ".json": "json",
            ".md": "markdown",
            ".markdown": "markdown",
            ".html": "html",
            ".htm": "html",
        }.get(target.suffix.casefold(), "json")
    if normalized == "json":
        target.write_text(json.dumps(payload.model_dump(), indent=2), encoding="utf-8")
    elif normalized == "markdown":
        target.write_text(payload.text, encoding="utf-8")
    elif normalized in {"html", "pdf-ready"}:
        html_text = "\n".join(
            [
                "<!doctype html>",
                '<html><head><meta charset="utf-8">',
                "<title>Project release readiness</title>",
                "<style>",
                "body{font-family:Segoe UI,Arial,sans-serif;margin:2rem;}"
                "pre{white-space:pre-wrap;font-family:Consolas,Monaco,monospace;line-height:1.45;}"
                "@media print{body{margin:1cm;}}"
                "</style>",
                "</head><body>",
                f"<pre>{escape(payload.text)}</pre>",
                "</body></html>",
            ]
        )
        target.write_text(html_text, encoding="utf-8")
    else:
        raise ValueError("export_format must be one of: json, markdown, html, pdf-ready")
    return str(target)


def _release_evidence_for_active_project() -> ProjectReleaseEvidenceResolution:
    cfg = get_config()
    if cfg.project_dir is None:
        return ProjectReleaseEvidenceResolution(adopted=False)
    return resolve_project_release_evidence(cfg.project_dir)


def _release_evidence_risks(
    resolution: ProjectReleaseEvidenceResolution,
) -> list[str]:
    if not resolution.adopted:
        return []
    risks = list(resolution.errors)
    if resolution.gate is None:
        if not risks:
            risks.append("release contract evidence gate could not be evaluated")
        return risks
    for result in resolution.gate.blocking:
        identity = f"{result.contract_id}@{result.contract_version}"
        reasons = ", ".join(result.reason_codes) or "unresolved"
        risks.append(f"{identity}: {reasons}")
    return risks


def _compute_readiness_required_failures(
    project_gate: ProjectGateReportPayload,
    drc: ReadinessEvidencePayload,
    erc: ReadinessEvidencePayload,
    bom: BomReadinessPayload,
    artifacts: ReadinessEvidencePayload,
    manifest: ReadinessEvidencePayload,
    waivers: ReadinessEvidencePayload,
    release_evidence: ProjectReleaseEvidenceResolution,
) -> list[str]:
    required_failures: list[str] = []
    if project_gate.status != "PASS":
        required_failures.append(f"project gate is {project_gate.status}")
    if not drc.available:
        required_failures.append("DRC report unavailable")
    if not erc.available:
        required_failures.append("ERC report unavailable")
    if bom.total_refs == 0:
        required_failures.append("BOM evidence missing")
    if bom.missing_mpn_refs or bom.missing_lcsc_refs or bom.missing_footprint_refs:
        required_failures.append("populated BOM fields unresolved")
    if not artifacts.available:
        missing_categories = cast(list[str], artifacts.metadata.get("missing_categories", []))
        suffix = f" ({', '.join(missing_categories)})" if missing_categories else ""
        required_failures.append(f"release artifacts missing{suffix}")
    if not manifest.available:
        required_failures.append("release manifest missing")
    if not waivers.available:
        required_failures.append("waiver evidence unreadable")
    if release_evidence.adopted and not release_evidence.approved:
        required_failures.append("release-blocking contract evidence is stale or unresolved")
    return required_failures


def _compute_readiness_open_risks(
    project_gate: ProjectGateReportPayload,
    drc: ReadinessEvidencePayload,
    erc: ReadinessEvidencePayload,
    bom: BomReadinessPayload,
    artifacts: ReadinessEvidencePayload,
    manifest: ReadinessEvidencePayload,
    waiver_count: int,
    release_evidence: ProjectReleaseEvidenceResolution,
    release_evidence_risks: list[str],
) -> list[str]:
    open_risks = [
        f"Project quality gate is {project_gate.status}: {project_gate.summary}"
        for _ in [0]
        if project_gate.status != "PASS"
    ]
    if not drc.available:
        open_risks.append(drc.summary)
    if not erc.available:
        open_risks.append(erc.summary)
    if bom.missing_mpn_refs:
        open_risks.append(
            "Missing MPN fields on populated refs: " + ", ".join(bom.missing_mpn_refs[:8])
        )
    if bom.missing_lcsc_refs:
        open_risks.append(
            "Missing LCSC fields on populated refs: " + ", ".join(bom.missing_lcsc_refs[:8])
        )
    if bom.missing_footprint_refs:
        open_risks.append(
            "Missing footprint fields on populated refs: "
            + ", ".join(bom.missing_footprint_refs[:8])
        )
    if not artifacts.available:
        missing_categories = cast(list[str], artifacts.metadata.get("missing_categories", []))
        open_risks.append(
            "Release artifact categories missing: " + ", ".join(missing_categories or ["unknown"])
        )
    if not manifest.available:
        open_risks.append(manifest.summary)
    if waiver_count:
        open_risks.append(f"{waiver_count} DRC exclusion(s) remain active and need review.")
    open_risks.extend(release_evidence_risks)
    if release_evidence.gate is not None and release_evidence.gate.waived:
        open_risks.append(
            f"{len(release_evidence.gate.waived)} release-blocking contract waiver(s) "
            "require explicit review."
        )
    return open_risks


def _compute_readiness_approval_checklist(
    drc: ReadinessEvidencePayload,
    erc: ReadinessEvidencePayload,
    manufacturing: GateOutcomePayload,
    bom: BomReadinessPayload,
    waiver_count: int,
    artifacts: ReadinessEvidencePayload,
    manifest: ReadinessEvidencePayload,
    release_evidence: ProjectReleaseEvidenceResolution,
) -> list[str]:
    approval_checklist = [
        (
            "[x]"
            if drc.available
            and int(drc.metadata.get("violations", 0)) == 0
            and int(drc.metadata.get("unconnected_items", 0)) == 0
            and int(drc.metadata.get("courtyard_issues", 0)) == 0
            else "[ ]"
        )
        + " Review DRC evidence and confirm zero blocking findings.",
        ("[x]" if erc.available and int(erc.metadata.get("violation_count", 0)) == 0 else "[ ]")
        + " Review ERC evidence and confirm zero blocking findings.",
        ("[x]" if manufacturing.status == "PASS" else "[ ]")
        + " Confirm the selected manufacturing profile and DFM checks.",
        (
            "[x]"
            if bom.populated_refs > 0
            and not bom.missing_mpn_refs
            and not bom.missing_lcsc_refs
            and not bom.missing_footprint_refs
            else "[ ]"
        )
        + " Confirm populated BOM rows include MPN, LCSC, and footprint evidence.",
        ("[x]" if waiver_count == 0 else "[ ]") + " Review all recorded waivers and exclusions.",
        ("[x]" if artifacts.available else "[ ]")
        + " Archive BOM, pick-and-place, and manufacturing release artifacts.",
        ("[x]" if manifest.available else "[ ]")
        + " Generate and archive the release manifest package.",
    ]
    if release_evidence.adopted:
        approval_checklist.append(
            ("[x]" if release_evidence.approved else "[ ]")
            + " Confirm release-blocking HardwareIntentContract evidence is fresh "
            "or explicitly waived."
        )
    approval_checklist.append("[ ] Record final human approval in the external release workflow.")
    return approval_checklist


def _build_project_release_readiness_payload(
    *,
    manufacturer: str | None = None,
    tier: str | None = None,
) -> ProjectReleaseReadinessPayload:
    outcomes = _evaluate_project_gate(manufacturer=manufacturer, tier=tier)
    project_gate = _project_gate_report_payload(outcomes)
    manufacturing_outcome = next(
        (outcome for outcome in outcomes if outcome.name == "Manufacturing"),
        GateOutcome(
            name="Manufacturing",
            status="BLOCKED",
            summary="Manufacturing profile evidence was not produced.",
            details=[],
        ),
    )
    manufacturing = _gate_outcome_payload(manufacturing_outcome)

    drc_path, drc_report, drc_error = _run_drc_report("release_readiness_drc.json")
    erc_path, erc_report, erc_error = _run_erc_report("release_readiness_erc.json")
    drc = _readiness_evidence_from_verdict(
        _drc_report_payload(drc_path, drc_report, drc_error, save_report=False)
    )
    erc = _readiness_evidence_from_verdict(
        _erc_report_payload(erc_path, erc_report, erc_error, save_report=False)
    )
    bom = _release_bom_readiness()
    artifacts = _release_artifact_evidence()
    manifest = _release_manifest_evidence(artifacts.path)
    waivers = _release_waiver_evidence()
    release_evidence = _release_evidence_for_active_project()

    required_failures = _compute_readiness_required_failures(
        project_gate, drc, erc, bom, artifacts, manifest, waivers, release_evidence
    )
    release_evidence_risks = _release_evidence_risks(release_evidence)
    waiver_count = int(waivers.metadata.get("count", 0))

    open_risks = _compute_readiness_open_risks(
        project_gate,
        drc,
        erc,
        bom,
        artifacts,
        manifest,
        waiver_count,
        release_evidence,
        release_evidence_risks,
    )

    if required_failures:
        verdict: Verdict = "FAIL"
    elif (
        waiver_count
        or bom.dnp_refs
        or (release_evidence.gate is not None and release_evidence.gate.waived)
    ):
        verdict = "WARN"
    else:
        verdict = _gate_status_verdict(project_gate.status)
    summary = _release_readiness_summary(
        verdict,
        required_failures=required_failures,
        waiver_count=waiver_count,
        dnp_refs=bom.dnp_refs,
    )
    approval_checklist = _compute_readiness_approval_checklist(
        drc,
        erc,
        manufacturing,
        bom,
        waiver_count,
        artifacts,
        manifest,
        release_evidence,
    )
    advisory_notes = [
        "This bundle aggregates evidence for release review; it does not grant Formal sign-off.",
        "Advisory estimators and heuristics remain evidence only and must not be "
        "treated as certification.",
    ]
    text = _render_release_readiness_text(
        verdict=verdict,
        summary=summary,
        drc=drc,
        erc=erc,
        manufacturing=manufacturing,
        project_gate=project_gate,
        bom=bom,
        waivers=waivers,
        artifacts=artifacts,
        manifest=manifest,
        approval_checklist=approval_checklist,
        open_risks=open_risks,
        advisory_notes=advisory_notes,
    )
    return ProjectReleaseReadinessPayload(
        text=text,
        summary=summary,
        verdict=verdict,
        status=project_gate.status,
        drc=drc,
        erc=erc,
        manufacturing=manufacturing,
        project_gate=project_gate,
        bom=bom,
        waivers=waivers,
        artifacts=artifacts,
        manifest=manifest,
        approval_checklist=approval_checklist,
        open_risks=open_risks,
        advisory_notes=advisory_notes,
    )


def _placement_gate_report_payload() -> PlacementGateReportPayload:
    analysis, blocked = _placement_analysis()
    if blocked is not None:
        return PlacementGateReportPayload(
            text=_format_gate(blocked),
            status=blocked.status,
            summary=blocked.summary,
            hard_failures=blocked.details,
        )
    if analysis is None:
        raise RuntimeError(_MISSING_PLACEMENT_ANALYSIS)
    outcome = _evaluate_pcb_placement_gate()
    return PlacementGateReportPayload(
        text=_format_gate(outcome),
        status=outcome.status,
        summary=outcome.summary,
        score=analysis.score,
        footprint_count=analysis.footprint_count,
        checked_connectors=analysis.checked_connectors,
        checked_decoupling_pairs=analysis.checked_decoupling_pairs,
        checked_keepouts=analysis.checked_keepouts,
        checked_power_tree_refs=analysis.checked_power_tree_refs,
        checked_analog_refs=analysis.checked_analog_refs,
        checked_digital_refs=analysis.checked_digital_refs,
        checked_sensor_cluster_refs=analysis.checked_sensor_cluster_refs,
        hard_failures=analysis.hard_failures,
        warnings=analysis.warnings,
    )


def render_gate_by_name(
    gate_name: str,
    *,
    manufacturer: str | None = None,
    tier: str | None = None,
) -> str:
    """Render a single named gate or the full project gate as text."""
    normalized = gate_name.strip().lower().replace("-", "_")
    if normalized in {"project", "project_quality", "project_quality_gate"}:
        return _render_project_gate_report(
            _evaluate_project_gate(manufacturer=manufacturer, tier=tier)
        )
    if normalized in {"schematic", "schematic_quality", "schematic_quality_gate"}:
        return _format_gate(_evaluate_schematic_gate())
    if normalized in {
        "schematic_connectivity",
        "schematic_connectivity_gate",
        "connectivity",
    }:
        return _format_gate(_evaluate_schematic_connectivity_gate())
    if normalized in {"pcb", "pcb_quality", "pcb_quality_gate"}:
        return _format_gate(_evaluate_pcb_gate())
    if normalized in {"placement", "pcb_placement", "pcb_placement_quality_gate"}:
        return _format_gate(_evaluate_pcb_placement_gate())
    if normalized in {"transfer", "pcb_transfer", "pcb_transfer_quality_gate"}:
        return _format_gate(_evaluate_pcb_transfer_gate())
    if normalized in {"manufacturing", "manufacturing_quality_gate"}:
        return _format_gate(_evaluate_manufacturing_gate(manufacturer=manufacturer, tier=tier))
    if normalized in {"footprint_parity", "parity"}:
        return _format_gate(_footprint_parity_outcome())
    raise ValueError(
        "Unknown gate name. Use one of: project, schematic, schematic_connectivity, "
        "pcb, placement, transfer, manufacturing, footprint_parity."
    )


@dataclass(slots=True)
class _PcbTrackSegment:
    """Small file-level representation of a PCB segment for quality gates."""

    net: str
    layer: str
    start: tuple[float, float]
    end: tuple[float, float]
    width_mm: float


def _balanced_blocks(text: str, atom: str) -> list[str]:
    """Return top-level-ish S-expression blocks whose first atom matches ``atom``.

    This intentionally stays lightweight: it is used for quality linting only and
    does not attempt to be a full KiCad file parser. It handles nested parentheses
    and ignores malformed trailing content by omitting incomplete blocks.
    """
    blocks: list[str] = []
    pattern = re.compile(r"\(" + re.escape(atom) + r"\b")
    pos = 0
    while True:
        match = pattern.search(text, pos)
        if match is None:
            break
        start = match.start()
        depth = 0
        end = start
        while end < len(text):
            char = text[end]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    blocks.append(text[start : end + 1])
                    pos = end + 1
                    break
            end += 1
        else:
            break
    return blocks


def _pcb_net_name_from_block(block: str) -> str:
    numbered = re.search(r'\(net\s+\d+\s+"([^"]*)"\)', block)
    if numbered is not None:
        return numbered.group(1)
    named = re.search(r'\(net\s+"([^"]*)"\)', block)
    return named.group(1) if named is not None else ""


def _pcb_layer_from_block(block: str) -> str:
    match = re.search(r'\(layer\s+"([^"]+)"\)', block)
    return match.group(1) if match is not None else ""


def _pcb_point_from_block(block: str, atom: str) -> tuple[float, float] | None:
    match = re.search(r"\(" + re.escape(atom) + r"\s+([-0-9.]+)\s+([-0-9.]+)", block)
    if match is None:
        return None
    return (float(match.group(1)), float(match.group(2)))


def _pcb_width_from_block(block: str) -> float:
    match = re.search(r"\(width\s+([-0-9.]+)\)", block)
    return float(match.group(1)) if match is not None else 0.0


def _pcb_track_segments_from_text(pcb_text: str) -> list[_PcbTrackSegment]:
    segments: list[_PcbTrackSegment] = []
    for block in _balanced_blocks(pcb_text, "segment"):
        start = _pcb_point_from_block(block, "start")
        end = _pcb_point_from_block(block, "end")
        if start is None or end is None:
            continue
        segments.append(
            _PcbTrackSegment(
                net=_pcb_net_name_from_block(block),
                layer=_pcb_layer_from_block(block),
                start=start,
                end=end,
                width_mm=_pcb_width_from_block(block),
            )
        )
    return segments


def _segment_length_mm(segment: _PcbTrackSegment) -> float:
    return math.hypot(segment.end[0] - segment.start[0], segment.end[1] - segment.start[1])


def _segment_axis(segment: _PcbTrackSegment, tolerance_mm: float = 1e-4) -> str:
    dx = segment.end[0] - segment.start[0]
    dy = segment.end[1] - segment.start[1]
    if abs(dx) <= tolerance_mm and abs(dy) <= tolerance_mm:
        return "point"
    if abs(dx) <= tolerance_mm:
        return "vertical"
    if abs(dy) <= tolerance_mm:
        return "horizontal"
    if abs(abs(dx) - abs(dy)) <= tolerance_mm:
        return "45deg"
    return "angled"


def _point_key(point: tuple[float, float], precision: int = 3) -> tuple[float, float]:
    return (round(point[0], precision), round(point[1], precision))


def _index_segments_by_endpoint(
    segments: list[_PcbTrackSegment],
    min_segment_length_mm: float,
) -> dict[tuple[str, str, tuple[float, float]], list[_PcbTrackSegment]]:
    by_point: dict[tuple[str, str, tuple[float, float]], list[_PcbTrackSegment]] = {}
    for segment in segments:
        if not segment.net or _segment_length_mm(segment) < min_segment_length_mm:
            continue
        for point in (segment.start, segment.end):
            key = (segment.net, segment.layer, _point_key(point))
            by_point.setdefault(key, []).append(segment)
    return by_point


def _find_corner_findings_at_point(
    key: tuple[str, str, tuple[float, float]],
    connected: list[_PcbTrackSegment],
    seen: set[tuple[int, int, tuple[str, str, tuple[float, float]]]],
) -> list[str]:
    findings: list[str] = []
    for left_index, left in enumerate(connected):
        for right in connected[left_index + 1 :]:
            axes = {_segment_axis(left), _segment_axis(right)}
            if axes != {"horizontal", "vertical"}:
                continue
            pair_key = (id(left), id(right), key)
            if pair_key in seen:
                continue
            seen.add(pair_key)
            net, layer, point = key
            findings.append(
                f"{net} on {layer} has a 90° corner at ({point[0]:.3f}, {point[1]:.3f})"
            )
    return findings


def _route_90_degree_corners(
    segments: list[_PcbTrackSegment],
    *,
    min_segment_length_mm: float = 0.25,
) -> list[str]:
    """Return descriptions of orthogonal H/V corners that should be chamfered.

    We only flag corners formed by two real segments on the same net/layer that
    meet at an endpoint. Pad-entry stubs shorter than ``min_segment_length_mm``
    are ignored to avoid noisy reports around QFN/THT pin escapes.
    """
    by_point = _index_segments_by_endpoint(segments, min_segment_length_mm)
    findings: list[str] = []
    seen: set[tuple[int, int, tuple[str, str, tuple[float, float]]]] = set()
    for key, connected in by_point.items():
        if len(connected) >= 2:
            findings.extend(_find_corner_findings_at_point(key, connected, seen))
    return sorted(findings)


def _pcb_layer_table_copper_layers(pcb_text: str) -> list[str]:
    layer_blocks = _balanced_blocks(pcb_text, "layers")
    if not layer_blocks:
        return []
    layers = re.findall(r'\(\s*+\d++\s++"([^"]+\.Cu)"\s++[^)]*+\)', layer_blocks[0])
    return list(dict.fromkeys(layers))


def _pcb_stackup_copper_layers(pcb_text: str) -> list[str]:
    stackup_blocks = _balanced_blocks(pcb_text, "stackup")
    if not stackup_blocks:
        return []
    layers = re.findall(r'\(layer\s+"([^"]+\.Cu)"', stackup_blocks[0])
    return list(dict.fromkeys(layers))


def _evaluate_stackup_consistency_gate() -> GateOutcome:
    cfg = get_config()
    if cfg.pcb_file is None:
        return GateOutcome(
            name=_STACKUP_CONSISTENCY_GATE,
            status="BLOCKED",
            summary="PCB file must be configured first.",
        )
    try:
        pcb_text = cfg.pcb_file.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return GateOutcome(
            name=_STACKUP_CONSISTENCY_GATE,
            status="BLOCKED",
            summary=f"Could not read PCB file: {exc}",
        )

    table_layers = _pcb_layer_table_copper_layers(pcb_text)
    stackup_layers = _pcb_stackup_copper_layers(pcb_text)
    details = [
        f"Layer table copper layers: {', '.join(table_layers) or '(none)'}",
        f"Stackup copper layers: {', '.join(stackup_layers) or '(none)'}",
    ]
    if not table_layers:
        return GateOutcome(
            name=_STACKUP_CONSISTENCY_GATE,
            status="FAIL",
            summary="The PCB layer table contains no copper layers.",
            details=details,
        )
    if not stackup_layers:
        return GateOutcome(
            name=_STACKUP_CONSISTENCY_GATE,
            status="WARN",
            summary="The PCB has copper layers but no explicit stackup profile.",
            details=details,
        )
    missing_in_table = sorted(set(stackup_layers) - set(table_layers))
    missing_in_stackup = sorted(set(table_layers) - set(stackup_layers))
    if missing_in_table or missing_in_stackup or len(table_layers) != len(stackup_layers):
        details.extend(
            [
                "Missing from layer table: " + (", ".join(missing_in_table) or "none"),
                "Missing from stackup: " + (", ".join(missing_in_stackup) or "none"),
            ]
        )
        return GateOutcome(
            name=_STACKUP_CONSISTENCY_GATE,
            status="FAIL",
            summary="Board layer table and stackup copper layers are inconsistent.",
            details=details,
        )
    return GateOutcome(
        name=_STACKUP_CONSISTENCY_GATE,
        status="PASS",
        summary=f"Layer table and stackup agree on {len(table_layers)} copper layer(s).",
        details=details,
    )


def _evaluate_route_corner_style_gate(
    *,
    max_90_degree_corners: int = 0,
    min_segment_length_mm: float = 0.25,
) -> GateOutcome:
    cfg = get_config()
    if cfg.pcb_file is None:
        return GateOutcome(
            name=_ROUTE_CORNER_STYLE_GATE,
            status="BLOCKED",
            summary="PCB file must be configured first.",
        )
    try:
        pcb_text = cfg.pcb_file.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return GateOutcome(
            name=_ROUTE_CORNER_STYLE_GATE,
            status="BLOCKED",
            summary=f"Could not read PCB file: {exc}",
        )
    segments = _pcb_track_segments_from_text(pcb_text)
    corners = _route_90_degree_corners(
        segments,
        min_segment_length_mm=min_segment_length_mm,
    )
    details = [
        f"Track segments scanned: {len(segments)}",
        f"90° route corners found: {len(corners)}",
        f"Allowed 90° route corners: {max_90_degree_corners}",
        *corners[:30],
    ]
    if len(corners) > max_90_degree_corners:
        return GateOutcome(
            name=_ROUTE_CORNER_STYLE_GATE,
            status="FAIL",
            summary=(
                "PCB routing contains right-angle corners that should be "
                "refactored to chamfered or rounded geometry."
            ),
            details=details,
        )
    return GateOutcome(
        name=_ROUTE_CORNER_STYLE_GATE,
        status="PASS",
        summary="PCB route corners satisfy the configured 45°/rounded-style policy.",
        details=details,
    )


def _evaluate_professional_release_gate(
    *,
    max_90_degree_corners: int = 0,
    manufacturer: str | None = None,
    tier: str | None = None,
) -> GateOutcome:
    outcomes = [
        _evaluate_schematic_gate(),
        _evaluate_pcb_gate(),
        _evaluate_pcb_transfer_gate(),
        _evaluate_pcb_placement_gate(),
        _evaluate_stackup_consistency_gate(),
        _evaluate_route_corner_style_gate(max_90_degree_corners=max_90_degree_corners),
        _evaluate_manufacturing_gate(manufacturer=manufacturer, tier=tier),
    ]
    status = _combined_status(outcomes)
    details: list[str] = []
    for outcome in outcomes:
        details.append(f"{outcome.name}: {outcome.status} — {outcome.summary}")
        details.extend(f"  {detail}" for detail in outcome.details[:8])
    return GateOutcome(
        name="Professional release",
        status=status,
        summary="All professional release gates passed."
        if status == "PASS"
        else "One or more professional release gates require attention.",
        details=details,
    )


def _drc_state_path() -> Path:
    cfg = get_config()
    if cfg.project_dir is None:
        raise ValueError(_NO_ACTIVE_PROJECT_ERROR)
    target = cfg.project_dir / ".kicad-mcp"
    target.mkdir(parents=True, exist_ok=True)
    return target / "drc_rules_state.json"


def _write_drc_state(path: Path, payload: dict[str, object]) -> Path:
    cfg = get_config()
    if cfg.project_dir is None:
        raise ValueError(_NO_ACTIVE_PROJECT_ERROR)
    safe_path = resolve_under(cfg.project_dir, path)
    with safe_path.open("w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2))
    return safe_path


def _load_drc_state() -> dict[str, object]:
    path = _drc_state_path()
    if not path.exists():
        payload: dict[str, object] = {"enabled": {}, "severity": {}}
        _write_drc_state(path, payload)
        return payload
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _save_drc_state(payload: dict[str, object]) -> Path:
    return _write_drc_state(_drc_state_path(), payload)


def _rule_child_nodes(
    rule: SExprNode,
    child_name: str,
) -> list[SExprNode]:
    return [
        child for child in rule[2:] if isinstance(child, list) and child and child[0] == child_name
    ]


def _replace_rule_child(
    rule: SExprNode,
    child_name: str,
    replacement: SExprNode,
) -> SExprNode:
    updated: SExprNode = []
    replaced = False
    for child in rule:
        if isinstance(child, list) and child and child[0] == child_name and not replaced:
            updated.append(replacement)
            replaced = True
            continue
        if isinstance(child, list) and child and child[0] == child_name:
            continue
        updated.append(child)
    if not replaced:
        updated.append(replacement)
    return updated


def _rule_payload(rule: SExprNode, state: dict[str, object]) -> dict[str, object]:
    rule_name = str(rule[1]) if len(rule) > 1 and not isinstance(rule[1], list) else "unknown"
    condition_nodes = _rule_child_nodes(rule, "condition")
    constraint_nodes = _rule_child_nodes(rule, "constraint")
    severity_nodes = _rule_child_nodes(rule, "severity")
    enabled_state = cast(dict[str, bool], state.get("enabled", {}))
    severity_state = cast(dict[str, str], state.get("severity", {}))
    parsed_condition = (
        str(condition_nodes[0][1])
        if condition_nodes
        and len(condition_nodes[0]) > 1
        and not isinstance(condition_nodes[0][1], list)
        else ""
    )
    parsed_severity = (
        str(severity_nodes[0][1])
        if severity_nodes
        and len(severity_nodes[0]) > 1
        and not isinstance(severity_nodes[0][1], list)
        else "error"
    )
    effective_severity = severity_state.get(rule_name, parsed_severity)
    payload: dict[str, object] = {
        "name": rule_name,
        "condition": parsed_condition,
        "constraints": [
            str(child[1])
            for child in constraint_nodes
            if len(child) > 1 and not isinstance(child[1], list)
        ],
        "severity": effective_severity,
        "enabled": enabled_state.get(rule_name, parsed_severity != "ignore"),
    }
    return payload


def _coerce_constraint_value(value: float | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip()
    return f"{value}"


def _build_constraint_node(
    constraint_type: str,
    min_value: float | str | None,
    max_value: float | str | None,
) -> SExprNode:
    if not re.fullmatch(r"[A-Za-z_]\w*", constraint_type):
        raise ValueError("constraint_type must be a simple KiCad rule atom such as clearance.")
    node: SExprNode = ["constraint", constraint_type]
    min_atom = _coerce_constraint_value(min_value)
    max_atom = _coerce_constraint_value(max_value)
    if min_atom is not None:
        node.append(["min", min_atom])
    if max_atom is not None:
        node.append(["max", max_atom])
    return node


def _register_drc_rule_tools(mcp: FastMCP) -> None:
    """Register custom DRC rule management tools."""

    @mcp.tool()
    @headless_compatible
    def drc_list_rules(include_custom: bool = True) -> str:
        """List known DRC rules from the active ``.kicad_dru`` file."""
        from .routing_rules import _load_rules_content, _rules_file_path

        built_in = [
            {"name": "clearance", "source": "built-in"},
            {"name": "track_width", "source": "built-in"},
            {"name": "via_diameter", "source": "built-in"},
            {"name": "hole_to_hole", "source": "built-in"},
        ]
        if not include_custom:
            return json.dumps({"rules": built_in}, indent=2)

        content = _load_rules_content(_rules_file_path())
        root, _version = parse_dru(content)
        state = _load_drc_state()
        custom = [_rule_payload(rule, state) for rule in iter_rule_nodes(root)]
        return json.dumps({"rules": [*built_in, *custom]}, indent=2)

    @mcp.tool()
    @headless_compatible
    def drc_check_rule_conflicts() -> str:
        """Report conflicting or unsatisfiable rules in the active ``.kicad_dru``.

        Flags duplicate rule names (KiCad keeps only the last), two scoped rules
        setting different minimums for the same constraint and condition,
        inverted min/max bounds, and negative dimensions. Useful after generating
        constraints from several sources (net classes, interface binders,
        manufacturer profiles) to reconcile them to one truth.
        """
        from ..utils.dru_analysis import analyze_rule_conflicts
        from .routing_rules import _load_rules_content, _rules_file_path

        root, _version = parse_dru(_load_rules_content(_rules_file_path()))
        conflicts = analyze_rule_conflicts(root)
        return json.dumps(
            {
                "conflict_count": len(conflicts),
                "conflicts": [
                    {
                        "kind": c.kind,
                        "severity": c.severity,
                        "message": c.message,
                        "rules": list(c.rules),
                    }
                    for c in conflicts
                ],
            },
            indent=2,
        )

    @mcp.tool()
    @headless_compatible
    def drc_rule_create(
        name: str,
        constraint_type: str,
        min_value: float | str | None = None,
        max_value: float | str | None = None,
        condition: str | None = None,
        severity: str = "error",
    ) -> str:
        """Create or update a custom DRC rule in the active ``.kicad_dru`` file."""
        from .routing_rules import _load_rules_content, _rules_file_path, _write_rules_content

        if not name.strip():
            raise ValueError("Rule name must not be empty.")
        if not re.fullmatch(r"[a-z_]+", severity.casefold()):
            raise ValueError("severity must be a simple KiCad severity atom such as error.")

        rule_node: SExprNode = [
            "rule",
            name,
            ["condition", condition or "A.Type != 'none'"],
            _build_constraint_node(constraint_type, min_value, max_value),
            ["severity", severity],
        ]
        path = _rules_file_path()
        root, version = parse_dru(_load_rules_content(path))
        upsert_rule(root, rule_node)
        path = _write_rules_content(path, dump_dru(root, version=version))
        state = _load_drc_state()
        cast(dict[str, bool], state.setdefault("enabled", {}))[name] = True
        cast(dict[str, str], state.setdefault("severity", {}))[name] = severity
        _save_drc_state(state)
        return f"Custom DRC rule '{name}' written to {path}."

    @mcp.tool()
    @headless_compatible
    def drc_rule_delete(rule_name: str) -> str:
        """Delete a custom DRC rule from the active rules file."""
        from .routing_rules import _load_rules_content, _rules_file_path, _write_rules_content

        path = _rules_file_path()
        root, version = parse_dru(_load_rules_content(path))
        if not delete_rule(root, rule_name):
            raise ValueError(f"Rule '{rule_name}' was not found.")
        path = _write_rules_content(path, dump_dru(root, version=version))
        state = _load_drc_state()
        cast(dict[str, bool], state.setdefault("enabled", {})).pop(rule_name, None)
        cast(dict[str, str], state.setdefault("severity", {})).pop(rule_name, None)
        _save_drc_state(state)
        return f"Deleted custom DRC rule '{rule_name}' from {path}."

    @mcp.tool()
    @headless_compatible
    def drc_rule_enable(rule_name: str, enabled: bool = True) -> str:
        """Enable or disable a custom DRC rule."""
        from .routing_rules import _load_rules_content, _rules_file_path, _write_rules_content

        path = _rules_file_path()
        root, version = parse_dru(_load_rules_content(path))
        rule = find_rule(root, rule_name)
        if rule is None:
            return f"Custom DRC rule '{rule_name}' was not found."

        state = _load_drc_state()
        severity_map = cast(dict[str, str], state.setdefault("severity", {}))
        enabled_map = cast(dict[str, bool], state.setdefault("enabled", {}))
        severity_nodes = _rule_child_nodes(rule, "severity")
        parsed_severity = (
            str(severity_nodes[0][1])
            if severity_nodes
            and len(severity_nodes[0]) > 1
            and not isinstance(severity_nodes[0][1], list)
            else "error"
        )
        existing_severity = severity_map.get(rule_name) or parsed_severity
        severity_map[rule_name] = existing_severity
        enabled_map[rule_name] = enabled

        replacement = _replace_rule_child(
            rule,
            "severity",
            ["severity", "ignore" if not enabled else existing_severity],
        )
        upsert_rule(root, replacement)
        path = _write_rules_content(path, dump_dru(root, version=version))
        _save_drc_state(state)
        state_text = "enabled" if enabled else "disabled"
        return f"Custom DRC rule '{rule_name}' {state_text}."

    @mcp.tool()
    @headless_compatible
    def drc_export_rules(output_path: str | None = None) -> str:
        """Export the active custom DRC rules file for sharing or CI."""
        from .routing_rules import _rules_file_path

        source = _rules_file_path()
        cfg = get_config()
        target = (
            cfg.resolve_within_project(output_path, allow_absolute=False)
            if output_path
            else cfg.ensure_output_dir("drc") / source.name
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        return f"Custom DRC rules exported to {target}."


def _execute_validate_design() -> str:
    _, drc_report, drc_error = _run_drc_report("validate_drc.json")
    _, erc_report, erc_error = _run_erc_report("validate_erc.json")

    lines = ["Design validation summary:"]
    if drc_report is not None:
        lines.append(
            f"- DRC: {len(_entries(drc_report, 'violations'))} violations, "
            f"{len(_entries(drc_report, 'unconnected_items'))} unconnected items"
        )
    else:
        lines.append(f"- DRC: unavailable ({drc_error})")

    if erc_report is not None:
        lines.append(f"- ERC: {len(_erc_violations(erc_report))} violations")
    else:
        lines.append(f"- ERC: unavailable ({erc_error})")
    return "\n".join(lines)


def _pcb_score_placement_impl() -> str:
    analysis, blocked = _placement_analysis()
    if blocked is not None:
        return "\n".join(
            [
                "Placement score: BLOCKED",
                f"- {blocked.summary}",
                *[f"- {detail}" for detail in blocked.details],
            ]
        )
    if analysis is None:
        raise RuntimeError(_MISSING_PLACEMENT_ANALYSIS)
    return _format_placement_score(analysis)


def _project_signoff_report_impl(manufacturer: str, tier: str) -> str:
    from .project import load_design_intent
    from .signoff import build_signoff_report, render_signoff_report

    outcomes = _evaluate_project_gate(manufacturer=manufacturer or None, tier=tier or None)
    intent = load_design_intent()
    release_evidence = _release_evidence_for_active_project()
    report = build_signoff_report(
        intent.model_dump(),
        outcomes,
        _signoff_provenance(intent),
        release_evidence if release_evidence.adopted else None,
    )
    return render_signoff_report(report)


def _project_release_readiness_impl(
    manufacturer: str,
    tier: str,
    output_path: str,
    export_format: str,
) -> ProjectReleaseReadinessPayload:
    payload = _build_project_release_readiness_payload(
        manufacturer=manufacturer or None,
        tier=tier or None,
    )
    if output_path:
        payload.exported_report_path = _export_release_readiness_report(
            payload,
            output_path=output_path,
            export_format=export_format,
        )
    return payload


def _register_schematic_gate_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    @headless_compatible
    def run_erc(save_report: bool = False) -> VerdictReport:
        """Run schematic electrical rule checks."""
        path, report, error = _run_erc_report("erc_report.json")
        return _erc_report_payload(path, report, error, save_report=save_report)

    @mcp.tool()
    @headless_compatible
    def schematic_quality_gate() -> VerdictReport:
        """Evaluate whether the schematic is clean enough to proceed."""
        return _gate_report(_evaluate_schematic_gate())

    @mcp.tool()
    @headless_compatible
    def schematic_connectivity_gate() -> VerdictReport:
        """Evaluate whether schematic structure and hierarchy look electrically meaningful."""
        return _gate_report(_evaluate_schematic_connectivity_gate())

    @mcp.tool()
    @headless_compatible
    def schematic_design_rule_check() -> VerdictReport:
        """Check the schematic against professional electrical-design rules (advisory).

        Beyond ERC connectivity: flags supply rails that feed ICs without a
        decoupling capacitor and I2C buses without pull-up resistors. This is an
        advisory critic (WARN), not a hard release gate, so it complements
        ``run_erc()`` rather than replacing it.
        """
        return _gate_report(_evaluate_schematic_design_rule_gate())


def _register_pcb_gate_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    @headless_compatible
    def run_drc(save_report: bool = False) -> VerdictReport:
        """Return full DRC report with PCB violations, unconnected items, and courtyard issues."""
        path, report, error = _run_drc_report("drc_report.json")
        return _drc_report_payload(path, report, error, save_report=save_report)

    @mcp.tool()
    @headless_compatible
    def validate_design() -> str:
        """Run DRC and ERC and summarize readiness."""
        return _execute_validate_design()

    @mcp.tool()
    @headless_compatible
    def pcb_quality_gate() -> VerdictReport:
        """Evaluate whether the PCB is physically clean enough to proceed."""
        return _gate_report(_evaluate_pcb_gate())

    @mcp.tool()
    @headless_compatible
    def pcb_placement_quality_gate() -> VerdictReport:
        """Evaluate whether footprint placement is overlap-free and inside the board frame."""
        return _gate_report(_evaluate_pcb_placement_gate())

    @mcp.tool()
    @headless_compatible
    def pcb_placement_quality_report() -> PlacementGateReportPayload:
        """Return a structured placement-quality report for capable MCP clients."""
        return _placement_gate_report_payload()

    @mcp.tool()
    @headless_compatible
    def pcb_transfer_quality_gate() -> VerdictReport:
        """Evaluate whether named schematic pad nets transferred cleanly onto PCB pads."""
        return _gate_report(_evaluate_pcb_transfer_gate())

    @mcp.tool()
    @headless_compatible
    def pcb_stackup_consistency_gate() -> VerdictReport:
        """Validate board layer table and stackup copper layer consistency."""
        return _gate_report(_evaluate_stackup_consistency_gate())

    @mcp.tool()
    @headless_compatible
    def pcb_route_corner_style_gate(
        max_90_degree_corners: int = 0,
        min_segment_length_mm: float = 0.25,
    ) -> VerdictReport:
        """Check whether routed tracks still contain non-professional 90-degree corners."""
        return _gate_report(
            _evaluate_route_corner_style_gate(
                max_90_degree_corners=max_90_degree_corners,
                min_segment_length_mm=min_segment_length_mm,
            )
        )


def _register_project_bundle_gate_tools(mcp: FastMCP) -> None:
    @mcp.tool()
    @headless_compatible
    def project_professional_release_gate(
        max_90_degree_corners: int = 0,
        manufacturer: str = "",
        tier: str = "",
    ) -> VerdictReport:
        """Run the professional release gate bundle before manufacturing handoff."""
        return _gate_report(
            _evaluate_professional_release_gate(
                max_90_degree_corners=max_90_degree_corners,
                manufacturer=manufacturer or None,
                tier=tier or None,
            )
        )

    @mcp.tool()
    @headless_compatible
    def pcb_score_placement() -> str:
        """Score PCB placement quality and explain both hard failures and softer warnings."""
        return _pcb_score_placement_impl()

    @mcp.tool()
    @headless_compatible
    def manufacturing_quality_gate(
        manufacturer: str = "",
        tier: str = "",
    ) -> VerdictReport:
        """Evaluate manufacturing readiness against the active or requested DFM profile."""
        outcome = _evaluate_manufacturing_gate(
            manufacturer=manufacturer or None,
            tier=tier or None,
        )
        return _gate_report(outcome)

    @mcp.tool()
    @headless_compatible
    def project_quality_gate(
        manufacturer: str = "",
        tier: str = "",
    ) -> VerdictReport:
        """Run the full project quality gate across schematic, PCB, DFM, and parity checks."""
        outcomes = _evaluate_project_gate(
            manufacturer=manufacturer or None,
            tier=tier or None,
        )
        return _project_gate_verdict_report(outcomes)

    @mcp.tool()
    @headless_compatible
    def project_quality_gate_report(
        manufacturer: str = "",
        tier: str = "",
    ) -> ProjectGateReportPayload:
        """Return the full project gate in structured form for capable MCP clients."""
        outcomes = _evaluate_project_gate(
            manufacturer=manufacturer or None,
            tier=tier or None,
        )
        return _project_gate_report_payload(outcomes)

    @mcp.tool()
    @headless_compatible
    def project_signoff_report(manufacturer: str = "", tier: str = "") -> str:
        """Produce the single manufacturing sign-off report.

        Binds each declared design-intent requirement to the gate check(s) that
        would catch a violation, attaches the gate evidence and full provenance
        (engine versions, rule profile, intent and source hashes), and returns one
        PASS/FAIL verdict. A board with no declared intent is UNVERIFIED, not a
        silent PASS. ``export_manufacturing_package`` is hard-gated on the same
        underlying project gate, so a PASS here means the package will export.
        """
        return _project_signoff_report_impl(manufacturer=manufacturer, tier=tier)

    @mcp.tool()
    @headless_compatible
    def project_release_readiness(
        manufacturer: str = "",
        tier: str = "",
        output_path: str = "",
        export_format: str = "",
    ) -> ProjectReleaseReadinessPayload:
        """Assemble a release-readiness evidence bundle for human manufacturing review.

        Aggregates project gate results, DRC/ERC summaries, BOM completeness,
        waiver state, release artifacts, and manifest presence into one structured,
        text-renderable payload. Missing required evidence fails closed.

        When ``output_path`` is provided, the bundle is also written as JSON,
        Markdown, HTML, or a print-friendly HTML report (``pdf-ready``).
        """
        return _project_release_readiness_impl(
            manufacturer=manufacturer,
            tier=tier,
            output_path=output_path,
            export_format=export_format,
        )


def _register_validation_gate_tools(mcp: FastMCP) -> None:
    """Register DRC, ERC, and project quality-gate tools."""
    _register_schematic_gate_tools(mcp)
    _register_pcb_gate_tools(mcp)
    _register_project_bundle_gate_tools(mcp)


def _register_targeted_validation_tools(mcp: FastMCP) -> None:
    """Register targeted DFM and violation-reporting tools."""

    @mcp.tool()
    @headless_compatible
    def check_design_for_manufacture(jlcpcb: bool = True) -> str:
        """Run a lightweight DFM check using available DRC data."""
        from .dfm import _dfm_check_lines, _load_profile

        profile = _load_profile("JLCPCB" if jlcpcb else "PCBWay", "standard")
        heading = f"DFM check ({'JLCPCB' if jlcpcb else 'generic'} profile):"
        return "\n".join(_dfm_check_lines(profile, heading=heading))

    @mcp.tool()
    @headless_compatible
    def get_unconnected_nets() -> str:
        """Return only unconnected DRC issues for focused follow-up after run_drc."""
        _, report, error = _run_drc_report("unconnected.json")
        if report is None:
            return f"Unable to compute unconnected nets: {error or 'unknown error'}"

        entries = _entries(report, "unconnected_items")
        if not entries:
            return "No unconnected nets were reported."
        return _format_violations("Unconnected nets", entries)

    @mcp.tool()
    @headless_compatible
    def get_courtyard_violations() -> str:
        """Return only courtyard DRC issues for focused follow-up after run_drc."""
        _, report, error = _run_drc_report("courtyard.json")
        if report is None:
            return f"Unable to compute courtyard issues: {error or 'unknown error'}"

        entries = courtyard_violations(report)
        if not entries:
            return "No courtyard violations were reported."
        return _format_violations("Courtyard violations", entries)

    @mcp.tool()
    @headless_compatible
    def get_silk_to_pad_violations() -> str:
        """Return silkscreen overlap issues from DRC."""
        _, report, error = _run_drc_report("silk_to_pad.json")
        if report is None:
            return f"Unable to compute silk-to-pad issues: {error or 'unknown error'}"

        entries = [
            entry
            for entry in _entries(report, "violations")
            if "silk" in str(entry.get("description", "")).lower()
            and "pad" in str(entry.get("description", "")).lower()
        ]
        if not entries:
            return "No silk-to-pad violations were reported."
        return _format_violations("Silk-to-pad violations", entries)

    @mcp.tool()
    @headless_compatible
    def validate_footprints_vs_schematic() -> str:
        """Compare PCB footprint references against the schematic symbol references."""
        outcome = _footprint_parity_outcome()
        lines = [
            "Footprint versus schematic comparison:",
            f"- Status: {outcome.status}",
            f"- {outcome.summary}",
        ]
        lines.extend(f"- {detail}" for detail in outcome.details)
        return "\n".join(lines)


def register(mcp: FastMCP) -> None:
    """Register validation tools."""

    _register_drc_rule_tools(mcp)

    _register_validation_gate_tools(mcp)

    _register_targeted_validation_tools(mcp)

    # ── FAZ 5.1 — DRC Exclusion tools ──────────────────────────────────

    validation_policy_state.register(
        mcp,
        validation_policy_state.ValidationPolicyStateDependencies(
            service=ValidationPolicyStateService(
                project_dir=lambda: get_config().project_dir,
                run_drc_report=_run_drc_report,
                report_entries=_entries,
            )
        ),
    )
