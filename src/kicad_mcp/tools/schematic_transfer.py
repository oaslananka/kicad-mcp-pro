"""Shared schematic-to-PCB transfer helpers."""

from __future__ import annotations

import re
from typing import Any, cast

from ..config import get_config
from ..utils.sexpr import _extract_block
from . import export_support
from .board_file import STRING_PATTERN
from .schematic import parse_schematic_file

subprocess = export_support.subprocess


def _collect_net_nodes(block: str, net_map: dict[tuple[str, str], str]) -> None:
    name_match = re.search(rf"\(name\s+{STRING_PATTERN}\)", block)
    if name_match is not None:
        net_name = name_match.group(1)
        for node in re.finditer(
            rf"\(node\s+\(ref\s+{STRING_PATTERN}\)\s+\(pin\s+{STRING_PATTERN}\)",
            block,
        ):
            net_map[(node.group(1), node.group(2))] = net_name


def _parse_netlist_text(content: str) -> dict[tuple[str, str], str]:
    net_map: dict[tuple[str, str], str] = {}
    cursor = 0
    while cursor < len(content):
        if content[cursor : cursor + 4] == "(net" and (
            cursor + 4 == len(content) or content[cursor + 4].isspace()
        ):
            block, length = _extract_block(content, cursor)
            if block:
                _collect_net_nodes(block, net_map)
                cursor += length
                continue
        cursor += 1
    return net_map


def _export_schematic_net_map() -> tuple[dict[tuple[str, str], str], str]:
    cfg = get_config()
    if cfg.sch_file is None or not cfg.sch_file.exists():
        return {}, "No schematic file is configured, so pad net names were skipped."
    if not cfg.kicad_cli.exists():
        return {}, "kicad-cli is unavailable, so pad net names were skipped."

    out_file = cfg.ensure_output_dir() / "pcb_sync.net"
    variants = [
        ["sch", "export", "netlist", "--output", str(out_file), str(cfg.sch_file)],
        ["sch", "export", "netlist", "--input", str(cfg.sch_file), "--output", str(out_file)],
    ]
    code, _stdout, stderr = export_support._run_cli_variants(variants)
    if code == 0 and out_file.exists():
        content = out_file.read_text(encoding="utf-8", errors="ignore")
        return _parse_netlist_text(content), ""
    last_stderr = stderr.strip() or "unknown error"
    return {}, f"Netlist export failed, so pad net names were skipped: {last_stderr}"


def _collect_schematic_components() -> tuple[list[dict[str, Any]], list[str]]:
    cfg = get_config()
    if cfg.sch_file is None or not cfg.sch_file.exists():
        raise ValueError(
            "No schematic file is configured. Call kicad_set_project() or set KICAD_MCP_SCH_FILE."
        )

    data = parse_schematic_file(cfg.sch_file)
    grouped: dict[str, dict[str, Any]] = {}
    issues: list[str] = []
    for symbol in data["symbols"]:
        reference = str(symbol["reference"])
        component = grouped.setdefault(
            reference,
            {
                "reference": reference,
                "value": str(symbol["value"]),
                "footprints": set(),
                "positions": [],
                "rotations": [],
            },
        )
        footprint = str(symbol["footprint"]).strip()
        if footprint:
            component["footprints"].add(footprint)
        component["positions"].append((float(symbol["x"]), float(symbol["y"])))
        component["rotations"].append(int(symbol["rotation"]))

    components: list[dict[str, Any]] = []
    for reference, component in grouped.items():
        footprints = cast(set[str], component["footprints"])
        if len(footprints) > 1:
            footprint_list = ", ".join(sorted(footprints))
            issues.append(f"{reference} has conflicting footprint assignments: {footprint_list}")
            continue
        positions = cast(list[tuple[float, float]], component["positions"])
        rotations = cast(list[int], component["rotations"])
        components.append(
            {
                "reference": reference,
                "value": str(component["value"]),
                "footprint": next(iter(footprints), ""),
                "x": sum(position[0] for position in positions) / len(positions),
                "y": sum(position[1] for position in positions) / len(positions),
                "rotation": rotations[0] if rotations else 0,
            }
        )
    return components, issues
