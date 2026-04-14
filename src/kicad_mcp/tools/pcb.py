"""PCB read/write tools backed by KiCad IPC."""

from __future__ import annotations

import json
import math
import re
import subprocess
import uuid
from collections.abc import Callable, Iterable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Protocol, cast

import structlog
from kipy.board_types import (
    BoardCircle,
    BoardItem,
    BoardRectangle,
    BoardSegment,
    BoardText,
    Net,
    Track,
    Via,
    Zone,
)
from kipy.geometry import Angle, PolygonWithHoles, PolyLine, PolyLineNode, Vector2
from kipy.proto.board.board_types_pb2 import BoardLayer, ViaType, ZoneType
from kipy.proto.common import types as common_types
from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..connection import KiCadConnectionError, board_transaction, get_board
from ..models.common import _FootprintLike, _PadLike
from ..models.pcb import (
    AddCircleInput,
    AddFiducialMarksInput,
    AddMountingHolesInput,
    AddRectangleInput,
    AddSegmentInput,
    AddTeardropsInput,
    AddTextInput,
    AddTrackInput,
    AddViaInput,
    AlignFootprintsInput,
    AutoPlaceBySchematicInput,
    BulkTrackItem,
    CreepageCheckInput,
    GroupFootprintsInput,
    ImpedanceForTraceInput,
    KeepoutZoneInput,
    LayerViaInput,
    PlaceDecouplingCapsInput,
    SetBoardOutlineInput,
    SetStackupInput,
    StackupLayerSpec,
    SyncPcbFromSchematicInput,
)
from ..utils.impedance import TraceType, copper_thickness_mm, trace_impedance
from ..utils.layers import CANONICAL_LAYER_NAMES, resolve_layer, resolve_layer_name
from ..utils.sexpr import _extract_block, _sexpr_string
from ..utils.units import _coord_nm, mm_to_nm, nm_to_mm
from .metadata import headless_compatible, requires_kicad_running
from .schematic import parse_schematic_file

logger = structlog.get_logger(__name__)
BOARD_FILE_VERSION = "20250216"
STRING_PATTERN = r'"((?:\\.|[^"\\])*)"'
FLOAT_PATTERN = r"-?\d+(?:\.\d+)?"
PLACEMENT_MARGIN_MM = 1.27
STACKUP_STATE_FILE = "stackup_profile.json"
_COPPER_LAYER_SEQUENCE = [
    "F_Cu",
    "In1_Cu",
    "In2_Cu",
    "In3_Cu",
    "In4_Cu",
    "In5_Cu",
    "In6_Cu",
    "In7_Cu",
    "In8_Cu",
    "B_Cu",
]


class _ComponentPlacement(Protocol):
    reference: str
    value: str
    footprint: str
    x: float
    y: float
    rotation: int


def _limit[T](items: Iterable[T]) -> tuple[list[T], int]:
    cfg = get_config()
    collected = list(items)
    return collected[: cfg.max_items_per_response], len(collected)


def _page_size(requested: int) -> int:
    if requested < 1:
        raise ValueError("page_size must be at least 1.")
    return min(requested, get_config().max_items_per_response)


def _paginate[T](items: Iterable[T], *, page: int, page_size: int) -> tuple[list[T], int, int]:
    if page < 1:
        raise ValueError("page must be at least 1.")
    normalized_page_size = _page_size(page_size)
    collected = list(items)
    total = len(collected)
    if total == 0:
        return [], 0, 0
    page_count = max(math.ceil(total / normalized_page_size), 1)
    if page > page_count:
        return [], total, page_count
    start = (page - 1) * normalized_page_size
    stop = start + normalized_page_size
    return collected[start:stop], total, page_count


def _matches_layer_filter(layer: int, filter_layer: str) -> bool:
    if not filter_layer:
        return True
    board_layer_name = BoardLayer.Name(layer)
    if board_layer_name.startswith("BL_"):
        board_layer_name = board_layer_name[3:]
    return resolve_layer_name(filter_layer) == resolve_layer_name(board_layer_name)


def _find_net(name: str) -> Net:
    net = Net()
    net.name = name
    return net


def _board_file_layer_name(layer_name: str) -> str:
    canonical = resolve_layer_name(layer_name)
    return canonical.replace("_", ".")


def _is_copper_stackup_layer(layer: StackupLayerSpec) -> bool:
    normalized_name = layer.name.replace(".", "_")
    material = layer.material.casefold()
    return (
        normalized_name in CANONICAL_LAYER_NAMES and normalized_name.endswith("_Cu")
    ) or (
        material == "copper"
    )


def _indent_block(block: str, level: int) -> str:
    prefix = "\t" * level
    return "\n".join(f"{prefix}{line}" for line in block.strip().splitlines())


def _replace_or_append_root_block(content: str, keyword: str, block: str) -> str:
    normalized = _normalize_board_content(content)
    replacement = _indent_block(block, 1)
    match = re.search(rf"(?m)^\s*\({re.escape(keyword)}\b", normalized)
    if match is None:
        return _append_board_blocks(normalized, [block])
    existing, length = _extract_block(normalized, match.start())
    if not existing:
        return _append_board_blocks(normalized, [block])
    return normalized[: match.start()] + replacement + normalized[match.start() + length :]


def _replace_or_append_child_block(parent_block: str, keyword: str, child_block: str) -> str:
    replacement = _indent_block(child_block, 2)
    match = re.search(rf"(?m)^\s*\({re.escape(keyword)}\b", parent_block)
    if match is not None:
        existing, length = _extract_block(parent_block, match.start())
        if existing:
            return (
                parent_block[: match.start()]
                + replacement
                + parent_block[match.start() + length :]
            )

    insert_at = parent_block.rfind(")")
    if insert_at == -1:
        raise ValueError("Unable to update the board setup block.")
    before = parent_block[:insert_at].rstrip()
    after = parent_block[insert_at:]
    return f"{before}\n{replacement}\n\t{after.lstrip()}"


def _stackup_state_path() -> Path:
    return get_config().ensure_output_dir() / STACKUP_STATE_FILE


def _write_stackup_state(layers: list[StackupLayerSpec]) -> Path:
    path = _stackup_state_path()
    path.write_text(
        json.dumps([layer.model_dump() for layer in layers], indent=2),
        encoding="utf-8",
    )
    return path


def _load_stackup_state() -> list[StackupLayerSpec] | None:
    path = _stackup_state_path()
    if not path.exists():
        return None
    payload = cast(list[dict[str, Any]], json.loads(path.read_text(encoding="utf-8")))
    return [StackupLayerSpec.model_validate(item) for item in payload]


def _stackup_specs_from_board() -> list[StackupLayerSpec] | None:
    if not _board_is_open():
        return None

    stackup = get_board().get_stackup()
    specs: list[StackupLayerSpec] = []
    for index, layer in enumerate(getattr(stackup, "layers", [])):
        raw_layer = getattr(layer, "layer", "")
        if isinstance(raw_layer, int):
            name = BoardLayer.Name(raw_layer).removeprefix("BL_")
        else:
            name = str(raw_layer or f"dielectric_{index}")
        normalized_name = name.replace(".", "_")
        thickness_nm = int(getattr(layer, "thickness", 0))
        material = str(getattr(layer, "material_name", "") or "")
        if not material:
            material = "Copper" if normalized_name.endswith("_Cu") else "FR4"
        layer_type = str(getattr(layer, "type_name", "") or getattr(layer, "type", "") or "")
        if not layer_type:
            layer_type = "signal" if normalized_name.endswith("_Cu") else "dielectric"
        spec_kwargs: dict[str, Any] = {
            "name": normalized_name if normalized_name in CANONICAL_LAYER_NAMES else name,
            "type": layer_type,
            "thickness_mm": nm_to_mm(thickness_nm) if thickness_nm else 0.18,
            "material": material,
        }
        epsilon_r = getattr(layer, "epsilon_r", None)
        if isinstance(epsilon_r, int | float) and epsilon_r != 0:
            spec_kwargs["epsilon_r"] = float(epsilon_r)
        loss_tangent = getattr(layer, "loss_tangent", None)
        if isinstance(loss_tangent, int | float) and loss_tangent != 0:
            spec_kwargs["loss_tangent"] = float(loss_tangent)
        specs.append(StackupLayerSpec.model_validate(spec_kwargs))
    return specs or None


def _parse_stackup_specs_from_board_text(content: str) -> list[StackupLayerSpec] | None:
    match = re.search(r"(?m)^\s*\(setup\b", content)
    if match is None:
        return None
    setup_block, _ = _extract_block(content, match.start())
    stackup_match = re.search(r"(?m)^\s*\(stackup\b", setup_block)
    if stackup_match is None:
        return None
    stackup_block, _ = _extract_block(setup_block, stackup_match.start())
    if not stackup_block:
        return None

    specs: list[StackupLayerSpec] = []
    cursor = 0
    while cursor < len(stackup_block):
        layer_match = re.search(r"(?m)^\s*\(layer\b", stackup_block[cursor:])
        if layer_match is None:
            break
        start = cursor + layer_match.start()
        layer_block, length = _extract_block(stackup_block, start)
        if not layer_block:
            break
        cursor = start + length
        stripped = layer_block.lstrip()
        quoted = re.match(r'\(layer\s+"([^"]+)"\s+(\d+)', stripped)
        dielectric = re.match(r"\(layer\s+dielectric\s+(\d+)", stripped)
        if quoted is not None:
            layer_name = resolve_layer_name(quoted.group(1))
        elif dielectric is not None:
            layer_name = f"dielectric_{dielectric.group(1)}"
        else:
            continue

        type_match = re.search(r'\(type\s+"([^"]+)"\)', layer_block)
        thickness_match = re.search(rf"\(thickness\s+({FLOAT_PATTERN})\)", layer_block)
        if thickness_match is None:
            continue
        material_match = re.search(r'\(material\s+"([^"]+)"\)', layer_block)
        epsilon_match = re.search(rf"\(epsilon_r\s+({FLOAT_PATTERN})\)", layer_block)
        loss_match = re.search(rf"\(loss_tangent\s+({FLOAT_PATTERN})\)", layer_block)
        epsilon_text = epsilon_match.group(1) if epsilon_match is not None else None
        loss_text = loss_match.group(1) if loss_match is not None else None

        specs.append(
            StackupLayerSpec.model_validate(
                {
                    "name": layer_name,
                    "type": type_match.group(1) if type_match else "signal",
                    "thickness_mm": float(thickness_match.group(1)),
                    "material": material_match.group(1) if material_match else "FR4",
                    "epsilon_r": float(epsilon_text) if epsilon_text is not None else None,
                    "loss_tangent": float(loss_text) if loss_text is not None else None,
                }
            )
        )
    return specs or None


def _current_stackup_specs() -> list[StackupLayerSpec]:
    if (board_specs := _stackup_specs_from_board()) is not None:
        return board_specs
    if (state_specs := _load_stackup_state()) is not None:
        return state_specs
    board_text = _get_pcb_file_for_sync().read_text(encoding="utf-8", errors="ignore")
    if (parsed_specs := _parse_stackup_specs_from_board_text(board_text)) is not None:
        return parsed_specs
    raise ValueError(
        "No stackup data is available. Configure one with pcb_set_stackup() "
        "or open the board in KiCad."
    )


def _total_stackup_thickness_mm(layers: list[StackupLayerSpec]) -> float:
    return round(sum(layer.thickness_mm for layer in layers), 4)


def _render_general_block(total_thickness_mm: float) -> str:
    return (
        "(general\n"
        f"\t(thickness {total_thickness_mm:.4f})\n"
        ")"
    )


def _render_stackup_layer_block(layer: StackupLayerSpec, order: int) -> str:
    if _is_copper_stackup_layer(layer):
        header = f'(layer "{_board_file_layer_name(layer.name)}" {order}'
    else:
        header = f"(layer dielectric {order}"
    lines = [
        header,
        f'\t(type "{layer.type}")',
        f"\t(thickness {layer.thickness_mm:.4f})",
        f'\t(material "{layer.material}")',
    ]
    if layer.epsilon_r is not None:
        lines.append(f"\t(epsilon_r {layer.epsilon_r:.4f})")
    if layer.loss_tangent is not None:
        lines.append(f"\t(loss_tangent {layer.loss_tangent:.4f})")
    lines.append(")")
    return "\n".join(lines)


def _render_stackup_block(layers: list[StackupLayerSpec]) -> str:
    blocks = [_render_stackup_layer_block(layer, order) for order, layer in enumerate(layers)]
    rendered_layers = "\n".join(_indent_block(block, 1) for block in blocks)
    return (
        "(stackup\n"
        f"{rendered_layers}\n"
        '\t(copper_finish "None")\n'
        "\t(dielectric_constraints no)\n"
        ")"
    )


def _copper_layer_order(layer_name: str) -> int:
    canonical = resolve_layer_name(layer_name)
    if canonical not in _COPPER_LAYER_SEQUENCE:
        raise ValueError(f"Layer '{layer_name}' is not a copper routing layer.")
    return _COPPER_LAYER_SEQUENCE.index(canonical)


