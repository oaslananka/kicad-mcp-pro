"""Shared parsers for KiCad PCB board files."""

from __future__ import annotations

import math
import re
import time
from collections.abc import Iterable
from typing import Any

from ..file_formats import GENERATED_SEXPR_DIALECT_VERSION
from ..utils import telemetry as otel
from ..utils.sexpr import _extract_block

BOARD_FILE_VERSION = GENERATED_SEXPR_DIALECT_VERSION
FLOAT_PATTERN = r"-?\d+(?:\.\d+)?"
STRING_PATTERN = r'"((?:\\.|[^"\\])*)"'


def _consume_quoted_board_character(char: str, escaped: bool) -> tuple[bool, bool]:
    """Advance the quoted string state; escaped quotes never end a string."""
    if escaped:
        return True, False
    if char == "\\":
        return True, True
    return char != '"', False


def _validate_board_text(content: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for char in content:
        if in_string:
            in_string, escaped = _consume_quoted_board_character(char, escaped)
            continue
        if char == '"':
            in_string = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                break
    if depth != 0 or in_string:
        raise ValueError("Refusing to write an invalid PCB file with unbalanced parentheses.")


def _default_board_text() -> str:
    return (
        "(kicad_pcb\n"
        f"\t(version {BOARD_FILE_VERSION})\n"
        '\t(generator "kicad-mcp-pro")\n'
        "\t(general)\n"
        '\t(paper "A4")\n'
        ")\n"
    )


def _normalize_board_content(content: str) -> str:
    stripped = content.strip()
    if not stripped or stripped == "(kicad_pcb)":
        return _default_board_text()
    if "(version" not in content:
        return _default_board_text()
    return content


def _parse_root_at(block: str) -> tuple[float, float, int] | None:
    for line in block.splitlines()[:12]:
        match = re.match(
            rf"\s*\(at\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})(?:\s+({FLOAT_PATTERN}))?\)",
            line,
        )
        if match:
            rotation = int(round(float(match.group(3) or "0")))
            return float(match.group(1)), float(match.group(2)), rotation
    return None


def _iter_blocks(content: str, keyword: str) -> Iterable[str]:
    cursor = 0
    marker = f"({keyword}"
    while cursor < len(content):
        if content.startswith(marker, cursor):
            block, length = _extract_block(content, cursor)
            if block:
                yield block
                cursor += length
                continue
        cursor += 1


def _bbox_from_block(block: str) -> tuple[float, float]:
    xs: list[float] = []
    ys: list[float] = []

    for rect in re.finditer(
        rf"\(fp_rect\s+\(start\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})\)\s+\(end\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})\)",
        block,
    ):
        xs.extend([float(rect.group(1)), float(rect.group(3))])
        ys.extend([float(rect.group(2)), float(rect.group(4))])

    for line in re.finditer(
        rf"\(fp_line\s+\(start\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})\)\s+\(end\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})\)",
        block,
    ):
        xs.extend([float(line.group(1)), float(line.group(3))])
        ys.extend([float(line.group(2)), float(line.group(4))])

    for circle in re.finditer(
        rf"\(fp_circle\s+\(center\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})\)\s+\(end\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})\)",
        block,
    ):
        center_x = float(circle.group(1))
        center_y = float(circle.group(2))
        end_x = float(circle.group(3))
        end_y = float(circle.group(4))
        radius = math.hypot(end_x - center_x, end_y - center_y)
        xs.extend([center_x - radius, center_x + radius])
        ys.extend([center_y - radius, center_y + radius])

    for pad_block in _iter_blocks(block, "pad"):
        at_match = re.search(
            rf"\(at\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})(?:\s+{FLOAT_PATTERN})?\)",
            pad_block,
        )
        size_match = re.search(rf"\(size\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})\)", pad_block)
        if at_match and size_match:
            center_x = float(at_match.group(1))
            center_y = float(at_match.group(2))
            width = float(size_match.group(1))
            height = float(size_match.group(2))
            xs.extend([center_x - (width / 2), center_x + (width / 2)])
            ys.extend([center_y - (height / 2), center_y + (height / 2)])

    if not xs or not ys:
        return 5.08, 5.08

    width = max(max(xs) - min(xs), 1.0)
    height = max(max(ys) - min(ys), 1.0)
    return round(width, 4), round(height, 4)


def _footprint_net_names(block: str) -> list[str]:
    names: set[str] = set()
    for pad_block in _iter_blocks(block, "pad"):
        match = re.search(rf"\(net(?:\s+\d+)?\s+{STRING_PATTERN}\)", pad_block)
        if match is not None and match.group(1):
            names.add(match.group(1))
    return sorted(names)


def _footprint_pad_positions_mm(
    block: str,
    origin: tuple[float, float, int] | None,
    footprint_layer: str | None,
) -> list[dict[str, Any]]:
    """Return measured front-layer pad centers and names in board coordinates.

    Restrict the calculation to known F.Cu geometry: the backside's mirror
    convention must not be mistaken for a qualified absolute position.
    """
    if origin is None or footprint_layer != "F.Cu":
        return []
    x0, y0, rotation = origin
    radians = math.radians(rotation)
    cosine, sine = math.cos(radians), math.sin(radians)
    pads: list[dict[str, Any]] = []
    for pad in _iter_blocks(block, "pad"):
        name_match = re.match(rf"\(pad\s+{STRING_PATTERN}", pad.lstrip())
        location = re.search(
            rf"\(at\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})(?:\s+{FLOAT_PATTERN})?\)",
            pad,
        )
        net_match = re.search(rf"\(net(?:\s+\d+)?\s+{STRING_PATTERN}\)", pad)
        if name_match is None or location is None or net_match is None:
            continue
        lx, ly = float(location.group(1)), float(location.group(2))
        pads.append(
            {
                "number": name_match.group(1),
                "net": net_match.group(1),
                "x_mm": x0 + lx * cosine + ly * sine,
                "y_mm": y0 - lx * sine + ly * cosine,
            }
        )
    return pads


def _footprint_pad_net_map(block: str) -> dict[str, str]:
    pad_map: dict[str, str] = {}
    for pad_block in _iter_blocks(block, "pad"):
        pad_match = re.match(rf"\(pad\s+{STRING_PATTERN}", pad_block.lstrip())
        net_match = re.search(rf"\(net(?:\s+\d+)?\s+{STRING_PATTERN}\)", pad_block)
        if pad_match is None or net_match is None:
            continue
        if not pad_match.group(1) or not net_match.group(1):
            continue
        pad_map[pad_match.group(1)] = net_match.group(1)
    return pad_map


def _courtyard_shape_points(
    primitive: str,
    item: str,
    shape_pattern: re.Pattern[str],
) -> list[tuple[float, float]] | None:
    """Return only *conservatively* supported local courtyard geometry."""
    if primitive in {"fp_arc", "fp_poly"}:
        return None
    coords = [(float(x), float(y)) for x, y in shape_pattern.findall(item)]
    if primitive == "fp_circle":
        center = re.search(rf"\(center\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})\)", item)
        if center is None or len(coords) != 1:
            return None
        cx, cy = float(center.group(1)), float(center.group(2))
        radius = math.hypot(coords[0][0] - cx, coords[0][1] - cy)
        return [
            (cx - radius, cy - radius),
            (cx - radius, cy + radius),
            (cx + radius, cy - radius),
            (cx + radius, cy + radius),
        ]
    if len(coords) != 2:
        return None
    if primitive == "fp_rect":
        (x0, y0), (x1, y1) = coords
        return [(x0, y0), (x0, y1), (x1, y0), (x1, y1)]
    return coords


def _local_courtyard_points(block: str) -> list[tuple[float, float]] | None:
    """Abort to legacy fallback if a courtyard primitive cannot be bounded."""
    shape_pattern = re.compile(rf"\((?:start|end)\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})\)")
    points: list[tuple[float, float]] = []
    for primitive in ("fp_line", "fp_rect", "fp_circle", "fp_arc", "fp_poly"):
        for item in _iter_blocks(block, primitive):
            if not re.search(r'\(layer\s+"[FB]\.CrtYd"\)', item):
                continue
            item_points = _courtyard_shape_points(primitive, item, shape_pattern)
            if item_points is None:
                return None
            points.extend(item_points)
    return points or None


def _absolute_courtyard_bounds_mm(
    block: str,
    root_at: tuple[float, float, int] | None,
) -> tuple[float, float, float, float] | None:
    """Conservatively locate footprint courtyard in board coordinates.

    The pad-origin may not be the courtyard center. Preserve offset, rotation,
    unsupported-primitive fallback and KiCad's board-axis convention.
    """
    if root_at is None:
        return None
    local_points = _local_courtyard_points(block)
    if local_points is None:
        return None
    px, py, degrees = root_at
    theta = math.radians(degrees)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    rotated = [(px + x * cos_t + y * sin_t, py - x * sin_t + y * cos_t) for x, y in local_points]
    return (
        round(min(p[0] for p in rotated), 5),
        round(min(p[1] for p in rotated), 5),
        round(max(p[0] for p in rotated), 5),
        round(max(p[1] for p in rotated), 5),
    )


def _explicit_footprint_layer(block: str, after_name: int) -> str | None:
    """Read only the footprint's direct (layer ...) child, not nested graphics.

    Other consumers retain their historical F.Cu fallback, but engineering
    approval must know whether the actual root layer was declared.
    """
    cursor = after_name
    while (child_start := block.find("(", cursor)) >= 0:
        child, length = _extract_block(block, child_start)
        if not length:
            return None
        layer = re.fullmatch(r'\(layer\s+"([^"]+)"\)', child.strip())
        if layer is not None:
            return layer.group(1)
        cursor = child_start + length
    return None


def _build_footprint_entry(
    block: str,
    cursor: int,
    length: int,
) -> tuple[str, dict[str, Any]] | None:
    ref_match = re.search(rf'\(property\s+"Reference"\s+{STRING_PATTERN}', block)
    value_match = re.search(rf'\(property\s+"Value"\s+{STRING_PATTERN}', block)
    name_match = re.match(rf"\(footprint\s+{STRING_PATTERN}", block.lstrip())
    if not (ref_match and name_match):
        return None
    root_at = _parse_root_at(block)
    width_mm, height_mm = _bbox_from_block(block)
    explicit_layer = _explicit_footprint_layer(block, name_match.end())
    entry = {
        "name": name_match.group(1),
        "block": block,
        "start": cursor,
        "end": cursor + length,
        "value": value_match.group(1) if value_match else "",
        "x_mm": root_at[0] if root_at else None,
        "y_mm": root_at[1] if root_at else None,
        "rotation": root_at[2] if root_at else 0,
        "width_mm": width_mm,
        "height_mm": height_mm,
        "courtyard_bounds_mm": _absolute_courtyard_bounds_mm(block, root_at),
        "layer_name": explicit_layer if explicit_layer is not None else "F.Cu",
        "layer_name_explicit": explicit_layer is not None,
        "net_names": _footprint_net_names(block),
        "pad_nets": _footprint_pad_net_map(block),
        "pad_positions_mm": _footprint_pad_positions_mm(block, root_at, explicit_layer),
    }
    return ref_match.group(1), entry


def _parse_board_footprint_blocks(content: str) -> dict[str, dict[str, Any]]:
    started = time.perf_counter()
    footprints: dict[str, dict[str, Any]] = {}
    with otel.pcb_parse_span() as span:
        cursor = 0
        while cursor < len(content):
            if content.startswith("(footprint", cursor):
                block, length = _extract_block(content, cursor)
                if block:
                    parsed = _build_footprint_entry(block, cursor, length)
                    if parsed:
                        ref, entry = parsed
                        footprints[ref] = entry
                    cursor += length
                    continue
            cursor += 1
        otel.finish_pcb_parse_span(
            span,
            footprint_count=len(footprints),
            elapsed_seconds=time.perf_counter() - started,
        )
        return footprints


def _edge_cuts_bounds(content: str) -> tuple[float, float, float, float] | None:
    xs: list[float] = []
    ys: list[float] = []
    patterns = [
        rf"\(gr_line\s+\(start\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})\)\s+\(end\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})\).*?\(layer\s+\"Edge\.Cuts\"\)",
        rf"\(gr_rect\s+\(start\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})\)\s+\(end\s+({FLOAT_PATTERN})\s+({FLOAT_PATTERN})\).*?\(layer\s+\"Edge\.Cuts\"\)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, content, flags=re.DOTALL):
            xs.extend([float(match.group(1)), float(match.group(3))])
            ys.extend([float(match.group(2)), float(match.group(4))])
    if not xs or not ys:
        return None
    return min(xs), min(ys), max(xs), max(ys)


def _board_frame_mm(
    content: str,
    footprints: dict[str, dict[str, Any]],
) -> tuple[float, float, float, float]:
    if (outline := _edge_cuts_bounds(content)) is not None:
        return outline

    xs: list[float] = []
    ys: list[float] = []
    for entry in footprints.values():
        if entry["x_mm"] is None or entry["y_mm"] is None:
            continue
        x_mm = float(entry["x_mm"])
        y_mm = float(entry["y_mm"])
        width_mm = float(entry["width_mm"])
        height_mm = float(entry["height_mm"])
        xs.extend([x_mm - (width_mm / 2), x_mm + (width_mm / 2)])
        ys.extend([y_mm - (height_mm / 2), y_mm + (height_mm / 2)])
    if xs and ys:
        return min(xs) - 10.0, min(ys) - 10.0, max(xs) + 10.0, max(ys) + 10.0
    return 0.0, 0.0, 100.0, 80.0


def _placement_boxes_overlap(
    x1_mm: float,
    y1_mm: float,
    width1_mm: float,
    height1_mm: float,
    x2_mm: float,
    y2_mm: float,
    width2_mm: float,
    height2_mm: float,
    margin_mm: float,
) -> bool:
    return (
        abs(x1_mm - x2_mm) < ((width1_mm + width2_mm) / 2) + margin_mm
        and abs(y1_mm - y2_mm) < ((height1_mm + height2_mm) / 2) + margin_mm
    )
