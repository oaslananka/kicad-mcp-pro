"""Validation and design-check tools."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, cast

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..connection import KiCadConnectionError, get_board
from ..models.component_contracts import find_component_contract
from .export import _ensure_output_dir, _get_pcb_file, _get_sch_file, _run_cli_variants
from .metadata import headless_compatible

GateStatus = Literal["PASS", "FAIL", "BLOCKED"]


@dataclass(slots=True)
class GateOutcome:
    """Structured status for a validation gate."""

    name: str
    status: GateStatus
    summary: str
    details: list[str] = field(default_factory=list)


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


def _load_report(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _entries(report: dict[str, object], key: str) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], report.get(key, []))


def _erc_violations(report: dict[str, object]) -> list[dict[str, object]]:
    violations = list(_entries(report, "violations"))
    for sheet in cast(list[dict[str, object]], report.get("sheets", [])):
        violations.extend(cast(list[dict[str, object]], sheet.get("violations", [])))
    return violations


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


def _run_drc_report(report_name: str) -> tuple[Path, dict[str, object] | None, str | None]:
    pcb_file = _get_pcb_file()
    out_file = _ensure_output_dir() / report_name
    code, _, stderr = _run_cli_variants(
        [
            [
                "pcb",
                "drc",
                "--output",
                str(out_file),
                "--format",
                "json",
                "--severity-all",
                "--exit-code-violations",
                str(pcb_file),
            ],
            [
                "pcb",
                "drc",
                "--input",
                str(pcb_file),
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
        return out_file, None, stderr if code != 0 else "DRC report was not produced."
    return out_file, _load_report(out_file), None


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


def _board_footprint_references() -> tuple[set[str], str, str | None]:
    try:
        return (
            {
                footprint.reference_field.text.value
                for footprint in get_board().get_footprints()
                if footprint.reference_field.text.value
            },
            "IPC",
            None,
        )
    except (KiCadConnectionError, OSError):
        from .pcb import _parse_board_footprint_blocks

        try:
            board_text = _get_pcb_file().read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            return set(), "file", str(exc)
        return set(_parse_board_footprint_blocks(board_text)), "file", None


def _footprint_parity_outcome() -> GateOutcome:
    from .schematic import parse_schematic_file

    cfg = get_config()
    if cfg.sch_file is None or cfg.pcb_file is None:
        return GateOutcome(
            name="Footprint parity",
            status="BLOCKED",
            summary="Both schematic and PCB files must be configured first.",
        )

    schematic = parse_schematic_file(cfg.sch_file)
    schematic_refs = {
        str(symbol["reference"])
        for symbol in schematic["symbols"]
        if str(symbol["reference"]).strip()
        and not str(symbol["reference"]).startswith("#")
        and str(symbol["footprint"]).strip()
    }
    board_refs, source, error = _board_footprint_references()
    if error is not None:
        return GateOutcome(
            name="Footprint parity",
            status="BLOCKED",
            summary=f"PCB references were unavailable via {source} mode ({error}).",
        )

    missing_on_board = sorted(schematic_refs - board_refs)
    missing_in_schematic = sorted(board_refs - schematic_refs)
    status: GateStatus = "PASS" if not missing_on_board and not missing_in_schematic else "FAIL"
    details = [
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
        name="Footprint parity",
        status=status,
        summary="PCB and schematic references are aligned."
        if status == "PASS"
        else "Schematic and PCB references are out of sync.",
        details=details,
    )


def _evaluate_pcb_transfer_gate() -> GateOutcome:
    from .pcb import (
        _collect_schematic_components,
        _export_schematic_net_map,
        _parse_board_footprint_blocks,
    )

    cfg = get_config()
    if cfg.sch_file is None or cfg.pcb_file is None:
        return GateOutcome(
            name="PCB transfer",
            status="BLOCKED",
            summary="Both schematic and PCB files must be configured first.",
        )

    try:
        components, issues = _collect_schematic_components()
    except ValueError as exc:
        return GateOutcome(
            name="PCB transfer",
            status="BLOCKED",
            summary=str(exc),
        )
    if issues:
        return GateOutcome(
            name="PCB transfer",
            status="FAIL",
            summary="Schematic component metadata is not stable enough for pad-net transfer.",
            details=issues[:12],
        )

    expected_map, note = _export_schematic_net_map()
    if note:
        return GateOutcome(
            name="PCB transfer",
            status="BLOCKED",
            summary=note,
        )
    if not expected_map:
        return GateOutcome(
            name="PCB transfer",
            status="BLOCKED",
            summary="The schematic did not export any named pad nets to compare against the PCB.",
        )

    try:
        board_text = cfg.pcb_file.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return GateOutcome(
            name="PCB transfer",
            status="BLOCKED",
            summary=f"Could not read the PCB file ({exc}).",
        )

    footprints = _parse_board_footprint_blocks(board_text)
    component_refs = {str(component["reference"]) for component in components}
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
        for pad_number, expected_net in expected_for_ref:
            total_expected_pads += 1
            actual_net = actual_pad_nets.get(pad_number, "")
            if not actual_net:
                mismatches.append(f"{reference}.{pad_number}: missing net '{expected_net}' on PCB.")
                continue
            if actual_net != expected_net:
                mismatches.append(
                    f"{reference}.{pad_number}: PCB has '{actual_net}', expected '{expected_net}'."
                )
                continue
            matched_pads += 1

    if total_expected_pads == 0:
        return GateOutcome(
            name="PCB transfer",
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
        name="PCB transfer",
        status=status,
        summary="Named schematic pad nets match the PCB footprint pads."
        if status == "PASS"
        else "Named schematic pad nets did not transfer cleanly to the PCB.",
        details=details,
    )


def _evaluate_schematic_gate() -> GateOutcome:
    from .schematic import _build_connectivity_groups, parse_schematic_file

    _, report, error = _run_erc_report("schematic_quality_gate.json")
    if report is None:
        return GateOutcome(
            name="Schematic",
            status="BLOCKED",
            summary=f"ERC report was unavailable ({error or 'unknown error'}).",
        )

    violations = _erc_violations(report)
    cfg = get_config()
    details = [f"ERC violations: {len(violations)}"]
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


def _hierarchical_labels(sch_file: Path) -> set[str]:
    from ..utils.sexpr import _unescape_sexpr_string

    content = sch_file.read_text(encoding="utf-8", errors="ignore")
    return {
        _unescape_sexpr_string(match.group(1))
        for match in re.finditer(r'\(hierarchical_label\s+"((?:\\.|[^"\\])*)"', content)
    }


def _evaluate_schematic_connectivity_gate() -> GateOutcome:
    from .schematic import _build_connectivity_groups, parse_schematic_file

    try:
        top_file = _get_sch_file()
    except ValueError as exc:
        return GateOutcome(
            name="Schematic connectivity",
            status="BLOCKED",
            summary=str(exc),
        )

    pages: list[tuple[str, Path]] = [("Top level", top_file)]
    blocked: list[str] = []
    failures: list[str] = []
    page_summaries: list[str] = []
    try:
        contracts = _sheet_contracts(top_file)
    except OSError as exc:
        return GateOutcome(
            name="Schematic connectivity",
            status="BLOCKED",
            summary=f"Top-level sheet contract data was unavailable ({exc}).",
        )

    for contract in contracts:
        child_path = top_file.parent / str(contract["filename"])
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

    dangling_labels = 0
    zero_wire_pages = 0
    unnamed_single_pin_groups = 0
    isolated_footprint_symbols = 0
    matched_component_contracts = 0
    contract_violations = 0

    for page_name, page_path in pages:
        if not page_path.exists():
            continue
        try:
            data = parse_schematic_file(page_path)
            groups = _build_connectivity_groups(page_path)
        except (OSError, RuntimeError, ValueError) as exc:
            blocked.append(f"{page_name}: connectivity data was unavailable ({exc}).")
            continue

        symbol_count = len(data["symbols"]) + len(data["power_symbols"])
        label_count = len(data["labels"])
        wire_count = len(data["wires"])
        page_summaries.append(
            f"{page_name}: {symbol_count} symbol(s), {label_count} label(s), {wire_count} wire(s)"
        )

        if wire_count == 0 and (symbol_count >= 2 or label_count >= 3):
            zero_wire_pages += 1
            failures.append(
                f"{page_name}: has {symbol_count} symbol(s) and {label_count} label(s) but 0 wires."
            )

        label_only_groups = [
            group
            for group in groups
            if group["names"] and not group["pins"] and len(group["points"]) == 1
        ]
        dangling_labels += len(label_only_groups)
        for group in label_only_groups[:8]:
            failures.append(
                f"{page_name}: unattached label/group at {group['points'][0]} -> "
                + ", ".join(group["names"][:4])
            )

        unnamed_groups = [
            group for group in groups if not group["names"] and len(group["pins"]) == 1
        ]
        unnamed_single_pin_groups += len(unnamed_groups)
        for group in unnamed_groups[:8]:
            pin = cast(dict[str, str], group["pins"][0])
            failures.append(
                f"{page_name}: unnamed single-pin group at {group['points'][0]} -> "
                f"{pin['reference']}:{pin['pin']}"
            )

        for symbol in cast(list[dict[str, object]], data["symbols"]):
            footprint = str(symbol.get("footprint", "")).strip()
            lib_id = str(symbol.get("lib_id", "")).strip()
            if not footprint:
                continue
            reference = str(symbol.get("reference", "")).strip()
            component_contract = find_component_contract(lib_id=lib_id, footprint=footprint)
            if component_contract is not None:
                matched_component_contracts += 1
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
                isolated_footprint_symbols += 1
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

    hierarchy_mismatches = sum("Hierarchy contract mismatch" in item for item in failures)
    details = [f"Pages analysed: {len(pages)}"]
    details.extend(page_summaries[:12])
    details.extend(
        [
            f"Dangling label groups: {dangling_labels}",
            f"Zero-wire pages: {zero_wire_pages}",
            f"Unnamed single-pin groups: {unnamed_single_pin_groups}",
            f"Isolated footprint symbols: {isolated_footprint_symbols}",
            f"Hierarchy contract mismatches: {hierarchy_mismatches}",
            f"Matched component contracts: {matched_component_contracts}",
            f"Component contract violations: {contract_violations}",
        ]
    )
    if blocked:
        details.extend(f"BLOCKED: {item}" for item in blocked[:12])
        return GateOutcome(
            name="Schematic connectivity",
            status="BLOCKED",
            summary="Connectivity checks could not complete for every sheet.",
            details=details,
        )
    if failures:
        details.extend(f"FAIL: {item}" for item in failures[:20])
        return GateOutcome(
            name="Schematic connectivity",
            status="FAIL",
            summary=(
                "Connectivity smells suggest the schematic is not ready for PCB or "
                "release work."
            ),
            details=details,
        )
    return GateOutcome(
        name="Schematic connectivity",
        status="PASS",
        summary="Connectivity structure looks consistent across the active schematic set.",
        details=details,
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
    courtyard = _entries(report, "items_not_passing_courtyard")
    blocking_count = len(violations) + len(unconnected) + len(courtyard)
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


def _placement_analysis() -> tuple[PlacementAnalysis | None, GateOutcome | None]:
    from .pcb import (
        _board_frame_mm,
        _normalize_board_content,
        _parse_board_footprint_blocks,
        _placement_boxes_overlap,
    )
    from .project import ProjectDesignIntent, load_design_intent

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
        intent = load_design_intent()
    except ValueError:
        intent = ProjectDesignIntent()

    min_x, min_y, max_x, max_y = _board_frame_mm(content, footprints)
    frame = (min_x, min_y, max_x, max_y)
    board_width_mm = max_x - min_x
    board_height_mm = max_y - min_y
    board_area_mm2 = max(board_width_mm * board_height_mm, 1.0)

    missing_position = [
        reference
        for reference, entry in footprints.items()
        if entry["x_mm"] is None or entry["y_mm"] is None
    ]
    overlaps: list[str] = []
    outside: list[str] = []
    connector_edge_violations: list[str] = []
    decoupling_distance_violations: list[str] = []
    keepout_violations: list[str] = []
    power_tree_violations: list[str] = []
    sensor_cluster_violations: list[str] = []
    analog_digital_violations: list[str] = []
    warnings: list[str] = []

    items = sorted(footprints.items())
    footprint_area_mm2 = sum(
        float(entry["width_mm"]) * float(entry["height_mm"]) for entry in footprints.values()
    )
    density_pct = round((footprint_area_mm2 / board_area_mm2) * 100.0, 2)
    board_diagonal = math.hypot(board_width_mm, board_height_mm)

    for index, (left_ref, left_entry) in enumerate(items):
        if left_entry["x_mm"] is None or left_entry["y_mm"] is None:
            continue
        left_x = float(left_entry["x_mm"])
        left_y = float(left_entry["y_mm"])
        left_w = float(left_entry["width_mm"])
        left_h = float(left_entry["height_mm"])
        if (
            left_x - (left_w / 2) < min_x
            or left_x + (left_w / 2) > max_x
            or left_y - (left_h / 2) < min_y
            or left_y + (left_h / 2) > max_y
        ):
            outside.append(left_ref)
        for right_ref, right_entry in items[index + 1 :]:
            if right_entry["x_mm"] is None or right_entry["y_mm"] is None:
                continue
            if _placement_boxes_overlap(
                left_x,
                left_y,
                left_w,
                left_h,
                float(right_entry["x_mm"]),
                float(right_entry["y_mm"]),
                float(right_entry["width_mm"]),
                float(right_entry["height_mm"]),
                0.0,
            ):
                overlaps.append(f"{left_ref}/{right_ref}")

    checked_connectors = 0
    for reference in intent.connector_refs:
        entry = footprints.get(reference)
        if entry is None:
            connector_edge_violations.append(f"Connector intent ref '{reference}' is missing.")
            continue
        checked_connectors += 1
        distance = _nearest_edge_distance(entry, frame)
        if distance is None:
            connector_edge_violations.append(
                f"Connector '{reference}' has no resolved placement to evaluate."
            )
            continue
        if distance > 5.0:
            connector_edge_violations.append(
                f"Connector '{reference}' is {distance:.2f} mm from the nearest edge."
            )

    checked_decoupling_pairs = 0
    for pair in intent.decoupling_pairs:
        ic_entry = footprints.get(pair.ic_ref)
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
        cap_distances: list[float] = []
        missing_caps: list[str] = []
        for cap_ref in pair.cap_refs:
            cap_entry = footprints.get(cap_ref)
            if cap_entry is None:
                missing_caps.append(cap_ref)
                continue
            if cap_entry["x_mm"] is None or cap_entry["y_mm"] is None:
                missing_caps.append(cap_ref)
                continue
            cap_distances.append(
                math.hypot(
                    float(ic_entry["x_mm"]) - float(cap_entry["x_mm"]),
                    float(ic_entry["y_mm"]) - float(cap_entry["y_mm"]),
                )
            )
        if missing_caps:
            decoupling_distance_violations.append(
                f"{pair.ic_ref}: missing or unresolved decoupling caps -> "
                + ", ".join(missing_caps[:12])
            )
        if cap_distances and min(cap_distances) > pair.max_distance_mm:
            decoupling_distance_violations.append(
                f"{pair.ic_ref}: nearest decoupling cap is {min(cap_distances):.2f} mm away "
                f"(limit {pair.max_distance_mm:.2f} mm)."
            )

    checked_keepouts = 0
    for region in intent.rf_keepout_regions:
        checked_keepouts += 1
        for reference, entry in footprints.items():
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
                keepout_violations.append(
                    f"{reference} overlaps RF keepout '{region.name}'."
                )

    checked_power_tree_refs = 0
    present_power_tree: list[str] = []
    for reference in intent.power_tree_refs:
        entry = footprints.get(reference)
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
        left_center = _entry_center(footprints[left_ref])
        right_center = _entry_center(footprints[right_ref])
        if left_center is None or right_center is None:
            continue
        step_distance = math.hypot(
            left_center[0] - right_center[0],
            left_center[1] - right_center[1],
        )
        if step_distance > board_diagonal * 0.75:
            power_tree_violations.append(
                f"Power-tree step '{left_ref} -> {right_ref}' spans {step_distance:.2f} mm."
            )
        elif step_distance > board_diagonal * 0.5:
            warnings.append(
                f"Power-tree step '{left_ref} -> {right_ref}' spans {step_distance:.2f} mm."
            )

    checked_sensor_cluster_refs = 0
    missing_sensor_refs = [
        reference
        for reference in intent.sensor_cluster_refs
        if reference not in footprints or _entry_center(footprints[reference]) is None
    ]
    if missing_sensor_refs:
        sensor_cluster_violations.append(
            "Sensor-cluster refs missing or unresolved: " + ", ".join(missing_sensor_refs[:12])
        )
    sensor_cluster_spread, present_sensor_refs = _group_spread_mm(
        intent.sensor_cluster_refs,
        footprints,
    )
    checked_sensor_cluster_refs = len(present_sensor_refs)
    if checked_sensor_cluster_refs >= 2:
        if sensor_cluster_spread > board_diagonal * 0.6:
            sensor_cluster_violations.append(
                f"Sensor cluster spreads {sensor_cluster_spread:.2f} mm across the board."
            )
        elif sensor_cluster_spread > board_diagonal * 0.35:
            warnings.append(
                f"Sensor cluster spreads {sensor_cluster_spread:.2f} mm across the board."
            )

    analog_refs = [
        reference
        for reference in intent.analog_refs
        if reference in footprints and _entry_center(footprints[reference]) is not None
    ]
    digital_refs = [
        reference
        for reference in intent.digital_refs
        if reference in footprints and _entry_center(footprints[reference]) is not None
    ]
    checked_analog_refs = len(analog_refs)
    checked_digital_refs = len(digital_refs)
    nearest_mixed_gap: tuple[float, str, str] | None = None
    for analog_ref in analog_refs:
        analog_entry = footprints[analog_ref]
        for digital_ref in digital_refs:
            digital_entry = footprints[digital_ref]
            gap = _bbox_gap_mm(analog_entry, digital_entry)
            if gap is None:
                continue
            candidate = (gap, analog_ref, digital_ref)
            if nearest_mixed_gap is None or candidate[0] < nearest_mixed_gap[0]:
                nearest_mixed_gap = candidate
    if nearest_mixed_gap is not None:
        gap, analog_ref, digital_ref = nearest_mixed_gap
        if gap < 1.0:
            analog_digital_violations.append(
                "Analog ref "
                f"'{analog_ref}' is only {gap:.2f} mm away from digital ref "
                f"'{digital_ref}'."
            )
        elif gap < 3.0:
            warnings.append(
                "Analog ref "
                f"'{analog_ref}' is only {gap:.2f} mm away from digital ref "
                f"'{digital_ref}'."
            )

    if density_pct > 70.0:
        warnings.append(f"Footprint density is high ({density_pct:.2f}%).")
    elif density_pct < 5.0 and len(footprints) >= 6:
        warnings.append(f"Footprint density is sparse ({density_pct:.2f}%).")

    footprint_span_x = 0.0
    footprint_span_y = 0.0
    placed_x = [float(entry["x_mm"]) for entry in footprints.values() if entry["x_mm"] is not None]
    placed_y = [float(entry["y_mm"]) for entry in footprints.values() if entry["y_mm"] is not None]
    if len(placed_x) >= 2 and len(placed_y) >= 2:
        footprint_span_x = max(placed_x) - min(placed_x)
        footprint_span_y = max(placed_y) - min(placed_y)
        if len(footprints) >= 6 and (
            footprint_span_x > board_width_mm * 0.7 or footprint_span_y > board_height_mm * 0.7
        ):
            warnings.append("Placement spans most of the board; clustering looks weak.")

    for net_name in intent.critical_nets:
        refs = sorted(
            reference
            for reference, entry in footprints.items()
            if net_name in cast(list[str], entry.get("net_names", []))
            and entry["x_mm"] is not None
            and entry["y_mm"] is not None
        )
        if len(refs) < 2:
            continue
        max_spread = 0.0
        for index, left_ref in enumerate(refs):
            left_entry = footprints[left_ref]
            for right_ref in refs[index + 1 :]:
                right_entry = footprints[right_ref]
                max_spread = max(
                    max_spread,
                    math.hypot(
                        float(left_entry["x_mm"]) - float(right_entry["x_mm"]),
                        float(left_entry["y_mm"]) - float(right_entry["y_mm"]),
                    ),
                )
        if max_spread > board_diagonal * 0.6:
            warnings.append(
                f"Critical net '{net_name}' spans {max_spread:.2f} mm across the board."
            )

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

    score = 100
    score -= min(len(overlaps) * 20, 40)
    score -= min(len(outside) * 20, 40)
    score -= min(len(connector_edge_violations) * 15, 30)
    score -= min(len(decoupling_distance_violations) * 15, 30)
    score -= min(len(keepout_violations) * 15, 30)
    score -= min(len(power_tree_violations) * 15, 30)
    score -= min(len(sensor_cluster_violations) * 15, 30)
    score -= min(len(analog_digital_violations) * 15, 30)
    score -= min(len(warnings) * 5, 20)

    return (
        PlacementAnalysis(
            footprint_count=len(footprints),
            board_width_mm=board_width_mm,
            board_height_mm=board_height_mm,
            board_area_mm2=board_area_mm2,
            footprint_area_mm2=footprint_area_mm2,
            density_pct=density_pct,
            score=max(score, 0),
            hard_failures=hard_failures,
            warnings=warnings,
            checked_connectors=checked_connectors,
            checked_decoupling_pairs=checked_decoupling_pairs,
            checked_keepouts=checked_keepouts,
            checked_power_tree_refs=checked_power_tree_refs,
            checked_analog_refs=checked_analog_refs,
            checked_digital_refs=checked_digital_refs,
            checked_sensor_cluster_refs=checked_sensor_cluster_refs,
        ),
        None,
    )


def _format_placement_score(analysis: PlacementAnalysis) -> str:
    lines = [
        f"Placement score: {analysis.score}/100",
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
        f"- Hard failures: {len(analysis.hard_failures)}",
        f"- Warnings: {len(analysis.warnings)}",
    ]
    lines.extend(f"- FAIL: {item}" for item in analysis.hard_failures[:12])
    lines.extend(f"- WARN: {item}" for item in analysis.warnings[:12])
    return "\n".join(lines)


def _evaluate_pcb_placement_gate() -> GateOutcome:
    analysis, blocked = _placement_analysis()
    if blocked is not None:
        return blocked
    if analysis is None:
        raise RuntimeError("Placement analysis unexpectedly returned no result.")

    status: GateStatus = "PASS" if not analysis.hard_failures else "FAIL"
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
        f"Placement score: {analysis.score}/100",
    ]
    details.extend(f"FAIL: {item}" for item in analysis.hard_failures[:12])
    details.extend(f"WARN: {item}" for item in analysis.warnings[:12])
    return GateOutcome(
        name="Placement",
        status=status,
        summary="Footprint placement is geometrically and contextually sane."
        if status == "PASS"
        else "Footprint placement still violates hard physical or intent-aware checks.",
        details=details,
    )


def _evaluate_manufacturing_gate(
    *,
    manufacturer: str | None = None,
    tier: str | None = None,
) -> GateOutcome:
    from .dfm import _dfm_check_lines, _load_profile, _selected_profile
    from .project import load_design_intent

    if manufacturer is None or tier is None:
        try:
            intent = load_design_intent()
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


def _evaluate_project_gate(
    *,
    manufacturer: str | None = None,
    tier: str | None = None,
) -> list[GateOutcome]:
    return [
        _evaluate_schematic_gate(),
        _evaluate_schematic_connectivity_gate(),
        _evaluate_pcb_gate(),
        _evaluate_pcb_placement_gate(),
        _evaluate_pcb_transfer_gate(),
        _evaluate_manufacturing_gate(manufacturer=manufacturer, tier=tier),
        _footprint_parity_outcome(),
    ]


def _combined_status(outcomes: list[GateOutcome]) -> GateStatus:
    statuses = {outcome.status for outcome in outcomes}
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "FAIL" in statuses:
        return "FAIL"
    return "PASS"


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
    lines.extend(_format_gate(outcome) for outcome in outcomes)
    return "\n\n".join(lines)


def register(mcp: FastMCP) -> None:
    """Register validation tools."""

    @mcp.tool()
    @headless_compatible
    def run_drc(save_report: bool = False) -> str:
        """Run PCB design rule checks."""
        path, report, error = _run_drc_report("drc_report.json")
        if report is None:
            return f"DRC failed: {error or 'unknown error'}"

        violations = _entries(report, "violations")
        unconnected = _entries(report, "unconnected_items")
        courtyard = _entries(report, "items_not_passing_courtyard")
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
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def run_erc(save_report: bool = False) -> str:
        """Run schematic electrical rule checks."""
        path, report, error = _run_erc_report("erc_report.json")
        if report is None:
            return f"ERC failed: {error or 'unknown error'}"

        violations = _erc_violations(report)
        lines = ["ERC summary:", f"- Violations: {len(violations)}"]
        if violations:
            lines.append(_format_violations("Violations", violations))
        if save_report:
            lines.append(f"Saved report: {path}")
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def validate_design() -> str:
        """Run DRC and ERC and summarize readiness."""
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

    @mcp.tool()
    @headless_compatible
    def schematic_quality_gate() -> str:
        """Evaluate whether the schematic is clean enough to proceed."""
        return _format_gate(_evaluate_schematic_gate())

    @mcp.tool()
    @headless_compatible
    def pcb_quality_gate() -> str:
        """Evaluate whether the PCB is physically clean enough to proceed."""
        return _format_gate(_evaluate_pcb_gate())

    @mcp.tool()
    @headless_compatible
    def schematic_connectivity_gate() -> str:
        """Evaluate whether schematic structure and hierarchy look electrically meaningful."""
        return _format_gate(_evaluate_schematic_connectivity_gate())

    @mcp.tool()
    @headless_compatible
    def pcb_placement_quality_gate() -> str:
        """Evaluate whether footprint placement is overlap-free and inside the board frame."""
        return _format_gate(_evaluate_pcb_placement_gate())

    @mcp.tool()
    @headless_compatible
    def pcb_transfer_quality_gate() -> str:
        """Evaluate whether named schematic pad nets transferred cleanly onto PCB pads."""
        return _format_gate(_evaluate_pcb_transfer_gate())

    @mcp.tool()
    @headless_compatible
    def pcb_score_placement() -> str:
        """Score PCB placement quality and explain both hard failures and softer warnings."""
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
            raise RuntimeError("Placement analysis unexpectedly returned no result.")
        return _format_placement_score(analysis)

    @mcp.tool()
    @headless_compatible
    def manufacturing_quality_gate(
        manufacturer: str = "",
        tier: str = "",
    ) -> str:
        """Evaluate manufacturing readiness against the active or requested DFM profile."""
        outcome = _evaluate_manufacturing_gate(
            manufacturer=manufacturer or None,
            tier=tier or None,
        )
        return _format_gate(outcome)

    @mcp.tool()
    @headless_compatible
    def project_quality_gate(
        manufacturer: str = "",
        tier: str = "",
    ) -> str:
        """Run the full project quality gate across schematic, PCB, DFM, and parity checks."""
        outcomes = _evaluate_project_gate(
            manufacturer=manufacturer or None,
            tier=tier or None,
        )
        return _render_project_gate_report(outcomes)

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
        """Return only unconnected net issues from DRC."""
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
        """Return only courtyard issues from DRC."""
        _, report, error = _run_drc_report("courtyard.json")
        if report is None:
            return f"Unable to compute courtyard issues: {error or 'unknown error'}"

        entries = _entries(report, "items_not_passing_courtyard")
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