def _configure_layer_via(via: Via, *, from_layer: str, to_layer: str) -> None:
    start_layer = resolve_layer(from_layer)
    end_layer = resolve_layer(to_layer)
    via.padstack.proto.ClearField("layers")
    layer_container = cast(Any, via.padstack.layers)
    layer_container.extend([start_layer, end_layer])
    via.padstack.drill.start_layer = start_layer
    via.padstack.drill.end_layer = end_layer


def _impedance_context_for_layer(
    specs: list[StackupLayerSpec],
    layer_name: str,
) -> tuple[TraceType, float, float, float]:
    canonical = resolve_layer_name(layer_name)
    target_index = next(
        (index for index, layer in enumerate(specs) if layer.name.replace(".", "_") == canonical),
        None,
    )
    if target_index is None:
        available = ", ".join(layer.name for layer in specs)
        raise ValueError(f"Layer '{layer_name}' was not found in the current stackup: {available}")

    copper_indices = [
        index for index, layer in enumerate(specs) if _is_copper_stackup_layer(layer)
    ]
    target = specs[target_index]
    previous_dielectric = next(
        (
            specs[index]
            for index in range(target_index - 1, -1, -1)
            if not _is_copper_stackup_layer(specs[index])
        ),
        None,
    )
    next_dielectric = next(
        (
            specs[index]
            for index in range(target_index + 1, len(specs))
            if not _is_copper_stackup_layer(specs[index])
        ),
        None,
    )
    adjacent_dielectrics = [
        layer for layer in (previous_dielectric, next_dielectric) if layer is not None
    ]
    if not adjacent_dielectrics:
        raise ValueError(
            "The current stackup does not define dielectric spacing around that layer."
        )

    is_outer = target_index in {copper_indices[0], copper_indices[-1]}
    if is_outer:
        dielectric = previous_dielectric or next_dielectric
        if dielectric is None:
            raise ValueError(
                "The current stackup does not define dielectric spacing around that layer."
            )
        trace_type: TraceType = "microstrip"
        height_mm = dielectric.thickness_mm
        er = dielectric.epsilon_r or 4.2
    else:
        trace_type = "stripline"
        height_mm = (
            sum(layer.thickness_mm for layer in adjacent_dielectrics)
            / len(adjacent_dielectrics)
        )
        er_values = [layer.epsilon_r or 4.2 for layer in adjacent_dielectrics]
        er = sum(er_values) / len(er_values)

    copper_oz = target.thickness_mm / copper_thickness_mm(1.0)
    return trace_type, height_mm, er, max(copper_oz, 0.1)


def _required_creepage_mm(
    voltage_v: float,
    pollution_degree: int,
    material_group: int,
) -> float:
    base_table: dict[int, list[tuple[float, float]]] = {
        1: [(50.0, 0.2), (100.0, 0.4), (150.0, 0.6), (300.0, 1.2), (600.0, 2.4)],
        2: [(50.0, 0.6), (100.0, 1.0), (150.0, 1.5), (300.0, 2.5), (600.0, 5.0)],
        3: [(50.0, 1.0), (100.0, 1.5), (150.0, 2.5), (300.0, 4.0), (600.0, 8.0)],
        4: [(50.0, 1.6), (100.0, 2.5), (150.0, 4.0), (300.0, 6.3), (600.0, 12.5)],
    }
    group_multiplier = {1: 0.8, 2: 0.9, 3: 1.0, 4: 1.1}
    table = base_table[pollution_degree]
    required_mm = table[-1][1]
    for threshold_v, creepage_mm in table:
        if voltage_v <= threshold_v:
            required_mm = creepage_mm
            break
    if voltage_v > table[-1][0]:
        required_mm += ((voltage_v - table[-1][0]) / 100.0) * 1.5
    return round(required_mm * group_multiplier[material_group], 3)


def _apply_stackup_to_board(content: str, layers: list[StackupLayerSpec]) -> str:
    updated = _replace_or_append_root_block(
        content,
        "general",
        _render_general_block(_total_stackup_thickness_mm(layers)),
    )
    stackup_block = _render_stackup_block(layers)
    match = re.search(r"(?m)^\s*\(setup\b", updated)
    if match is None:
        setup_block = "(setup\n" + _indent_block(stackup_block, 1) + "\n)"
        return _replace_or_append_root_block(updated, "setup", setup_block)

    existing_setup, _ = _extract_block(updated, match.start())
    refreshed_setup = _replace_or_append_child_block(existing_setup, "stackup", stackup_block)
    return _replace_or_append_root_block(updated, "setup", refreshed_setup)


def _find_footprint_by_reference(reference: str) -> _FootprintLike | None:
    board = get_board()
    for footprint in cast(Iterable[_FootprintLike], board.get_footprints()):
        if footprint.reference_field.text.value == reference:
            return footprint
    return None


def _format_selection_id(item: object) -> str:
    item_id = getattr(getattr(item, "id", None), "value", "")
    return str(item_id)[:8] + ("..." if item_id else "")


def _validate_board_text(content: str) -> None:
    depth = 0
    in_string = False
    escaped = False
    for char in content:
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
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


def _get_pcb_file_for_sync() -> Path:
    cfg = get_config()
    if cfg.pcb_file is not None:
        path = cfg.pcb_file
    elif cfg.project_file is not None:
        path = cfg.project_file.with_suffix(".kicad_pcb")
        cfg.pcb_file = path
    else:
        raise ValueError(
            "No PCB file is configured. Call kicad_set_project() or set KICAD_MCP_PCB_FILE."
        )
    if not path.exists():
        path.write_text(_default_board_text(), encoding="utf-8")
    return path


def _normalize_board_content(content: str) -> str:
    stripped = content.strip()
    if not stripped or stripped == "(kicad_pcb)":
        return _default_board_text()
    if "(version" not in content:
        return _default_board_text()
    return content


def _transactional_board_write(mutator: Callable[[str], str]) -> str:
    board_file = _get_pcb_file_for_sync()
    current = _normalize_board_content(board_file.read_text(encoding="utf-8", errors="ignore"))
    updated = mutator(current)
    _validate_board_text(updated)
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=board_file.parent) as handle:
        handle.write(updated)
        temp_path = Path(handle.name)
    temp_path.replace(board_file)
    return str(board_file)


def _board_is_open() -> bool:
    try:
        get_board()
    except (KiCadConnectionError, OSError) as exc:
        logger.debug("board_not_open", error=str(exc))
        return False
    return True


def _reload_board_after_file_sync() -> str:
    try:
        board = get_board()
    except (KiCadConnectionError, OSError) as exc:
        logger.debug("board_reload_skipped", error=str(exc))
        return "The PCB file was updated. Reload it manually in KiCad if needed."

    try:
        revert = cast(Callable[[], None], board.revert)
        revert()
        return "The PCB file was updated and KiCad was asked to reload it."
    except Exception as exc:
        logger.debug("board_reload_after_sync_failed", error=str(exc))
        return "The PCB file was updated. Reload it manually in KiCad if needed."


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
        if content[cursor:].startswith(marker):
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


def _footprint_size_from_assignment(assignment: str) -> tuple[float, float]:
    library, footprint = _split_footprint_assignment(assignment)
    path = _footprint_file(library, footprint)
    if not path.exists():
        raise FileNotFoundError(f"Footprint '{assignment}' was not found.")
    return _bbox_from_block(path.read_text(encoding="utf-8", errors="ignore"))


def _footprint_pad_numbers_from_assignment(assignment: str) -> list[str]:
    library, footprint = _split_footprint_assignment(assignment)
    path = _footprint_file(library, footprint)
    if not path.exists():
        raise FileNotFoundError(f"Footprint '{assignment}' was not found.")
    block = path.read_text(encoding="utf-8", errors="ignore")
    pad_numbers: list[str] = []
    for pad_block in _iter_blocks(block, "pad"):
        match = re.match(rf"\(pad\s+{STRING_PATTERN}", pad_block.lstrip())
        if match is None or not match.group(1):
            continue
        pad_numbers.append(match.group(1))
    return pad_numbers


def _schematic_pad_net_summary(
    components: list[dict[str, Any]],
    net_map: dict[tuple[str, str], str],
) -> dict[str, Any]:
    total_pads = 0
    named_pads = 0
    unresolved_refs: list[str] = []
    fully_named_refs = 0
    partial_refs = 0
    for component in components:
        reference = str(component["reference"])
        pad_numbers = _footprint_pad_numbers_from_assignment(str(component["footprint"]))
        if not pad_numbers:
            continue
        unresolved_count = 0
        for pad_number in pad_numbers:
            total_pads += 1
            if net_map.get((reference, pad_number)):
                named_pads += 1
            else:
                unresolved_count += 1
        if unresolved_count == 0:
            fully_named_refs += 1
        else:
            partial_refs += 1
        if unresolved_count:
            unresolved_refs.append(
                f"{reference} ({unresolved_count}/{len(pad_numbers)} pad(s) without net names)"
            )
    coverage_pct = round((named_pads / total_pads) * 100, 1) if total_pads else 100.0
    if total_pads == 0:
        quality = "UNKNOWN"
    elif named_pads == total_pads:
        quality = "CLEAN"
    elif coverage_pct >= 50.0:
        quality = "DEGRADED"
    else:
        quality = "POOR"
    return {
        "total_pads": total_pads,
        "named_pads": named_pads,
        "no_net_pads": total_pads - named_pads,
        "coverage_pct": coverage_pct,
        "quality": quality,
        "fully_named_refs": fully_named_refs,
        "partial_refs": partial_refs,
        "unresolved_refs": unresolved_refs,
    }


def _footprint_net_names(block: str) -> list[str]:
    names: set[str] = set()
    for pad_block in _iter_blocks(block, "pad"):
        match = re.search(rf"\(net(?:\s+\d+)?\s+{STRING_PATTERN}\)", pad_block)
        if match is not None and match.group(1):
            names.add(match.group(1))
    return sorted(names)


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


def _parse_board_footprint_blocks(content: str) -> dict[str, dict[str, Any]]:
    footprints: dict[str, dict[str, Any]] = {}
    cursor = 0
    while cursor < len(content):
        if content[cursor:].startswith("(footprint"):
            block, length = _extract_block(content, cursor)
            if block:
                ref_match = re.search(rf'\(property\s+"Reference"\s+{STRING_PATTERN}', block)
                name_match = re.match(rf"\(footprint\s+{STRING_PATTERN}", block.lstrip())
                if ref_match and name_match:
                    root_at = _parse_root_at(block)
                    width_mm, height_mm = _bbox_from_block(block)
                    layer_match = re.search(r'\(layer\s+"([^"]+)"\)', block)
                    footprints[ref_match.group(1)] = {
                        "name": name_match.group(1),
                        "block": block,
                        "start": cursor,
                        "end": cursor + length,
                        "x_mm": root_at[0] if root_at else None,
                        "y_mm": root_at[1] if root_at else None,
                        "rotation": root_at[2] if root_at else 0,
                        "width_mm": width_mm,
                        "height_mm": height_mm,
                        "layer_name": layer_match.group(1) if layer_match else "F.Cu",
                        "net_names": _footprint_net_names(block),
                        "pad_nets": _footprint_pad_net_map(block),
                    }
                cursor += length
                continue
        cursor += 1
    return footprints


def _replace_root_at(block: str, *, x_mm: float, y_mm: float, rotation: int) -> str:
    lines = block.splitlines()
    for index, line in enumerate(lines[:20]):
        match = re.match(
            rf"(\s*)\(at\s+{FLOAT_PATTERN}\s+{FLOAT_PATTERN}(?:\s+{FLOAT_PATTERN})?\)",
            line,
        )
        if match:
            indent = match.group(1)
            lines[index] = f"{indent}(at {x_mm:.4f} {y_mm:.4f} {rotation})"
            return "\n".join(lines)
    return _inject_root_placement(block, x_mm=x_mm, y_mm=y_mm, rotation=rotation)


def _collect_occupied_boxes(
    footprints: dict[str, dict[str, Any]],
    *,
    exclude_refs: set[str] | None = None,
) -> list[dict[str, float]]:
    excluded = exclude_refs or set()
    return [
        {
            "x_mm": float(entry["x_mm"]),
            "y_mm": float(entry["y_mm"]),
            "width_mm": float(entry["width_mm"]),
            "height_mm": float(entry["height_mm"]),
        }
        for reference, entry in footprints.items()
        if reference not in excluded and entry["x_mm"] is not None and entry["y_mm"] is not None
    ]


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


def _guard_file_based_board_edit(operation: str, allow_open_board: bool) -> str | None:
    if _board_is_open() and not allow_open_board:
        return (
            f"Refusing file-based {operation} while a board is open in KiCad. "
            "Close the board first, or rerun with allow_open_board=True if you want "
            "KiCad to reload the updated file from disk."
        )
    return None


def _finalize_file_based_board_edit(allow_open_board: bool) -> str:
    if allow_open_board and _board_is_open():
        return _reload_board_after_file_sync()
    return "The PCB file was updated. Reload it manually in KiCad if needed."


def _strategy_board_positions(
    components: list[dict[str, Any]],
    payload: AutoPlaceBySchematicInput,
    occupied_boxes: list[dict[str, float]],
) -> dict[str, tuple[float, float]]:
    sync_payload = SyncPcbFromSchematicInput(
        origin_x_mm=payload.origin_x_mm,
        origin_y_mm=payload.origin_y_mm,
        scale_x=payload.scale_x,
        scale_y=payload.scale_y,
        grid_mm=payload.grid_mm,
        allow_open_board=payload.allow_open_board,
    )
    if payload.strategy == "cluster":
        return _planned_board_positions(components, sync_payload, occupied_boxes)

    positions: dict[str, tuple[float, float]] = {}
    occupied = list(occupied_boxes)
    ordered = sorted(components, key=lambda item: str(item["reference"]))

    if payload.strategy == "linear":
        cursor_x_mm = payload.origin_x_mm
        base_y_mm = payload.origin_y_mm
        for component in ordered:
            width_mm, height_mm = _footprint_size_from_assignment(str(component["footprint"]))
            resolved_x_mm, resolved_y_mm = _find_open_position(
                cursor_x_mm,
                base_y_mm,
                width_mm,
                height_mm,
                sync_payload,
                occupied,
            )
            positions[str(component["reference"])] = (resolved_x_mm, resolved_y_mm)
            occupied.append(
                {
                    "x_mm": resolved_x_mm,
                    "y_mm": resolved_y_mm,
                    "width_mm": width_mm,
                    "height_mm": height_mm,
                }
            )
            cursor_x_mm = resolved_x_mm + width_mm + payload.grid_mm + PLACEMENT_MARGIN_MM
        return positions

    angle_step = (2 * math.pi) / max(6, len(ordered) - 1)
    for index, component in enumerate(ordered):
        width_mm, height_mm = _footprint_size_from_assignment(str(component["footprint"]))
        if index == 0:
            seed_x_mm = payload.origin_x_mm
            seed_y_mm = payload.origin_y_mm
        else:
            ring = ((index - 1) // 6) + 1
            angle = (index - 1) * angle_step
            radius_mm = ring * max(10.0, payload.grid_mm * 6)
            seed_x_mm = payload.origin_x_mm + (math.cos(angle) * radius_mm)
            seed_y_mm = payload.origin_y_mm + (math.sin(angle) * radius_mm)
        resolved_x_mm, resolved_y_mm = _find_open_position(
            seed_x_mm,
            seed_y_mm,
            width_mm,
            height_mm,
            sync_payload,
            occupied,
        )
        positions[str(component["reference"])] = (resolved_x_mm, resolved_y_mm)
        occupied.append(
            {
                "x_mm": resolved_x_mm,
                "y_mm": resolved_y_mm,
                "width_mm": width_mm,
                "height_mm": height_mm,
            }
        )
    return positions


def _mounting_hole_block(
    reference: str,
    x_mm: float,
    y_mm: float,
    diameter_mm: float,
    clearance_mm: float,
) -> str:
    outer_radius_mm = max((diameter_mm / 2) + clearance_mm, diameter_mm)
    outer_size_mm = diameter_mm + (clearance_mm * 2)
    return "\n".join(
        [
            f'(footprint "MountingHole_{diameter_mm:.2f}mm"',
            '\t(layer "F.Cu")',
            f'\t(uuid "{uuid.uuid4()}")',
            f"\t(at {x_mm:.4f} {y_mm:.4f} 0)",
            f'\t(property "Reference" "{reference}"',
            "\t\t(at 0 -4.0 0)",
            '\t\t(layer "F.SilkS")',
            "\t)",
            f'\t(property "Value" "MountingHole_{diameter_mm:.2f}mm"',
            "\t\t(at 0 4.0 0)",
            '\t\t(layer "F.Fab")',
            "\t)",
            "\t(attr board_only exclude_from_pos_files exclude_from_bom)",
            (
                f"\t(fp_circle (center 0 0) (end {outer_radius_mm:.4f} 0) "
                '(stroke (width 0.05) (type solid)) (fill none) (layer "F.CrtYd"))'
            ),
            (
                f"\t(fp_circle (center 0 0) (end {(diameter_mm / 2):.4f} 0) "
                '(stroke (width 0.1) (type solid)) (fill none) (layer "Cmts.User"))'
            ),
            (
                f'\t(pad "" np_thru_hole circle (at 0 0) '
                f"(size {outer_size_mm:.4f} {outer_size_mm:.4f}) "
                f'(drill {diameter_mm:.4f}) (layers "*.Cu" "*.Mask"))'
            ),
            ")",
        ]
    )


def _fiducial_block(reference: str, x_mm: float, y_mm: float, diameter_mm: float) -> str:
    courtyard_radius_mm = max((diameter_mm / 2) + 0.5, diameter_mm)
    return "\n".join(
        [
            f'(footprint "Fiducial_{diameter_mm:.2f}mm"',
            '\t(layer "F.Cu")',
            f'\t(uuid "{uuid.uuid4()}")',
            f"\t(at {x_mm:.4f} {y_mm:.4f} 0)",
            f'\t(property "Reference" "{reference}"',
            "\t\t(at 0 -2.2 0)",
            '\t\t(layer "F.SilkS")',
            "\t)",
            f'\t(property "Value" "Fiducial_{diameter_mm:.2f}mm"',
            "\t\t(at 0 2.2 0)",
            '\t\t(layer "F.Fab")',
            "\t)",
            "\t(attr smd board_only exclude_from_pos_files exclude_from_bom)",
            (
                f"\t(fp_circle (center 0 0) (end {courtyard_radius_mm:.4f} 0) "
                '(stroke (width 0.05) (type solid)) (fill none) (layer "F.CrtYd"))'
            ),
            (
                f'\t(pad "1" smd circle (at 0 0) (size {diameter_mm:.4f} {diameter_mm:.4f}) '
                '(layers "F.Cu" "F.Mask"))'
            ),
            ")",
        ]
    )


def _next_reference(existing_refs: set[str], prefix: str) -> str:
    index = 1
    while f"{prefix}{index}" in existing_refs:
        index += 1
    reference = f"{prefix}{index}"
    existing_refs.add(reference)
    return reference


def _rectangle_polygon(
    x_mm: float,
    y_mm: float,
    width_mm: float,
    height_mm: float,
) -> PolygonWithHoles:
    polygon = PolygonWithHoles()
    outline = PolyLine()
    left_mm = x_mm - (width_mm / 2)
    right_mm = x_mm + (width_mm / 2)
    top_mm = y_mm - (height_mm / 2)
    bottom_mm = y_mm + (height_mm / 2)
    for point_x_mm, point_y_mm in [
        (left_mm, top_mm),
        (right_mm, top_mm),
        (right_mm, bottom_mm),
        (left_mm, bottom_mm),
    ]:
        outline.append(PolyLineNode.from_point(Vector2.from_xy_mm(point_x_mm, point_y_mm)))
    outline.closed = True
    polygon.outline = outline
    return polygon


def _polygon_from_points(points_nm: list[tuple[int, int]]) -> PolygonWithHoles:
    polygon = PolygonWithHoles()
    outline = PolyLine()
    for point_x_nm, point_y_nm in points_nm:
        outline.append(PolyLineNode.from_point(Vector2.from_xy(point_x_nm, point_y_nm)))
    outline.closed = True
    polygon.outline = outline
    return polygon


def _append_board_blocks(content: str, blocks: list[str]) -> str:
    normalized = _normalize_board_content(content).rstrip()
    if not normalized.endswith(")"):
        raise ValueError("The active PCB file does not end with a closing parenthesis.")
    body = normalized[:-1].rstrip()
    rendered = "\n".join("\n".join("\t" + line for line in block.splitlines()) for block in blocks)
    return f"{body}\n{rendered}\n)\n"


def _replace_board_blocks(
    content: str,
    replacements: dict[str, str],
    additions: list[str],
) -> str:
    normalized = _normalize_board_content(content)
    if replacements:
        parsed = _parse_board_footprint_blocks(normalized)
        pieces: list[str] = []
        cursor = 0
        for reference, entry in sorted(
            parsed.items(),
            key=lambda item: int(cast(int, item[1]["start"])),
        ):
            start = int(entry["start"])
            end = int(entry["end"])
            pieces.append(normalized[cursor:start])
            pieces.append(replacements.get(reference, str(entry["block"])))
            cursor = end
        pieces.append(normalized[cursor:])
        normalized = "".join(pieces)
    if additions:
        normalized = _append_board_blocks(normalized, additions)
    return normalized


def _footprint_file(library: str, footprint: str) -> Path:
    cfg = get_config()
    if cfg.footprint_library_dir is None or not cfg.footprint_library_dir.exists():
        raise FileNotFoundError("No KiCad footprint library directory is configured.")
    return cfg.footprint_library_dir / f"{library}.pretty" / f"{footprint}.kicad_mod"


def _split_footprint_assignment(assignment: str) -> tuple[str, str]:
    if ":" not in assignment:
        raise ValueError(
            f"Footprint assignment '{assignment}' must use the 'Library:Footprint' format."
        )
    library, footprint = assignment.split(":", 1)
    if not library or not footprint:
        raise ValueError(
            f"Footprint assignment '{assignment}' must use the 'Library:Footprint' format."
        )
    return library, footprint


def _snap_board_coord(value: float, grid_mm: float) -> float:
    snapped = round(round(value / grid_mm) * grid_mm, 4)
    return 0.0 if abs(snapped) < 1e-6 else snapped


def _replace_property_value(block: str, field_name: str, value: str) -> str:
    pattern = re.compile(rf'(\(property\s+"{re.escape(field_name)}"\s+){STRING_PATTERN}')
    return pattern.sub(lambda match: f"{match.group(1)}{_sexpr_string(value)}", block, count=1)


def _set_pad_net_name(pad_block: str, net_name: str) -> str:
    net_pattern = re.compile(rf"(\(net\s+){STRING_PATTERN}")
    if net_pattern.search(pad_block):
        return net_pattern.sub(
            lambda match: f"{match.group(1)}{_sexpr_string(net_name)}",
            pad_block,
            count=1,
        )
    insert_at = pad_block.rfind("\n)")
    if insert_at == -1:
        insert_at = pad_block.rfind(")")
    if insert_at == -1:
        return pad_block
    return pad_block[:insert_at] + f"\n\t\t(net {_sexpr_string(net_name)})" + pad_block[insert_at:]


def _assign_pad_nets(block: str, pad_nets: dict[str, str]) -> str:
    rebuilt: list[str] = []
    cursor = 0
    while cursor < len(block):
        if block[cursor:].startswith("(pad"):
            pad_block, length = _extract_block(block, cursor)
            if pad_block:
                pad_match = re.match(rf"\(pad\s+{STRING_PATTERN}", pad_block.lstrip())
                if pad_match and pad_match.group(1) in pad_nets:
                    pad_block = _set_pad_net_name(pad_block, pad_nets[pad_match.group(1)])
                rebuilt.append(pad_block)
                cursor += length
                continue
        rebuilt.append(block[cursor])
        cursor += 1
    return "".join(rebuilt)


def _inject_root_placement(block: str, *, x_mm: float, y_mm: float, rotation: int) -> str:
    layer_match = re.search(r'\n(\s*\(layer\s+"[^"]+"\))', block)
    insertion = (
        f"\n\t(uuid {_sexpr_string(str(uuid.uuid4()))})\n\t(at {x_mm:.4f} {y_mm:.4f} {rotation})"
    )
    if layer_match:
        end = layer_match.end()
        return block[:end] + insertion + block[end:]
    line_end = block.find("\n")
    if line_end == -1:
        return block[:-1] + insertion + "\n)"
    return block[:line_end] + insertion + block[line_end:]


def _render_board_footprint_block(
    footprint_assignment: str,
    *,
    reference: str,
    value: str,
    x_mm: float,
    y_mm: float,
    rotation: int,
    pad_nets: dict[str, str],
) -> str:
    library, footprint = _split_footprint_assignment(footprint_assignment)
    path = _footprint_file(library, footprint)
    if not path.exists():
        raise FileNotFoundError(f"Footprint '{footprint_assignment}' was not found.")
    block = path.read_text(encoding="utf-8", errors="ignore").strip()
    block = _replace_property_value(block, "Reference", reference)
    block = _replace_property_value(block, "Value", value)
    block = _assign_pad_nets(block, pad_nets)
    return _inject_root_placement(block, x_mm=x_mm, y_mm=y_mm, rotation=rotation)


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


def _find_open_position(
    seed_x_mm: float,
    seed_y_mm: float,
    width_mm: float,
    height_mm: float,
    payload: SyncPcbFromSchematicInput,
    occupied: list[dict[str, float]],
) -> tuple[float, float]:
    margin_mm = PLACEMENT_MARGIN_MM

    def is_free(candidate_x_mm: float, candidate_y_mm: float) -> bool:
        return not any(
            _placement_boxes_overlap(
                candidate_x_mm,
                candidate_y_mm,
                width_mm,
                height_mm,
                box["x_mm"],
                box["y_mm"],
                box["width_mm"],
                box["height_mm"],
                margin_mm,
            )
            for box in occupied
        )

    snapped_seed = (
        _snap_board_coord(seed_x_mm, payload.grid_mm),
        _snap_board_coord(seed_y_mm, payload.grid_mm),
    )
    if is_free(*snapped_seed):
        return snapped_seed

    step_x_mm = max(
        payload.grid_mm,
        _snap_board_coord(width_mm + margin_mm, payload.grid_mm),
    )
    step_y_mm = max(
        payload.grid_mm,
        _snap_board_coord(height_mm + margin_mm, payload.grid_mm),
    )

    for radius in range(1, 25):
        candidates: list[tuple[int, int]] = []
        for delta_x in range(-radius, radius + 1):
            candidates.append((delta_x, -radius))
            candidates.append((delta_x, radius))
        for delta_y in range(-radius + 1, radius):
            candidates.append((-radius, delta_y))
            candidates.append((radius, delta_y))
        seen: set[tuple[int, int]] = set()
        for delta_x, delta_y in candidates:
            if (delta_x, delta_y) in seen:
                continue
            seen.add((delta_x, delta_y))
            candidate_x_mm = _snap_board_coord(seed_x_mm + (delta_x * step_x_mm), payload.grid_mm)
            candidate_y_mm = _snap_board_coord(seed_y_mm + (delta_y * step_y_mm), payload.grid_mm)
            if is_free(candidate_x_mm, candidate_y_mm):
                return candidate_x_mm, candidate_y_mm

    return snapped_seed


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
    last_stderr = "unknown error"
    for variant in variants:
        try:
            result = subprocess.run(
                [str(cfg.kicad_cli), *variant],
                capture_output=True,
                text=True,
                timeout=cfg.cli_timeout,
                check=False,
            )
        except OSError as exc:
            return {}, f"Netlist export failed, so pad net names were skipped: {exc}"
        if result.returncode == 0 and out_file.exists():
            content = out_file.read_text(encoding="utf-8", errors="ignore")
            return _parse_netlist_text(content), ""
        last_stderr = result.stderr.strip() or last_stderr
    return {}, f"Netlist export failed, so pad net names were skipped: {last_stderr}"


def _parse_netlist_text(content: str) -> dict[tuple[str, str], str]:
    net_map: dict[tuple[str, str], str] = {}
    cursor = 0
    while cursor < len(content):
        if content[cursor:].startswith("(net"):
            block, length = _extract_block(content, cursor)
            if block:
                name_match = re.search(rf"\(name\s+{STRING_PATTERN}\)", block)
                if name_match is not None:
                    net_name = name_match.group(1)
                    for node in re.finditer(
                        rf"\(node\s+\(ref\s+{STRING_PATTERN}\)\s+\(pin\s+{STRING_PATTERN}\)",
                        block,
                    ):
                        net_map[(node.group(1), node.group(2))] = net_name
                cursor += length
                continue
        cursor += 1
    return net_map


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


def _pcb_sync_gate_failures() -> list[str]:
    from .validation import _evaluate_schematic_connectivity_gate, _evaluate_schematic_gate

    outcomes = [_evaluate_schematic_gate(), _evaluate_schematic_connectivity_gate()]
    blocking = [outcome for outcome in outcomes if outcome.status != "PASS"]
    if not blocking:
        return []

    lines = ["PCB sync aborted because the schematic is not ready:"]
    for outcome in blocking:
        lines.append(f"- {outcome.name} quality gate: {outcome.status}")
        lines.append(f"  {outcome.summary}")
        for detail in outcome.details[:6]:
            lines.append(f"  {detail}")
    lines.append(
        "Re-run `schematic_quality_gate()` and `schematic_connectivity_gate()` after fixing "
        "the schematic."
    )
    return lines


def _planned_board_positions(
    components: list[dict[str, Any]],
    payload: SyncPcbFromSchematicInput,
    occupied_boxes: list[dict[str, float]] | None = None,
) -> dict[str, tuple[float, float]]:
    if not components:
        return {}
    min_x = min(float(component["x"]) for component in components)
    min_y = min(float(component["y"]) for component in components)
    positions: dict[str, tuple[float, float]] = {}
    occupied = list(occupied_boxes or [])
    for component in sorted(
        components,
        key=lambda item: (float(item["y"]), float(item["x"]), str(item["reference"])),
    ):
        seed_x_mm = payload.origin_x_mm + ((float(component["x"]) - min_x) * payload.scale_x)
        seed_y_mm = payload.origin_y_mm + ((float(component["y"]) - min_y) * payload.scale_y)
        width_mm, height_mm = _footprint_size_from_assignment(str(component["footprint"]))
        resolved_x_mm, resolved_y_mm = _find_open_position(
            seed_x_mm,
            seed_y_mm,
            width_mm,
            height_mm,
            payload,
            occupied,
        )
        positions[str(component["reference"])] = (resolved_x_mm, resolved_y_mm)
        occupied.append(
            {
                "x_mm": resolved_x_mm,
                "y_mm": resolved_y_mm,
                "width_mm": width_mm,
                "height_mm": height_mm,
            }
        )
    return positions


def register(mcp: FastMCP) -> None:
    """Register PCB tools."""

    @mcp.tool()
    @requires_kicad_running
    def pcb_get_board_summary() -> str:
        """Summarize the current board."""
        board = get_board()
        tracks = board.get_tracks()
        footprints = board.get_footprints()
        vias = board.get_vias()
        zones = board.get_zones()
        nets = board.get_nets(netclass_filter=None)
        shapes = board.get_shapes()
        return "\n".join(
            [
                "Board summary:",
                f"- Tracks: {len(tracks)}",
                f"- Vias: {len(vias)}",
                f"- Footprints: {len(footprints)}",
                f"- Zones: {len(zones)}",
                f"- Nets: {len(nets)}",
                f"- Shapes: {len(shapes)}",
            ]
        )

    @mcp.tool()
    @requires_kicad_running
    def pcb_get_tracks(
        page: int = 1,
        page_size: int = 100,
        filter_layer: str = "",
        filter_net: str = "",
    ) -> str:
        """List board tracks."""
        all_tracks = [
            track
            for track in cast(Iterable[Track], get_board().get_tracks())
            if _matches_layer_filter(track.layer, filter_layer)
            and (not filter_net or (track.net.name or "").casefold() == filter_net.casefold())
        ]
        tracks, total, page_count = _paginate(all_tracks, page=page, page_size=page_size)
        if total == 0:
            if filter_layer or filter_net:
                return "No tracks match the supplied filters on the active board."
            return "No tracks are present on the active board."
        if not tracks:
            return f"Track page {page} is out of range. Available pages: 1-{page_count}."

        lines = [f"Tracks ({total} total):", f"- Page {page}/{page_count} | Showing {len(tracks)}"]
        for index, track in enumerate(tracks, start=1):
            lines.append(
                f"{index}. "
                f"({nm_to_mm(_coord_nm(track.start, 'x')):.2f}, "
                f"{nm_to_mm(_coord_nm(track.start, 'y')):.2f}) -> "
                f"({nm_to_mm(_coord_nm(track.end, 'x')):.2f}, "
                f"{nm_to_mm(_coord_nm(track.end, 'y')):.2f}) mm "
                f"layer={BoardLayer.Name(track.layer)} "
                f"width={nm_to_mm(track.width):.3f} mm "
                f"net={track.net.name or '(none)'} id={_format_selection_id(track)}"
            )
        return "\n".join(lines)

    @mcp.tool()
    @requires_kicad_running
    def pcb_get_vias() -> str:
        """List board vias."""
        vias, total = _limit(cast(Iterable[Via], get_board().get_vias()))
        if not vias:
            return "No vias are present on the active board."

        lines = [f"Vias ({total} total):"]
        for index, via in enumerate(vias, start=1):
            lines.append(
                f"{index}. "
                f"({nm_to_mm(_coord_nm(via.position, 'x')):.2f}, "
                f"{nm_to_mm(_coord_nm(via.position, 'y')):.2f}) mm "
                f"diameter={nm_to_mm(via.diameter):.3f} mm "
                f"drill={nm_to_mm(via.drill_diameter):.3f} mm "
                f"net={via.net.name or '(none)'} type={ViaType.Name(via.type)}"
            )
        return "\n".join(lines)

    @mcp.tool()
    @requires_kicad_running
    def pcb_get_footprints(
        page: int = 1,
        page_size: int = 50,
        filter_layer: str = "",
    ) -> str:
        """List board footprints."""
        all_footprints = [
            footprint
            for footprint in cast(Iterable[_FootprintLike], get_board().get_footprints())
            if _matches_layer_filter(footprint.layer, filter_layer)
        ]
        footprints, total, page_count = _paginate(all_footprints, page=page, page_size=page_size)
        if total == 0:
            if filter_layer:
                return "No footprints match the supplied layer filter on the active board."
            return "No footprints are present on the active board."
        if not footprints:
            return f"Footprint page {page} is out of range. Available pages: 1-{page_count}."

        lines = [
            f"Footprints ({total} total):",
            f"- Page {page}/{page_count} | Showing {len(footprints)}",
        ]
        for footprint in footprints:
            lines.append(
                f"- {footprint.reference_field.text.value} "
                f"({footprint.value_field.text.value}) "
                f"@ ({nm_to_mm(_coord_nm(footprint.position, 'x')):.2f}, "
                f"{nm_to_mm(_coord_nm(footprint.position, 'y')):.2f}) mm "
                f"layer={BoardLayer.Name(footprint.layer)} "
                f"id={_format_selection_id(footprint)}"
            )
        return "\n".join(lines)

    @mcp.tool()
    @requires_kicad_running
    def pcb_get_nets() -> str:
        """List all board nets."""
        nets, total = _limit(cast(Iterable[Net], get_board().get_nets(netclass_filter=None)))
        if not nets:
            return "No nets are present on the active board."
        lines = [f"Nets ({total} total):"]
        lines.extend(f"- {net.name or '(unnamed)'}" for net in nets)
        return "\n".join(lines)

    @mcp.tool()
    @requires_kicad_running
    def pcb_get_zones() -> str:
        """List all board copper zones."""
        zones, total = _limit(cast(Iterable[Any], get_board().get_zones()))
        if not zones:
            return "No zones are present on the active board."

        lines = [f"Zones ({total} total):"]
        for index, zone in enumerate(zones, start=1):
            line = f"{index}. name={zone.name or '(unnamed)'} net={zone.net.name or '(none)'}"
            if hasattr(zone, "layer"):
                line += f" layer={BoardLayer.Name(zone.layer)}"
            if hasattr(zone, "layers"):
                line += f" layers={','.join(BoardLayer.Name(layer) for layer in zone.layers)}"
            lines.append(line)
        return "\n".join(lines)

    @mcp.tool()
    @requires_kicad_running
    def pcb_get_shapes() -> str:
        """List graphical board shapes."""
        shapes, total = _limit(cast(Iterable[Any], get_board().get_shapes()))
        if not shapes:
            return "No graphic shapes are present on the active board."
        lines = [f"Shapes ({total} total):"]
        for index, shape in enumerate(shapes, start=1):
            layer = getattr(shape, "layer", BoardLayer.BL_UNDEFINED)
            lines.append(f"{index}. {type(shape).__name__} layer={BoardLayer.Name(layer)}")
        return "\n".join(lines)

    @mcp.tool()
    @requires_kicad_running
    def pcb_get_pads() -> str:
        """List board pads."""
        pads, total = _limit(cast(Iterable[_PadLike], get_board().get_pads()))
        if not pads:
            return "No pads are present on the active board."
        lines = [f"Pads ({total} total):"]
        for index, pad in enumerate(pads, start=1):
            lines.append(
                f"{index}. {pad.parent.reference_field.text.value}:{pad.number} "
                f"net={pad.net.name or '(none)'} "
                f"@ ({nm_to_mm(_coord_nm(pad.position, 'x')):.2f}, "
                f"{nm_to_mm(_coord_nm(pad.position, 'y')):.2f}) mm"
            )
        return "\n".join(lines)

    @mcp.tool()
    @requires_kicad_running
    def pcb_get_layers() -> str:
        """List enabled board layers."""
        layers = get_board().get_enabled_layers()
        names = [BoardLayer.Name(layer) for layer in layers]
        return "Enabled layers:\n" + "\n".join(f"- {name}" for name in names)

    @mcp.tool()
    @headless_compatible
    def pcb_get_stackup() -> str:
        """Show the current stackup."""
        try:
            layers = _current_stackup_specs()
        except ValueError as exc:
            return str(exc)

        lines = [f"Board stackup ({len(layers)} layers):"]
        for index, layer in enumerate(layers, start=1):
            extras: list[str] = []
            if layer.epsilon_r is not None:
                extras.append(f"Er={layer.epsilon_r:.3f}")
            if layer.loss_tangent is not None:
                extras.append(f"loss={layer.loss_tangent:.4f}")
            suffix = f" | {' | '.join(extras)}" if extras else ""
            lines.append(
                f"- {index}. {layer.name} | type={layer.type} | "
                f"thickness={layer.thickness_mm:.4f} mm | material={layer.material}{suffix}"
            )
        lines.append(f"- Total thickness: {_total_stackup_thickness_mm(layers):.4f} mm")
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def pcb_set_stackup(layers: list[dict[str, object]]) -> str:
        """Set the active board stackup using a file-backed profile."""
        payload = SetStackupInput.model_validate({"layers": layers})
        copper_count = sum(1 for layer in payload.layers if _is_copper_stackup_layer(layer))
        if copper_count < 2:
            raise ValueError("A valid stackup needs at least two copper layers.")

        state_path = _write_stackup_state(payload.layers)
        _transactional_board_write(lambda current: _apply_stackup_to_board(current, payload.layers))
        reload_message = _reload_board_after_file_sync()
        return "\n".join(
            [
                f"Configured stackup with {len(payload.layers)} layers.",
                f"- Copper layers: {copper_count}",
                f"- Total thickness: {_total_stackup_thickness_mm(payload.layers):.4f} mm",
                f"- Saved stackup state: {state_path}",
                f"- {reload_message}",
            ]
        )

    @mcp.tool()
    @headless_compatible
    def pcb_get_impedance_for_trace(width_mm: float, layer_name: str) -> str:
        """Estimate trace impedance for the supplied width on the named stackup layer."""
        payload = ImpedanceForTraceInput(width_mm=width_mm, layer_name=layer_name)
        specs = _current_stackup_specs()
        trace_type, height_mm, er, copper_oz = _impedance_context_for_layer(
            specs,
            payload.layer_name,
        )
        impedance_ohm, effective_er = trace_impedance(
            payload.width_mm,
            height_mm,
            er,
            trace_type=trace_type,
            copper_oz=copper_oz,
        )
        return "\n".join(
            [
                "Trace impedance from current stackup:",
                f"- Layer: {resolve_layer_name(payload.layer_name)}",
                f"- Trace type: {trace_type}",
                f"- Width: {payload.width_mm:.4f} mm",
                f"- Reference dielectric height: {height_mm:.4f} mm",
                f"- Effective dielectric constant: {effective_er:.3f}",
                f"- Copper weight estimate: {copper_oz:.3f} oz",
                f"- Estimated impedance: {impedance_ohm:.2f} ohm",
            ]
        )

    @mcp.tool()
    @headless_compatible
    def pcb_check_creepage_clearance(
        voltage_v: float,
        pollution_degree: int = 2,
        material_group: int = 3,
    ) -> str:
        """Run a heuristic creepage clearance review against pad spacing."""
        payload = CreepageCheckInput(
            voltage_v=voltage_v,
            pollution_degree=pollution_degree,
            material_group=material_group,
        )
        if not _board_is_open():
            return (
                "Creepage review requires an active PCB opened through KiCad IPC. "
                "Open the board in KiCad and rerun this tool."
            )

        pads = cast(list[_PadLike], list(get_board().get_pads()))
        if len(pads) < 2:
            return "At least two pads are required to evaluate creepage clearance."

        required_mm = _required_creepage_mm(
            payload.voltage_v,
            payload.pollution_degree,
            payload.material_group,
        )
        worst_pair: tuple[float, str, str, str, str] | None = None

        for left_index, left_pad in enumerate(pads):
            left_net = str(getattr(getattr(left_pad, "net", None), "name", "") or "")
            if not left_net:
                continue
            left_size = getattr(left_pad, "size", Vector2.from_xy_mm(1.0, 1.0))
            left_radius_mm = (
                nm_to_mm(max(_coord_nm(left_size, "x"), _coord_nm(left_size, "y"))) / 2
            )
            left_x_mm = nm_to_mm(_coord_nm(left_pad.position, "x"))
            left_y_mm = nm_to_mm(_coord_nm(left_pad.position, "y"))
            left_ref = str(left_pad.parent.reference_field.text.value)
            left_pin = str(left_pad.number)

            for right_pad in pads[left_index + 1 :]:
                right_net = str(getattr(getattr(right_pad, "net", None), "name", "") or "")
                if not right_net or right_net == left_net:
                    continue
                right_size = getattr(right_pad, "size", Vector2.from_xy_mm(1.0, 1.0))
                right_radius_mm = (
                    nm_to_mm(max(_coord_nm(right_size, "x"), _coord_nm(right_size, "y"))) / 2
                )
                right_x_mm = nm_to_mm(_coord_nm(right_pad.position, "x"))
                right_y_mm = nm_to_mm(_coord_nm(right_pad.position, "y"))
                center_distance_mm = math.hypot(left_x_mm - right_x_mm, left_y_mm - right_y_mm)
                edge_distance_mm = max(
                    0.0,
                    center_distance_mm - left_radius_mm - right_radius_mm,
                )
                right_ref = str(right_pad.parent.reference_field.text.value)
                right_pin = str(right_pad.number)
                candidate = (
                    edge_distance_mm,
                    f"{left_ref}.{left_pin}",
                    left_net,
                    f"{right_ref}.{right_pin}",
                    right_net,
                )
                if worst_pair is None or candidate[0] < worst_pair[0]:
                    worst_pair = candidate

        if worst_pair is None:
            return "No pad pairs on different named nets were available for creepage analysis."

        actual_mm, left_name, left_net, right_name, right_net = worst_pair
        verdict = "PASS" if actual_mm >= required_mm else "WARN"
        return "\n".join(
            [
                f"Creepage clearance review ({verdict}):",
                f"- Voltage: {payload.voltage_v:.1f} V",
                f"- Pollution degree: {payload.pollution_degree}",
                f"- Material group: {payload.material_group}",
                f"- Required creepage (IEC-inspired heuristic): {required_mm:.3f} mm",
                f"- Worst pad pair: {left_name} ({left_net}) vs {right_name} ({right_net})",
                f"- Estimated edge-to-edge clearance: {actual_mm:.3f} mm",
                "- Method: center spacing minus approximate pad radius on different nets.",
            ]
        )

    @mcp.tool()
    def pcb_get_selection() -> str:
        """List currently selected items in the PCB editor."""
        items = list(get_board().get_selection())
        if not items:
            return "No PCB items are currently selected."
        lines = [f"Selected items ({len(items)} total):"]
        for index, item in enumerate(items, start=1):
            lines.append(f"{index}. {type(item).__name__} id={_format_selection_id(item)}")
        return "\n".join(lines)

    @mcp.tool()
    def pcb_get_board_as_string() -> str:
        """Return the current board as a bounded S-expression string."""
        cfg = get_config()
        data = get_board().get_as_string()
        if len(data) > cfg.max_text_response_chars:
            return f"{data[: cfg.max_text_response_chars]}\n... [truncated]"
        return data

    @mcp.tool()
    def pcb_get_ratsnest() -> str:
        """Report currently unconnected board items using the latest DRC view."""
        board = get_board()
        nets = board.get_nets(netclass_filter=None)
        if not nets:
            return "The active board has no nets to analyze."
        return (
            "Live ratsnest extraction is not exposed by KiCad 10.x IPC. "
            "Run `get_unconnected_nets()` or `run_drc()` for an actionable list."
        )

    @mcp.tool()
    def pcb_get_design_rules() -> str:
        """Read the active board design rules file when available."""
        cfg = get_config()
        if cfg.project_dir is None:
            return "No active project is configured."

        matches = sorted(cfg.project_dir.glob("*.kicad_dru"))
        if not matches:
            return "No .kicad_dru design rules file was found in the active project."

        content = matches[0].read_text(encoding="utf-8", errors="ignore")
        if len(content) > cfg.max_text_response_chars:
            content = f"{content[: cfg.max_text_response_chars]}\n... [truncated]"
        return content

    @mcp.tool()
    @requires_kicad_running
    def pcb_add_track(
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        layer: str = "F_Cu",
        width_mm: float = 0.25,
        net_name: str = "",
    ) -> str:
        """Add a single track segment."""
        payload = AddTrackInput(
            x1_mm=x1_mm,
            y1_mm=y1_mm,
            x2_mm=x2_mm,
            y2_mm=y2_mm,
            layer=layer,
            width_mm=width_mm,
            net_name=net_name,
        )
        with board_transaction() as board:
            track = Track()
            track.start = Vector2.from_xy_mm(payload.x1_mm, payload.y1_mm)
            track.end = Vector2.from_xy_mm(payload.x2_mm, payload.y2_mm)
            track.layer = resolve_layer(payload.layer)
            track.width = mm_to_nm(payload.width_mm)
            if payload.net_name:
                track.net = _find_net(payload.net_name)
            board.create_items([track])
        return "Track added successfully."

    @mcp.tool()
    def pcb_add_tracks_bulk(tracks: list[BulkTrackItem]) -> str:
        """Add multiple tracks in a single operation."""
        validated = [BulkTrackItem.model_validate(track) for track in tracks]
        created: list[Track] = []
        for track_input in validated:
            track = Track()
            track.start = Vector2.from_xy_mm(track_input.x1, track_input.y1)
            track.end = Vector2.from_xy_mm(track_input.x2, track_input.y2)
            track.layer = resolve_layer(track_input.layer)
            track.width = mm_to_nm(track_input.width)
            if track_input.net:
                track.net = _find_net(track_input.net)
            created.append(track)
        with board_transaction() as board:
            board.create_items(created)
        return f"Added {len(created)} tracks."

    @mcp.tool()
    @requires_kicad_running
    def pcb_add_via(
        x_mm: float,
        y_mm: float,
        diameter_mm: float = 0.8,
        drill_mm: float = 0.4,
        net_name: str = "",
        via_type: str = "through",
    ) -> str:
        """Add a via."""
        payload = AddViaInput(
            x_mm=x_mm,
            y_mm=y_mm,
            diameter_mm=diameter_mm,
            drill_mm=drill_mm,
            net_name=net_name,
            via_type=via_type,
        )
        type_map: dict[str, ViaType.ValueType] = {
            "through": ViaType.VT_THROUGH,
            "blind": ViaType.VT_BLIND_BURIED,
            "micro": ViaType.VT_MICRO,
        }
        via = Via()
        via.position = Vector2.from_xy_mm(payload.x_mm, payload.y_mm)
        via.diameter = mm_to_nm(payload.diameter_mm)
        via.drill_diameter = mm_to_nm(payload.drill_mm)
        via.type = type_map[payload.via_type]
        if payload.net_name:
            via.net = _find_net(payload.net_name)
        with board_transaction() as board:
            board.create_items([via])
        return "Via added successfully."

    @mcp.tool()
    def pcb_add_blind_via(
        x_mm: float,
        y_mm: float,
        from_layer: str,
        to_layer: str,
        drill_mm: float = 0.2,
        diameter_mm: float = 0.45,
        net_name: str = "",
    ) -> str:
        """Add a blind or buried via between the requested copper layers."""
        payload = LayerViaInput(
            x_mm=x_mm,
            y_mm=y_mm,
            from_layer=from_layer,
            to_layer=to_layer,
            drill_mm=drill_mm,
            diameter_mm=diameter_mm,
            net_name=net_name,
        )
        start_order = _copper_layer_order(payload.from_layer)
        end_order = _copper_layer_order(payload.to_layer)
        if start_order == end_order:
            raise ValueError("Blind vias require two different copper layers.")
        if {start_order, end_order} == {0, len(_COPPER_LAYER_SEQUENCE) - 1}:
            raise ValueError("Use pcb_add_via for full-stack through vias.")

        via = Via()
        via.position = Vector2.from_xy_mm(payload.x_mm, payload.y_mm)
        via.diameter = mm_to_nm(payload.diameter_mm)
        via.drill_diameter = mm_to_nm(payload.drill_mm)
        via.type = ViaType.VT_BLIND_BURIED
        _configure_layer_via(via, from_layer=payload.from_layer, to_layer=payload.to_layer)
        if payload.net_name:
            via.net = _find_net(payload.net_name)
        with board_transaction() as board:
            board.create_items([via])
        from_name = resolve_layer_name(payload.from_layer)
        to_name = resolve_layer_name(payload.to_layer)
        return (
            "Blind or buried via added successfully "
            f"from {from_name} to {to_name}."
        )

    @mcp.tool()
    def pcb_add_microvia(
        x_mm: float,
        y_mm: float,
        from_layer: str,
        to_layer: str,
        drill_mm: float = 0.1,
        diameter_mm: float = 0.25,
        net_name: str = "",
    ) -> str:
        """Add a microvia between adjacent copper layers."""
        payload = LayerViaInput(
            x_mm=x_mm,
            y_mm=y_mm,
            from_layer=from_layer,
            to_layer=to_layer,
            drill_mm=drill_mm,
            diameter_mm=diameter_mm,
            net_name=net_name,
        )
        start_order = _copper_layer_order(payload.from_layer)
        end_order = _copper_layer_order(payload.to_layer)
        if start_order == end_order:
            raise ValueError("Microvias require two different copper layers.")
        if abs(start_order - end_order) != 1:
            raise ValueError("Microvias should connect adjacent copper layers.")

        via = Via()
        via.position = Vector2.from_xy_mm(payload.x_mm, payload.y_mm)
        via.diameter = mm_to_nm(payload.diameter_mm)
        via.drill_diameter = mm_to_nm(payload.drill_mm)
        via.type = ViaType.VT_MICRO
        _configure_layer_via(via, from_layer=payload.from_layer, to_layer=payload.to_layer)
        if payload.net_name:
            via.net = _find_net(payload.net_name)
        with board_transaction() as board:
            board.create_items([via])
        from_name = resolve_layer_name(payload.from_layer)
        to_name = resolve_layer_name(payload.to_layer)
        return (
            "Microvia added successfully "
            f"from {from_name} to {to_name}."
        )

    @mcp.tool()
    def pcb_add_segment(
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        layer: str = "Edge_Cuts",
        width_mm: float = 0.05,
    ) -> str:
        """Add a board graphic segment."""
        payload = AddSegmentInput(
            x1_mm=x1_mm,
            y1_mm=y1_mm,
            x2_mm=x2_mm,
            y2_mm=y2_mm,
            layer=layer,
            width_mm=width_mm,
        )
        segment = BoardSegment()
        segment.layer = resolve_layer(payload.layer)
        segment.start = Vector2.from_xy_mm(payload.x1_mm, payload.y1_mm)
        segment.end = Vector2.from_xy_mm(payload.x2_mm, payload.y2_mm)
        segment.attributes.stroke.width = mm_to_nm(payload.width_mm)
        with board_transaction() as board:
            board.create_items([segment])
        return "Graphic segment added successfully."

    @mcp.tool()
    def pcb_add_circle(
        cx_mm: float,
        cy_mm: float,
        radius_mm: float,
        layer: str = "Edge_Cuts",
        width_mm: float = 0.05,
    ) -> str:
        """Add a board graphic circle."""
        payload = AddCircleInput(
            cx_mm=cx_mm,
            cy_mm=cy_mm,
            radius_mm=radius_mm,
            layer=layer,
            width_mm=width_mm,
        )
        circle = BoardCircle()
        circle.layer = resolve_layer(payload.layer)
        circle.center = Vector2.from_xy_mm(payload.cx_mm, payload.cy_mm)
        circle.radius_point = Vector2.from_xy_mm(payload.cx_mm + payload.radius_mm, payload.cy_mm)
        circle.attributes.stroke.width = mm_to_nm(payload.width_mm)
        with board_transaction() as board:
            board.create_items([circle])
        return "Graphic circle added successfully."

    @mcp.tool()
    def pcb_add_rectangle(
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        layer: str = "Edge_Cuts",
        width_mm: float = 0.05,
    ) -> str:
        """Add a board graphic rectangle."""
        payload = AddRectangleInput(
            x1_mm=x1_mm,
            y1_mm=y1_mm,
            x2_mm=x2_mm,
            y2_mm=y2_mm,
            layer=layer,
            width_mm=width_mm,
        )
        rectangle = BoardRectangle()
        rectangle.layer = resolve_layer(payload.layer)
        rectangle.top_left = Vector2.from_xy_mm(payload.x1_mm, payload.y1_mm)
        rectangle.bottom_right = Vector2.from_xy_mm(payload.x2_mm, payload.y2_mm)
        rectangle.attributes.stroke.width = mm_to_nm(payload.width_mm)
        with board_transaction() as board:
            board.create_items([rectangle])
        return "Graphic rectangle added successfully."

    @mcp.tool()
    def pcb_set_board_outline(
        width_mm: float,
        height_mm: float,
        origin_x_mm: float = 0.0,
        origin_y_mm: float = 0.0,
    ) -> str:
        """Draw a rectangular board outline on Edge.Cuts."""
        payload = SetBoardOutlineInput(
            width_mm=width_mm,
            height_mm=height_mm,
            origin_x_mm=origin_x_mm,
            origin_y_mm=origin_y_mm,
        )
        rectangle = BoardRectangle()
        rectangle.layer = BoardLayer.BL_Edge_Cuts
        rectangle.top_left = Vector2.from_xy_mm(payload.origin_x_mm, payload.origin_y_mm)
        rectangle.bottom_right = Vector2.from_xy_mm(
            payload.origin_x_mm + payload.width_mm,
            payload.origin_y_mm + payload.height_mm,
        )
        rectangle.attributes.stroke.width = mm_to_nm(0.05)
        with board_transaction() as board:
            board.create_items([rectangle])
        return "Board outline added successfully."

    @mcp.tool()
    def pcb_add_text(
        text: str,
        x_mm: float,
        y_mm: float,
        layer: str = "F_SilkS",
        size_mm: float = 1.0,
        rotation_deg: float = 0.0,
        bold: bool = False,
        italic: bool = False,
    ) -> str:
        """Add board text."""
        payload = AddTextInput(
            text=text,
            x_mm=x_mm,
            y_mm=y_mm,
            layer=layer,
            size_mm=size_mm,
            rotation_deg=rotation_deg,
            bold=bold,
            italic=italic,
        )
        text_item = BoardText()
        text_item.layer = resolve_layer(payload.layer)
        text_item.position = Vector2.from_xy_mm(payload.x_mm, payload.y_mm)
        text_item.value = payload.text
        text_item.attributes.size = Vector2.from_xy_mm(payload.size_mm, payload.size_mm)
        text_item.attributes.bold = payload.bold
        text_item.attributes.italic = payload.italic
        text_item.attributes.horizontal_alignment = common_types.HA_LEFT
        text_item.attributes.vertical_alignment = common_types.VA_BOTTOM
        try:
            text_item.attributes.angle = payload.rotation_deg
        except Exception as exc:
            logger.debug("board_text_angle_not_supported", error=str(exc))
        with board_transaction() as board:
            board.create_items([text_item])
        return "Board text added successfully."

    @mcp.tool()
    def pcb_delete_items(item_ids: list[str]) -> str:
        """Delete items by UUID."""
        from kipy.proto.common.types import KIID

        if not item_ids:
            return "No item IDs were supplied."
        kiids = []
        for item_id in item_ids:
            kiid = KIID()
            kiid.value = item_id
            kiids.append(kiid)
        with board_transaction() as board:
            board.remove_items_by_id(kiids)
        return f"Deleted {len(kiids)} item(s)."

    @mcp.tool()
    def pcb_save() -> str:
        """Save the active board."""
        save = cast(Callable[[], None], get_board().save)
        save()
        return "Board saved."

    @mcp.tool()
    def pcb_refill_zones() -> str:
        """Refill all copper zones."""
        get_board().refill_zones(block=True, max_poll_seconds=60.0)
        return "Zones refilled."

    @mcp.tool()
    def pcb_highlight_net(net_name: str) -> str:
        """Attempt to highlight a net in the GUI when supported."""
        if not get_config().enable_experimental_tools:
            return "Net highlighting is experimental. Enable experimental tools to try it."
        return (
            "Net highlighting is not exposed as a stable KiCad 10.x IPC operation. "
            "Use `pcb_get_nets()` to confirm "
            f"the net '{net_name}' exists and highlight it in the GUI."
        )

    @mcp.tool()
    def pcb_set_net_class(net_name: str, class_name: str) -> str:
        """Assign a net class when the runtime supports it."""
        if not get_config().enable_experimental_tools:
            return "Net class assignment is experimental. Enable experimental tools to try it."
        return (
            "Direct net class assignment is not exposed as a stable KiCad 10.x IPC operation. "
            f"Update the project rules for net '{net_name}' to use class '{class_name}'."
        )

    @mcp.tool()
    @requires_kicad_running
    def pcb_move_footprint(
        reference: str, x_mm: float, y_mm: float, rotation_deg: float = 0.0
    ) -> str:
        """Move a footprint to an absolute location."""
        footprint = _find_footprint_by_reference(reference)
        if footprint is None:
            return f"Footprint '{reference}' was not found on the active board."

        footprint.position = Vector2.from_xy_mm(x_mm, y_mm)
        if hasattr(footprint, "angle"):
            try:
                footprint.angle = Angle.from_degrees(rotation_deg)
            except Exception as exc:
                logger.debug("footprint_angle_not_supported", error=str(exc))
        elif hasattr(footprint, "orientation"):
            try:
                footprint.orientation = rotation_deg
            except Exception as exc:
                logger.debug("footprint_orientation_not_supported", error=str(exc))
        with board_transaction() as board:
            board.update_items([cast(BoardItem, footprint)])
        return f"Moved footprint '{reference}' to ({x_mm}, {y_mm}) mm."

    @mcp.tool()
    @requires_kicad_running
    def pcb_set_footprint_layer(reference: str, layer: str) -> str:
        """Set the footprint copper side."""
        footprint = _find_footprint_by_reference(reference)
        if footprint is None:
            return f"Footprint '{reference}' was not found on the active board."
        footprint.layer = resolve_layer(layer)
        with board_transaction() as board:
            board.update_items([cast(BoardItem, footprint)])
        return f"Updated footprint '{reference}' to layer '{layer}'."

    @mcp.tool()
    @headless_compatible
    def pcb_sync_from_schematic(
        origin_x_mm: float = 20.0,
        origin_y_mm: float = 20.0,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        grid_mm: float = 2.54,
        allow_open_board: bool = False,
        use_net_names: bool = True,
        replace_mismatched: bool = False,
    ) -> str:
        """Sync missing PCB footprints from schematic footprint assignments.

        This is a file-based operation intended for initial board bring-up. It adds
        missing footprint instances to the `.kicad_pcb` file using schematic
        references, values, rotations, and assigned `Library:Footprint` names.
        When `replace_mismatched=True`, existing footprints with the same
        reference but the wrong footprint name are replaced in place.
        """
        payload = SyncPcbFromSchematicInput(
            origin_x_mm=origin_x_mm,
            origin_y_mm=origin_y_mm,
            scale_x=scale_x,
            scale_y=scale_y,
            grid_mm=grid_mm,
            allow_open_board=allow_open_board,
            use_net_names=use_net_names,
            replace_mismatched=replace_mismatched,
        )
        if _board_is_open() and not payload.allow_open_board:
            return (
                "Refusing file-based PCB sync while a board is open in KiCad. "
                "Close the board first, or rerun with allow_open_board=True if you want "
                "KiCad to reload the updated file from disk."
            )
        if blocking_lines := _pcb_sync_gate_failures():
            return "\n".join(blocking_lines)

        components, issues = _collect_schematic_components()
        if issues:
            return "PCB sync aborted:\n" + "\n".join(f"- {issue}" for issue in issues)
        if not components:
            return "No schematic symbols were found to sync."

        missing_assignments = [
            component["reference"]
            for component in components
            if not str(component["footprint"]).strip()
        ]
        if missing_assignments:
            return (
                "PCB sync aborted because some schematic symbols are missing "
                "footprint assignments:\n"
                + "\n".join(f"- {reference}" for reference in missing_assignments)
            )

        board_file = _get_pcb_file_for_sync()
        board_content = _normalize_board_content(
            board_file.read_text(encoding="utf-8", errors="ignore")
        )
        existing = _parse_board_footprint_blocks(board_content)
        components_by_reference = {
            str(component["reference"]): component for component in components
        }

        expected_names = {
            str(component["reference"]): _split_footprint_assignment(str(component["footprint"]))[1]
            for component in components
        }
        mismatched_references = [
            reference
            for reference, entry in existing.items()
            if reference in expected_names and entry["name"] != expected_names[reference]
        ]
        mismatches = [
            (
                f"{reference}: board has {existing[reference]['name']}, "
                f"schematic expects {expected_names[reference]}"
            )
            for reference in mismatched_references
        ]

        net_map: dict[tuple[str, str], str] = {}
        net_note = ""
        if payload.use_net_names:
            net_map, net_note = _export_schematic_net_map()
        pad_summary = _schematic_pad_net_summary(components, net_map)

        additions: list[str] = []
        replacements: dict[str, str] = {}
        occupied_boxes = [
            {
                "x_mm": float(entry["x_mm"]),
                "y_mm": float(entry["y_mm"]),
                "width_mm": float(entry["width_mm"]),
                "height_mm": float(entry["height_mm"]),
            }
            for entry in existing.values()
            if entry["x_mm"] is not None and entry["y_mm"] is not None
        ]
        components_to_add = [
            component for component in components if str(component["reference"]) not in existing
        ]
        placements = _planned_board_positions(components_to_add, payload, occupied_boxes)

        for component in components_to_add:
            reference = str(component["reference"])
            x_mm, y_mm = placements[reference]
            pad_nets = {
                pin: name for (ref, pin), name in net_map.items() if ref == reference and name
            }
            additions.append(
                _render_board_footprint_block(
                    str(component["footprint"]),
                    reference=reference,
                    value=str(component["value"]),
                    x_mm=x_mm,
                    y_mm=y_mm,
                    rotation=int(component["rotation"]),
                    pad_nets=pad_nets,
                )
            )

        if payload.replace_mismatched:
            for reference in mismatched_references:
                component = components_by_reference[reference]
                existing_entry = existing[reference]
                x_mm = (
                    float(existing_entry["x_mm"])
                    if existing_entry["x_mm"] is not None
                    else payload.origin_x_mm
                )
                y_mm = (
                    float(existing_entry["y_mm"])
                    if existing_entry["y_mm"] is not None
                    else payload.origin_y_mm
                )
                pad_nets = {
                    pin: name for (ref, pin), name in net_map.items() if ref == reference and name
                }
                replacements[reference] = _render_board_footprint_block(
                    str(component["footprint"]),
                    reference=reference,
                    value=str(component["value"]),
                    x_mm=x_mm,
                    y_mm=y_mm,
                    rotation=int(existing_entry["rotation"]),
                    pad_nets=pad_nets,
                )

        if not additions and not mismatches:
            return "The PCB already contains all schematic footprint assignments."

        if additions or replacements:
            _transactional_board_write(
                lambda current: _replace_board_blocks(current, replacements, additions)
            )

        reload_note = (
            _reload_board_after_file_sync()
            if (additions or replacements) and payload.allow_open_board
            else "The PCB file was updated. Reload it manually in KiCad if needed."
            if additions or replacements
            else ""
        )

        lines = [
            f"Schematic components considered: {len(components)}",
            f"Existing PCB footprints kept: {len(existing) - len(replacements)}",
            f"New footprints added: {len(additions)}",
            f"Mismatched footprints replaced: {len(replacements)}",
            f"Total pads considered: {pad_summary['total_pads']}",
            f"Pads with named nets: {pad_summary['named_pads']}",
            f"Pads left as <no net>: {pad_summary['no_net_pads']}",
            "Transfer quality: "
            f"{pad_summary['quality']} ({pad_summary['coverage_pct']}% pad coverage)",
            f"Fully net-mapped refs: {pad_summary['fully_named_refs']}",
            f"Partially net-mapped refs: {pad_summary['partial_refs']}",
        ]
        unresolved_refs = cast(list[str], pad_summary["unresolved_refs"])
        lines.append(
            "Refs with unresolved pad nets: "
            + (", ".join(unresolved_refs[:12]) if unresolved_refs else "(none)")
        )
        if len(unresolved_refs) > 12:
            lines.append(f"... and {len(unresolved_refs) - 12} more")
        if mismatches:
            lines.append("Existing footprint mismatches:")
            lines.extend(f"- {mismatch}" for mismatch in mismatches[:20])
            if len(mismatches) > 20:
                lines.append(f"... and {len(mismatches) - 20} more")
            if not payload.replace_mismatched:
                lines.append(
                    "Rerun with replace_mismatched=True to replace those footprints in place."
                )
        if net_note:
            lines.append(net_note)
        if reload_note:
            lines.append(reload_note)
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def pcb_auto_place_by_schematic(
        strategy: str = "cluster",
        origin_x_mm: float = 20.0,
        origin_y_mm: float = 20.0,
        scale_x: float = 1.0,
        scale_y: float = 1.0,
        grid_mm: float = 2.54,
        allow_open_board: bool = False,
        sync_missing: bool = True,
    ) -> str:
        """Place PCB footprints from the current schematic using deterministic heuristics."""
        payload = AutoPlaceBySchematicInput(
            strategy=strategy,
            origin_x_mm=origin_x_mm,
            origin_y_mm=origin_y_mm,
            scale_x=scale_x,
            scale_y=scale_y,
            grid_mm=grid_mm,
            allow_open_board=allow_open_board,
            sync_missing=sync_missing,
        )
        if refusal := _guard_file_based_board_edit("auto-placement", payload.allow_open_board):
            return refusal

        components, issues = _collect_schematic_components()
        if issues:
            return "Auto-placement aborted:\n" + "\n".join(f"- {issue}" for issue in issues)
        if not components:
            return "No schematic symbols were found to place."

        board_file = _get_pcb_file_for_sync()
        board_content = _normalize_board_content(
            board_file.read_text(encoding="utf-8", errors="ignore")
        )
        existing = _parse_board_footprint_blocks(board_content)
        component_refs = {str(component["reference"]) for component in components}
        occupied = _collect_occupied_boxes(existing, exclude_refs=component_refs)
        positions = _strategy_board_positions(components, payload, occupied)

        additions: list[str] = []
        replacements: dict[str, str] = {}
        missing_refs: list[str] = []
        moved_existing = 0

        for component in components:
            reference = str(component["reference"])
            x_mm, y_mm = positions[reference]
            rotation = int(component["rotation"])
            if reference in existing:
                replacements[reference] = _replace_root_at(
                    str(existing[reference]["block"]),
                    x_mm=x_mm,
                    y_mm=y_mm,
                    rotation=rotation,
                )
                moved_existing += 1
                continue
            if not payload.sync_missing:
                missing_refs.append(reference)
                continue
            additions.append(
                _render_board_footprint_block(
                    str(component["footprint"]),
                    reference=reference,
                    value=str(component["value"]),
                    x_mm=x_mm,
                    y_mm=y_mm,
                    rotation=rotation,
                    pad_nets={},
                )
            )

        if replacements or additions:
            _transactional_board_write(
                lambda current: _replace_board_blocks(current, replacements, additions)
            )

        lines = [
            f"Auto-placement strategy: {payload.strategy}",
            f"Existing footprints moved: {moved_existing}",
            f"Missing footprints added: {len(additions)}",
        ]
        if missing_refs:
            lines.append("Missing schematic references left untouched:")
            lines.extend(f"- {reference}" for reference in missing_refs[:20])
            if len(missing_refs) > 20:
                lines.append(f"... and {len(missing_refs) - 20} more")
            lines.append("Rerun with sync_missing=True to add them automatically.")
        if replacements or additions:
            lines.append(_finalize_file_based_board_edit(payload.allow_open_board))
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def pcb_place_decoupling_caps(
        ic_ref: str,
        cap_refs: list[str],
        side: str = "same",
        max_distance_mm: float = 2.0,
        grid_mm: float = 1.27,
        allow_open_board: bool = False,
    ) -> str:
        """Move capacitor footprints into a tight row near a target IC footprint."""
        payload = PlaceDecouplingCapsInput(
            ic_ref=ic_ref,
            cap_refs=cap_refs,
            side=side,
            max_distance_mm=max_distance_mm,
            grid_mm=grid_mm,
            allow_open_board=allow_open_board,
        )
        if refusal := _guard_file_based_board_edit(
            "decoupling capacitor placement", payload.allow_open_board
        ):
            return refusal

        board_file = _get_pcb_file_for_sync()
        board_content = _normalize_board_content(
            board_file.read_text(encoding="utf-8", errors="ignore")
        )
        existing = _parse_board_footprint_blocks(board_content)
        if payload.ic_ref not in existing:
            return f"Footprint '{payload.ic_ref}' was not found on the PCB file."

        missing_caps = [reference for reference in payload.cap_refs if reference not in existing]
        if missing_caps:
            return (
                "Decoupling placement aborted because some capacitor references are missing:\n"
                + "\n".join(f"- {reference}" for reference in missing_caps)
            )

        ic_entry = existing[payload.ic_ref]
        ic_x_mm = float(ic_entry["x_mm"] or 0.0)
        ic_y_mm = float(ic_entry["y_mm"] or 0.0)
        ic_height_mm = float(ic_entry["height_mm"])
        ordered_caps = [existing[reference] for reference in payload.cap_refs]
        pitch_mm = max(float(entry["width_mm"]) for entry in ordered_caps) + payload.grid_mm
        cap_band_y_mm = (
            ic_y_mm - ((ic_height_mm / 2) + payload.max_distance_mm)
            if payload.side == "same"
            else ic_y_mm + ((ic_height_mm / 2) + payload.max_distance_mm)
        )
        base_x_mm = ic_x_mm - (((len(payload.cap_refs) - 1) * pitch_mm) / 2)
        occupied = _collect_occupied_boxes(existing, exclude_refs=set(payload.cap_refs))

        replacements: dict[str, str] = {}
        moved = 0
        for index, reference in enumerate(payload.cap_refs):
            entry = existing[reference]
            width_mm = float(entry["width_mm"])
            height_mm = float(entry["height_mm"])
            resolved_x_mm, resolved_y_mm = _find_open_position(
                base_x_mm + (index * pitch_mm),
                cap_band_y_mm,
                width_mm,
                height_mm,
                SyncPcbFromSchematicInput(grid_mm=payload.grid_mm),
                occupied,
            )
            replacements[reference] = _replace_root_at(
                str(entry["block"]),
                x_mm=resolved_x_mm,
                y_mm=resolved_y_mm,
                rotation=int(entry["rotation"]),
            )
            occupied.append(
                {
                    "x_mm": resolved_x_mm,
                    "y_mm": resolved_y_mm,
                    "width_mm": width_mm,
                    "height_mm": height_mm,
                }
            )
            moved += 1

        _transactional_board_write(lambda current: _replace_board_blocks(current, replacements, []))

        lines = [
            f"Placed {moved} decoupling capacitor(s) near {payload.ic_ref}.",
            f"Preferred placement band: {payload.side}.",
        ]
        if payload.side == "opposite":
            lines.append(
                "Note: file-based placement keeps the current copper side; "
                "only the preferred placement band changes."
            )
        lines.append(_finalize_file_based_board_edit(payload.allow_open_board))
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def pcb_group_by_function(
        groups: dict[str, list[str]],
        origin_x_mm: float = 20.0,
        origin_y_mm: float = 20.0,
        group_spacing_mm: float = 20.0,
        item_spacing_mm: float = 5.08,
        grid_mm: float = 1.27,
        allow_open_board: bool = False,
    ) -> str:
        """Cluster existing footprints into named functional groups."""
        payload = GroupFootprintsInput(
            groups=groups,
            origin_x_mm=origin_x_mm,
            origin_y_mm=origin_y_mm,
            group_spacing_mm=group_spacing_mm,
            item_spacing_mm=item_spacing_mm,
            grid_mm=grid_mm,
            allow_open_board=allow_open_board,
        )
        if refusal := _guard_file_based_board_edit("functional grouping", payload.allow_open_board):
            return refusal

        board_file = _get_pcb_file_for_sync()
        board_content = _normalize_board_content(
            board_file.read_text(encoding="utf-8", errors="ignore")
        )
        existing = _parse_board_footprint_blocks(board_content)
        occupied = _collect_occupied_boxes(existing)
        refs_in_groups = {
            reference for group_refs in payload.groups.values() for reference in group_refs
        }
        occupied = [box for box in occupied if True]
        replacements: dict[str, str] = {}
        missing_refs: list[str] = []
        moved = 0

        occupied = _collect_occupied_boxes(existing, exclude_refs=refs_in_groups)
        for group_index, (_group_name, references) in enumerate(payload.groups.items()):
            group_x_mm = payload.origin_x_mm + (group_index * payload.group_spacing_mm)
            cursor_y_mm = payload.origin_y_mm
            for reference in references:
                entry = existing.get(reference)
                if entry is None:
                    missing_refs.append(reference)
                    continue
                width_mm = float(entry["width_mm"])
                height_mm = float(entry["height_mm"])
                resolved_x_mm, resolved_y_mm = _find_open_position(
                    group_x_mm,
                    cursor_y_mm,
                    width_mm,
                    height_mm,
                    SyncPcbFromSchematicInput(grid_mm=payload.grid_mm),
                    occupied,
                )
                replacements[reference] = _replace_root_at(
                    str(entry["block"]),
                    x_mm=resolved_x_mm,
                    y_mm=resolved_y_mm,
                    rotation=int(entry["rotation"]),
                )
                occupied.append(
                    {
                        "x_mm": resolved_x_mm,
                        "y_mm": resolved_y_mm,
                        "width_mm": width_mm,
                        "height_mm": height_mm,
                    }
                )
                cursor_y_mm = resolved_y_mm + height_mm + payload.item_spacing_mm
                moved += 1

        if not replacements:
            return "No existing footprints were moved by functional grouping."

        _transactional_board_write(lambda current: _replace_board_blocks(current, replacements, []))
        lines = [
            f"Functional groups placed: {len(payload.groups)}",
            f"Footprints moved: {moved}",
        ]
        if missing_refs:
            lines.append("Missing references:")
            lines.extend(f"- {reference}" for reference in missing_refs[:20])
        lines.append(_finalize_file_based_board_edit(payload.allow_open_board))
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def pcb_align_footprints(
        refs: list[str],
        axis: str = "x",
        spacing_mm: float = 2.54,
        allow_open_board: bool = False,
    ) -> str:
        """Arrange selected footprints into a straight row or column."""
        payload = AlignFootprintsInput(
            refs=refs,
            axis=axis,
            spacing_mm=spacing_mm,
            allow_open_board=allow_open_board,
        )
        if refusal := _guard_file_based_board_edit("footprint alignment", payload.allow_open_board):
            return refusal

        board_file = _get_pcb_file_for_sync()
        board_content = _normalize_board_content(
            board_file.read_text(encoding="utf-8", errors="ignore")
        )
        existing = _parse_board_footprint_blocks(board_content)
        ordered_refs = [reference for reference in payload.refs if reference in existing]
        missing_refs = [reference for reference in payload.refs if reference not in existing]
        if len(ordered_refs) < 2:
            return "At least two existing footprint references are required for alignment."

        anchor = existing[ordered_refs[0]]
        anchor_x_mm = float(anchor["x_mm"] or 0.0)
        anchor_y_mm = float(anchor["y_mm"] or 0.0)
        replacements: dict[str, str] = {}

        for index, reference in enumerate(ordered_refs):
            entry = existing[reference]
            x_mm = (
                anchor_x_mm + (index * payload.spacing_mm) if payload.axis == "x" else anchor_x_mm
            )
            y_mm = (
                anchor_y_mm if payload.axis == "x" else anchor_y_mm + (index * payload.spacing_mm)
            )
            replacements[reference] = _replace_root_at(
                str(entry["block"]),
                x_mm=x_mm,
                y_mm=y_mm,
                rotation=int(entry["rotation"]),
            )

        _transactional_board_write(lambda current: _replace_board_blocks(current, replacements, []))
        lines = [
            f"Aligned {len(ordered_refs)} footprint(s) along the {payload.axis}-axis.",
            f"Origin spacing: {payload.spacing_mm:.2f} mm",
        ]
        if missing_refs:
            lines.append("Missing references:")
            lines.extend(f"- {reference}" for reference in missing_refs[:20])
        lines.append(_finalize_file_based_board_edit(payload.allow_open_board))
        return "\n".join(lines)

    @mcp.tool()
    @requires_kicad_running
    def pcb_set_keepout_zone(
        x_mm: float,
        y_mm: float,
        w_mm: float,
        h_mm: float,
        rules: list[str] | None = None,
        name: str = "MCP_Keepout",
    ) -> str:
        """Add a rectangular PCB keepout / rule area to the active board."""
        payload = KeepoutZoneInput(
            x_mm=x_mm,
            y_mm=y_mm,
            w_mm=w_mm,
            h_mm=h_mm,
            rules=rules or ["no_tracks", "no_vias", "no_copper"],
            name=name,
        )
        zone = Zone()
        zone.type = ZoneType.ZT_RULE_AREA
        zone.name = payload.name
        board = get_board()
        copper_layers = [
            layer for layer in board.get_enabled_layers() if "_Cu" in BoardLayer.Name(layer)
        ]
        zone.layers = copper_layers or [BoardLayer.BL_F_Cu, BoardLayer.BL_B_Cu]
        zone.outline = _rectangle_polygon(
            payload.x_mm,
            payload.y_mm,
            payload.w_mm,
            payload.h_mm,
        )
        zone.proto.rule_area_settings.keepout_tracks = "no_tracks" in payload.rules
        zone.proto.rule_area_settings.keepout_vias = "no_vias" in payload.rules
        zone.proto.rule_area_settings.keepout_copper = "no_copper" in payload.rules
        zone.proto.rule_area_settings.keepout_pads = "no_pads" in payload.rules
        zone.proto.rule_area_settings.keepout_footprints = "no_footprints" in payload.rules
        with board_transaction() as current_board:
            current_board.create_items([zone])
        return (
            f"Added keepout zone '{payload.name}' on {len(zone.layers)} copper layer(s) "
            f"with rules: {', '.join(payload.rules)}."
        )

    @mcp.tool()
    @headless_compatible
    def pcb_add_mounting_holes(
        diameter_mm: float = 3.2,
        clearance_mm: float = 6.35,
        pattern: str = "corners",
        margin_mm: float = 3.0,
        allow_open_board: bool = False,
    ) -> str:
        """Append standard mounting-hole footprints around the current board frame."""
        payload = AddMountingHolesInput(
            diameter_mm=diameter_mm,
            clearance_mm=clearance_mm,
            pattern=pattern,
            margin_mm=margin_mm,
            allow_open_board=allow_open_board,
        )
        if refusal := _guard_file_based_board_edit(
            "mounting-hole insertion",
            payload.allow_open_board,
        ):
            return refusal

        board_file = _get_pcb_file_for_sync()
        board_content = _normalize_board_content(
            board_file.read_text(encoding="utf-8", errors="ignore")
        )
        existing = _parse_board_footprint_blocks(board_content)
        min_x_mm, min_y_mm, max_x_mm, max_y_mm = _board_frame_mm(board_content, existing)
        positions = [
            (min_x_mm + payload.margin_mm, min_y_mm + payload.margin_mm),
            (max_x_mm - payload.margin_mm, min_y_mm + payload.margin_mm),
            (min_x_mm + payload.margin_mm, max_y_mm - payload.margin_mm),
            (max_x_mm - payload.margin_mm, max_y_mm - payload.margin_mm),
        ]
        if payload.pattern == "top_bottom":
            positions = [
                ((min_x_mm + max_x_mm) / 2, min_y_mm + payload.margin_mm),
                ((min_x_mm + max_x_mm) / 2, max_y_mm - payload.margin_mm),
            ]
        elif payload.pattern == "left_right":
            positions = [
                (min_x_mm + payload.margin_mm, (min_y_mm + max_y_mm) / 2),
                (max_x_mm - payload.margin_mm, (min_y_mm + max_y_mm) / 2),
            ]
        existing_refs = set(existing)
        additions: list[str] = []
        added_refs: list[str] = []
        for x_mm, y_mm in positions:
            reference = _next_reference(existing_refs, "H")
            added_refs.append(reference)
            additions.append(
                _mounting_hole_block(
                    reference,
                    x_mm,
                    y_mm,
                    payload.diameter_mm,
                    payload.clearance_mm,
                )
            )

        _transactional_board_write(lambda current: _replace_board_blocks(current, {}, additions))
        return "\n".join(
            [
                f"Added {len(additions)} mounting hole(s): {', '.join(added_refs)}.",
                _finalize_file_based_board_edit(payload.allow_open_board),
            ]
        )

    @mcp.tool()
    @headless_compatible
    def pcb_add_fiducial_marks(
        count: int = 3,
        diameter_mm: float = 1.0,
        margin_mm: float = 2.0,
        allow_open_board: bool = False,
    ) -> str:
        """Append simple fiducial footprints near the board corners."""
        payload = AddFiducialMarksInput(
            count=count,
            diameter_mm=diameter_mm,
            margin_mm=margin_mm,
            allow_open_board=allow_open_board,
        )
        if refusal := _guard_file_based_board_edit("fiducial insertion", payload.allow_open_board):
            return refusal

        board_file = _get_pcb_file_for_sync()
        board_content = _normalize_board_content(
            board_file.read_text(encoding="utf-8", errors="ignore")
        )
        existing = _parse_board_footprint_blocks(board_content)
        min_x_mm, min_y_mm, max_x_mm, max_y_mm = _board_frame_mm(board_content, existing)
        candidate_positions = [
            (min_x_mm + payload.margin_mm, min_y_mm + payload.margin_mm),
            (max_x_mm - payload.margin_mm, min_y_mm + payload.margin_mm),
            (min_x_mm + payload.margin_mm, max_y_mm - payload.margin_mm),
            (max_x_mm - payload.margin_mm, max_y_mm - payload.margin_mm),
            ((min_x_mm + max_x_mm) / 2, min_y_mm + payload.margin_mm),
            ((min_x_mm + max_x_mm) / 2, max_y_mm - payload.margin_mm),
        ]
        existing_refs = set(existing)
        additions: list[str] = []
        added_refs: list[str] = []
        for x_mm, y_mm in candidate_positions[: payload.count]:
            reference = _next_reference(existing_refs, "FID")
            added_refs.append(reference)
            additions.append(_fiducial_block(reference, x_mm, y_mm, payload.diameter_mm))

        _transactional_board_write(lambda current: _replace_board_blocks(current, {}, additions))
        return "\n".join(
            [
                f"Added {len(additions)} fiducial mark(s): {', '.join(added_refs)}.",
                _finalize_file_based_board_edit(payload.allow_open_board),
            ]
        )

    @mcp.tool()
    @requires_kicad_running
    def pcb_add_teardrops(
        net_classes: list[str] | None = None,
        length_ratio: float = 1.4,
        width_ratio: float = 1.2,
        max_count: int = 100,
    ) -> str:
        """Create small copper helper zones at simple pad-to-track junctions."""
        payload = AddTeardropsInput(
            net_classes=net_classes,
            length_ratio=length_ratio,
            width_ratio=width_ratio,
            max_count=max_count,
        )
        if not _board_is_open():
            return (
                "Teardrop generation requires an active PCB opened through KiCad IPC. "
                "Open the board in KiCad and rerun this tool."
            )

        board = get_board()
        pads = cast(list[_PadLike], board.get_pads())
        tracks = cast(list[Track], board.get_tracks())
        zones: list[Zone] = []
        created = 0

        for pad in pads:
            net_name = str(getattr(getattr(pad, "net", None), "name", ""))
            net_class_name = str(
                getattr(getattr(pad, "net", None), "netclass_name", "")
                or getattr(getattr(pad, "net", None), "class_name", "")
                or net_name
            )
            if payload.net_classes and net_class_name not in payload.net_classes:
                continue
            pad_x_nm = _coord_nm(pad.position, "x")
            pad_y_nm = _coord_nm(pad.position, "y")
            size_vector = getattr(pad, "size", Vector2.from_xy_mm(1.0, 1.0))
            pad_radius_nm = max(_coord_nm(size_vector, "x"), _coord_nm(size_vector, "y")) / 2

            for track in tracks:
                track_net_name = str(getattr(getattr(track, "net", None), "name", ""))
                if track_net_name != net_name:
                    continue
                start_dx = _coord_nm(track.start, "x") - pad_x_nm
                start_dy = _coord_nm(track.start, "y") - pad_y_nm
                end_dx = _coord_nm(track.end, "x") - pad_x_nm
                end_dy = _coord_nm(track.end, "y") - pad_y_nm
                start_distance = math.hypot(start_dx, start_dy)
                end_distance = math.hypot(end_dx, end_dy)
                tolerance_nm = max(pad_radius_nm * 1.2, track.width * 2)

                if start_distance > tolerance_nm and end_distance > tolerance_nm:
                    continue

                near_x_nm, near_y_nm, far_x_nm, far_y_nm = (
                    (
                        _coord_nm(track.start, "x"),
                        _coord_nm(track.start, "y"),
                        _coord_nm(track.end, "x"),
                        _coord_nm(track.end, "y"),
                    )
                    if start_distance <= end_distance
                    else (
                        _coord_nm(track.end, "x"),
                        _coord_nm(track.end, "y"),
                        _coord_nm(track.start, "x"),
                        _coord_nm(track.start, "y"),
                    )
                )
                vector_x_nm = far_x_nm - pad_x_nm
                vector_y_nm = far_y_nm - pad_y_nm
                vector_length_nm = math.hypot(vector_x_nm, vector_y_nm)
                if vector_length_nm == 0:
                    continue
                unit_x = vector_x_nm / vector_length_nm
                unit_y = vector_y_nm / vector_length_nm
                perp_x = -unit_y
                perp_y = unit_x
                base_half_nm = max((track.width * payload.width_ratio) / 2, track.width / 2)
                tip_distance_nm = min(
                    pad_radius_nm * payload.length_ratio,
                    vector_length_nm * 0.9,
                )
                base_center_x_nm = pad_x_nm + int(round(unit_x * (pad_radius_nm * 0.6)))
                base_center_y_nm = pad_y_nm + int(round(unit_y * (pad_radius_nm * 0.6)))
                tip_center_x_nm = pad_x_nm + int(round(unit_x * tip_distance_nm))
                tip_center_y_nm = pad_y_nm + int(round(unit_y * tip_distance_nm))
                polygon = _polygon_from_points(
                    [
                        (
                            int(round(base_center_x_nm + (perp_x * pad_radius_nm * 0.7))),
                            int(round(base_center_y_nm + (perp_y * pad_radius_nm * 0.7))),
                        ),
                        (
                            int(round(tip_center_x_nm + (perp_x * base_half_nm))),
                            int(round(tip_center_y_nm + (perp_y * base_half_nm))),
                        ),
                        (
                            int(round(tip_center_x_nm - (perp_x * base_half_nm))),
                            int(round(tip_center_y_nm - (perp_y * base_half_nm))),
                        ),
                        (
                            int(round(base_center_x_nm - (perp_x * pad_radius_nm * 0.7))),
                            int(round(base_center_y_nm - (perp_y * pad_radius_nm * 0.7))),
                        ),
                    ]
                )
                zone = Zone()
                zone.name = (
                    f"MCP_Teardrop_{getattr(pad.parent.reference_field.text, 'value', 'PAD')}"
                )
                zone.layers = [track.layer]
                zone.net = track.net if hasattr(track.net, "proto") else _find_net(track_net_name)
                zone.outline = polygon
                zones.append(zone)
                created += 1
                if created >= payload.max_count:
                    break
            if created >= payload.max_count:
                break

        if not zones:
            return "No simple pad-to-track teardrop candidates were found on the active board."

        with board_transaction() as current_board:
            current_board.create_items(zones)
            current_board.refill_zones(block=True, max_poll_seconds=60.0)
        return f"Added {len(zones)} teardrop helper zone(s) to the active board."
