"""Schematic tools with parser-based reads and transactional writes."""

from __future__ import annotations

import math
import re
import uuid
from collections.abc import Callable
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..connection import KiCadConnectionError, get_kicad
from ..models.schematic import (
    AddBusInput,
    AddBusWireEntryInput,
    AddLabelInput,
    AddNoConnectInput,
    AddSymbolInput,
    AddWireInput,
    AnnotateInput,
    PowerSymbolInput,
    UpdatePropertiesInput,
)


def new_uuid() -> str:
    """Create a KiCad UUID string."""
    return str(uuid.uuid4())


def parse_schematic_file(sch_file: Path) -> dict[str, Any]:
    """Parse a schematic file into coarse structures."""
    content = sch_file.read_text(encoding="utf-8", errors="ignore")
    result: dict[str, Any] = {
        "uuid": _extract_uuid(content),
        "symbols": _extract_symbols(content),
        "wires": _extract_wires(content),
        "labels": _extract_labels(content),
        "buses": _extract_buses(content),
        "power_symbols": [],
    }

    regular_symbols = []
    for symbol in result["symbols"]:
        if symbol["lib_id"].startswith("power:"):
            result["power_symbols"].append(symbol)
        else:
            regular_symbols.append(symbol)
    result["symbols"] = regular_symbols
    return result


def _extract_uuid(content: str) -> str:
    match = re.search(r'\(kicad_sch[^(]*\(uuid\s+"([^"]+)"', content)
    return match.group(1) if match else ""


def _extract_block(content: str, start: int) -> tuple[str, int]:
    depth = 0
    for index, char in enumerate(content[start:]):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return content[start : start + index + 1], index + 1
    return "", 0


def _extract_symbols(content: str) -> list[dict[str, Any]]:
    symbols: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(content):
        if content[cursor:].startswith("(symbol"):
            block, length = _extract_block(content, cursor)
            if block:
                parsed = _parse_symbol_block(block)
                if parsed is not None:
                    symbols.append(parsed)
                cursor += length
                continue
        cursor += 1
    return symbols


def _parse_symbol_block(block: str) -> dict[str, Any] | None:
    lib_id_match = re.search(r'\(lib_id\s+"([^"]+)"\)', block)
    if lib_id_match is None:
        return None
    at_match = re.search(r"\(at\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\)", block)
    ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
    value_match = re.search(r'\(property\s+"Value"\s+"([^"]+)"', block)
    footprint_match = re.search(r'\(property\s+"Footprint"\s+"([^"]*)"', block)
    return {
        "lib_id": lib_id_match.group(1),
        "reference": ref_match.group(1) if ref_match else "?",
        "value": value_match.group(1) if value_match else "?",
        "footprint": footprint_match.group(1) if footprint_match else "",
        "x": float(at_match.group(1)) if at_match else 0.0,
        "y": float(at_match.group(2)) if at_match else 0.0,
        "rotation": int(at_match.group(3)) if at_match else 0,
    }


def _extract_wires(content: str) -> list[dict[str, float]]:
    wires: list[dict[str, float]] = []
    for match in re.finditer(
        r"\(wire\s+\(pts\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\)",
        content,
    ):
        wires.append(
            {
                "x1": float(match.group(1)),
                "y1": float(match.group(2)),
                "x2": float(match.group(3)),
                "y2": float(match.group(4)),
            }
        )
    return wires


def _extract_buses(content: str) -> list[dict[str, float]]:
    buses: list[dict[str, float]] = []
    for match in re.finditer(
        r"\(bus\s+\(pts\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\s+\(xy\s+([-\d.]+)\s+([-\d.]+)\)\)",
        content,
    ):
        buses.append(
            {
                "x1": float(match.group(1)),
                "y1": float(match.group(2)),
                "x2": float(match.group(3)),
                "y2": float(match.group(4)),
            }
        )
    return buses


def _extract_labels(content: str) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    for match in re.finditer(
        r'\((?:label|global_label)\s+"([^"]+)"\s+(?:\(shape\s+\w+\)\s+)?\(at\s+([-\d.]+)\s+([-\d.]+)\s+(\d+)\)',
        content,
    ):
        labels.append(
            {
                "name": match.group(1),
                "x": float(match.group(2)),
                "y": float(match.group(3)),
                "rotation": int(match.group(4)),
            }
        )
    return labels


def _get_schematic_file() -> Path:
    cfg = get_config()
    if cfg.sch_file is None or not cfg.sch_file.exists():
        raise ValueError(
            "No schematic file is configured. Call kicad_set_project() or set KICAD_MCP_SCH_FILE."
        )
    return cfg.sch_file


def _get_symbol_library_dir() -> Path:
    cfg = get_config()
    if cfg.symbol_library_dir is None or not cfg.symbol_library_dir.exists():
        raise FileNotFoundError("No KiCad symbol library directory is configured.")
    return cfg.symbol_library_dir


def rotate_point(x: float, y: float, angle_deg: float) -> tuple[float, float]:
    """Rotate a point around the origin."""
    radians = math.radians(angle_deg)
    cos_a = math.cos(radians)
    sin_a = math.sin(radians)
    return (round(x * cos_a - y * sin_a, 4), round(x * sin_a + y * cos_a, 4))


def load_lib_symbol(library: str, symbol_name: str) -> str | None:
    """Load a symbol definition from a KiCad symbol library."""
    sym_file = _get_symbol_library_dir() / f"{library}.kicad_sym"
    if not sym_file.exists():
        return None

    content = sym_file.read_text(encoding="utf-8", errors="ignore")
    block = _find_symbol_block(content, symbol_name)
    if block is None:
        return None

    return block.replace(f'(symbol "{symbol_name}"', f'(symbol "{library}:{symbol_name}"', 1)


def _find_symbol_block(content: str, symbol_name: str) -> str | None:
    """Extract a single symbol block from a KiCad symbol library file."""
    start_marker = f'(symbol "{symbol_name}"'
    start = content.find(start_marker)
    if start == -1:
        return None

    depth = 0
    for index, char in enumerate(content[start:]):
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return content[start : start + index + 1]
    return None


def get_pin_positions(
    library: str,
    symbol_name: str,
    sym_x: float,
    sym_y: float,
    rotation: int = 0,
) -> dict[str, tuple[float, float]]:
    """Calculate absolute pin tip positions for a symbol placement."""
    sym_file = _get_symbol_library_dir() / f"{library}.kicad_sym"
    if not sym_file.exists():
        return {}

    content = sym_file.read_text(encoding="utf-8", errors="ignore")
    block = _find_symbol_block(content, symbol_name)
    if block is None:
        return {}

    pins: dict[str, tuple[float, float]] = {}
    for match in re.finditer(
        r'\(pin\s+\w+\s+\w+\s+\(at\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\)\s+\(length\s+([-\d.]+)\).*?\(number\s+"([^"]+)"',
        block,
        re.DOTALL,
    ):
        px = float(match.group(1))
        py = float(match.group(2))
        pin_angle = float(match.group(3))
        pin_length = float(match.group(4))
        pin_number = match.group(5)

        tip_x = px + pin_length * math.cos(math.radians(pin_angle))
        tip_y = py + pin_length * math.sin(math.radians(pin_angle))
        rx, ry = rotate_point(tip_x, -tip_y, rotation)
        pins[pin_number] = (round(sym_x + rx, 4), round(sym_y - ry, 4))
    return pins


def wire_block(x1: float, y1: float, x2: float, y2: float, kind: str = "wire") -> str:
    """Create a schematic wire or bus block."""
    return (
        f"\t({kind}\n"
        f"\t\t(pts (xy {x1} {y1}) (xy {x2} {y2}))\n"
        "\t\t(stroke (width 0) (type solid))\n"
        f'\t\t(uuid "{new_uuid()}")\n'
        "\t)"
    )


def label_block(
    name: str, x: float, y: float, rotation: int = 0, global_label: bool = False
) -> str:
    """Create a schematic label block."""
    kind = "global_label" if global_label else "label"
    shape_line = "\t\t(shape bidirectional)\n" if global_label else ""
    return (
        f'\t({kind} "{name}"\n'
        f"{shape_line}"
        f"\t\t(at {x} {y} {rotation})\n"
        "\t\t(effects (font (size 1.524 1.524)))\n"
        f'\t\t(uuid "{new_uuid()}")\n'
        "\t)"
    )


def no_connect_block(x: float, y: float) -> str:
    """Create a no-connect marker."""
    return f'\t(no_connect (at {x} {y}) (uuid "{new_uuid()}"))'


def bus_entry_block(x: float, y: float, direction: str) -> str:
    """Create a bus wire entry block."""
    offset_map = {
        "up_right": (2.54, -2.54),
        "down_right": (2.54, 2.54),
        "up_left": (-2.54, -2.54),
        "down_left": (-2.54, 2.54),
    }
    dx, dy = offset_map[direction]
    return (
        "\t(bus_entry\n"
        f"\t\t(at {x} {y})\n"
        f"\t\t(size {dx} {dy})\n"
        "\t\t(stroke (width 0) (type solid))\n"
        f'\t\t(uuid "{new_uuid()}")\n'
        "\t)"
    )


def place_symbol_block(
    lib_id: str,
    x: float,
    y: float,
    reference: str,
    value: str,
    footprint: str = "",
    rotation: int = 0,
    project_name: str = "KiCadMCP",
    root_uuid: str = "",
) -> str:
    """Build a schematic symbol instance block."""
    symbol_uuid = new_uuid()
    root = root_uuid or new_uuid()
    return (
        "\t(symbol\n"
        f'\t\t(lib_id "{lib_id}")\n'
        f"\t\t(at {x} {y} {rotation})\n"
        "\t\t(unit 1)\n"
        "\t\t(exclude_from_sim no)\n"
        "\t\t(in_bom yes)\n"
        "\t\t(on_board yes)\n"
        "\t\t(dnp no)\n"
        f'\t\t(uuid "{symbol_uuid}")\n'
        f'\t\t(property "Reference" "{reference}"\n'
        f"\t\t\t(at {x + 2.032} {y} {rotation})\n"
        "\t\t\t(effects (font (size 1.27 1.27)))\n"
        "\t\t)\n"
        f'\t\t(property "Value" "{value}"\n'
        f"\t\t\t(at {x} {y} {rotation})\n"
        "\t\t\t(effects (font (size 1.27 1.27)))\n"
        "\t\t)\n"
        f'\t\t(property "Footprint" "{footprint}"\n'
        f"\t\t\t(at {x} {y} {rotation})\n"
        "\t\t\t(effects (font (size 1.27 1.27)) (hide yes))\n"
        "\t\t)\n"
        '\t\t(property "Datasheet" "~"\n'
        f"\t\t\t(at {x} {y} 0)\n"
        "\t\t\t(effects (font (size 1.27 1.27)) (hide yes))\n"
        "\t\t)\n"
        "\t\t(instances\n"
        f'\t\t\t(project "{project_name}"\n'
        f'\t\t\t\t(path "/{root}"\n'
        f'\t\t\t\t\t(reference "{reference}") (unit 1)\n'
        "\t\t\t\t)\n"
        "\t\t\t)\n"
        "\t\t)\n"
        "\t)"
    )


def _append_before_sheet_instances(content: str, block: str) -> str:
    marker = "\t(sheet_instances"
    if marker in content:
        return content.replace(marker, f"{block}\n{marker}", 1)
    return content.rstrip().rstrip(")") + f"\n{block}\n)\n"


def _validate_schematic_text(content: str) -> None:
    if content.count("(") != content.count(")"):
        raise ValueError("Refusing to write an invalid schematic with unbalanced parentheses.")


def _find_placed_symbol_block(
    content: str, reference: str
) -> tuple[str, int, int, dict[str, Any]] | None:
    """Locate a placed symbol instance block by reference designator."""
    cursor = 0
    while cursor < len(content):
        if content[cursor:].startswith("(symbol"):
            block, length = _extract_block(content, cursor)
            if block:
                parsed = _parse_symbol_block(block)
                if parsed is not None and parsed["reference"] == reference:
                    return block, cursor, cursor + length, parsed
                cursor += length
                continue
        cursor += 1
    return None


def transactional_write(mutator: Callable[[str], str]) -> str:
    """Read, mutate, validate, and atomically rewrite the active schematic."""
    sch_file = _get_schematic_file()
    current = sch_file.read_text(encoding="utf-8")
    updated = mutator(current)
    _validate_schematic_text(updated)
    with NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=sch_file.parent) as handle:
        handle.write(updated)
        temp_path = Path(handle.name)
    temp_path.replace(sch_file)
    return str(sch_file)


def update_symbol_property(reference: str, field: str, value: str) -> str:
    """Update a symbol property in the active schematic."""
    payload = UpdatePropertiesInput(reference=reference, field=field, value=value)

    def mutator(current: str) -> str:
        pattern = re.compile(
            rf'(\(property\s+"{re.escape(payload.field)}"\s+")([^"]*)(")',
            re.DOTALL,
        )
        match = _find_placed_symbol_block(current, payload.reference)
        if match is None:
            raise ValueError(f"Reference '{payload.reference}' was not found in the schematic.")
        block, start, end, parsed = match
        if pattern.search(block):
            new_block = pattern.sub(
                lambda match: f"{match.group(1)}{payload.value}{match.group(3)}",
                block,
                count=1,
            )
        else:
            insert_point = block.rfind("\t\t(instances")
            if insert_point == -1:
                insert_point = block.rfind("\n\t)")
            if insert_point == -1:
                raise ValueError(f"Could not update '{payload.reference}' in the schematic.")
            x = parsed["x"]
            y = parsed["y"]
            rotation = parsed["rotation"]
            property_block = (
                f'\t\t(property "{payload.field}" "{payload.value}"\n'
                f"\t\t\t(at {x} {y} {rotation})\n"
                "\t\t\t(effects (font (size 1.27 1.27)) (hide yes))\n"
                "\t\t)\n"
            )
            new_block = block[:insert_point] + property_block + block[insert_point:]
        return current[:start] + new_block + current[end:]

    transactional_write(mutator)
    return f"Updated {payload.reference}.{payload.field}."


def _reload_schematic() -> str:
    try:
        from kipy.proto.common.commands import editor_commands_pb2
        from kipy.proto.common.types.base_types_pb2 import DocumentType
    except Exception:
        return "The schematic was updated. Reload it manually in KiCad if needed."

    try:
        kicad = get_kicad()
    except KiCadConnectionError:
        return "The schematic was updated. KiCad is not connected, so reload it manually."

    try:
        documents = kicad.get_open_documents(DocumentType.DOCTYPE_SCHEMATIC)
        if not documents:
            return "The schematic was updated. No open KiCad schematic was found to reload."
        command = editor_commands_pb2.RevertDocument()
        command.document.CopyFrom(documents[0])
        kicad._client.send(command, type(None).__mro__[0])
        return "The schematic was updated and KiCad was asked to reload it."
    except Exception:
        return "The schematic was updated. Reload it manually in KiCad if needed."


def register(mcp: FastMCP) -> None:
    """Register schematic tools."""

    @mcp.tool()
    def sch_get_symbols() -> str:
        """List all schematic symbols."""
        data = parse_schematic_file(_get_schematic_file())
        symbols = data["symbols"] + data["power_symbols"]
        if not symbols:
            return "The active schematic contains no symbols."

        lines = [f"Symbols ({len(symbols)} total):"]
        for symbol in data["symbols"]:
            suffix = f" footprint={symbol['footprint']}" if symbol["footprint"] else ""
            lines.append(
                f"- {symbol['reference']} {symbol['value']} {symbol['lib_id']} @ "
                f"({symbol['x']:.2f}, {symbol['y']:.2f}) rot={symbol['rotation']}{suffix}"
            )
        if data["power_symbols"]:
            lines.append("Power symbols:")
            for symbol in data["power_symbols"]:
                lines.append(
                    f"- {symbol['reference']} {symbol['value']} @ "
                    f"({symbol['x']:.2f}, {symbol['y']:.2f})"
                )
        return "\n".join(lines)

    @mcp.tool()
    def sch_get_wires() -> str:
        """List all wires in the schematic."""
        wires = parse_schematic_file(_get_schematic_file())["wires"]
        if not wires:
            return "The active schematic contains no wires."
        lines = [f"Wires ({len(wires)} total):"]
        lines.extend(
            f"- ({wire['x1']}, {wire['y1']}) -> ({wire['x2']}, {wire['y2']})" for wire in wires
        )
        return "\n".join(lines)

    @mcp.tool()
    def sch_get_labels() -> str:
        """List all labels in the schematic."""
        labels = parse_schematic_file(_get_schematic_file())["labels"]
        if not labels:
            return "The active schematic contains no labels."
        lines = [f"Labels ({len(labels)} total):"]
        lines.extend(
            f"- {label['name']} @ ({label['x']}, {label['y']}) rot={label['rotation']}"
            for label in labels
        )
        return "\n".join(lines)

    @mcp.tool()
    def sch_get_net_names() -> str:
        """List unique net names derived from labels."""
        labels = parse_schematic_file(_get_schematic_file())["labels"]
        names = sorted({label["name"] for label in labels})
        if not names:
            return "No named nets were found in the schematic."
        return "Named nets:\n" + "\n".join(f"- {name}" for name in names)

    @mcp.tool()
    def sch_add_symbol(
        library: str,
        symbol_name: str,
        x_mm: float,
        y_mm: float,
        reference: str,
        value: str,
        footprint: str = "",
        rotation: int = 0,
    ) -> str:
        """Add a schematic symbol."""
        payload = AddSymbolInput(
            library=library,
            symbol_name=symbol_name,
            x_mm=x_mm,
            y_mm=y_mm,
            reference=reference,
            value=value,
            footprint=footprint,
            rotation=rotation,
        )
        lib_def = load_lib_symbol(payload.library, payload.symbol_name)
        if lib_def is None:
            return f"Symbol '{payload.library}:{payload.symbol_name}' was not found."

        sch_file = _get_schematic_file()
        root_uuid = parse_schematic_file(sch_file)["uuid"] or new_uuid()
        cfg = get_config()
        project_name = cfg.project_file.stem if cfg.project_file is not None else "KiCadMCP"
        lib_id = f"{payload.library}:{payload.symbol_name}"

        def mutator(current: str) -> str:
            updated = current
            if f'(symbol "{lib_id}"' not in updated:
                if "(lib_symbols)" in updated:
                    updated = updated.replace("(lib_symbols)", f"(lib_symbols\n\t{lib_def}\n\t)", 1)
                else:
                    updated = updated.replace(
                        "\t(lib_symbols\n", f"\t(lib_symbols\n\t{lib_def}\n", 1
                    )
            block = place_symbol_block(
                lib_id=lib_id,
                x=payload.x_mm,
                y=payload.y_mm,
                reference=payload.reference,
                value=payload.value,
                footprint=payload.footprint,
                rotation=payload.rotation,
                project_name=project_name,
                root_uuid=root_uuid,
            )
            return _append_before_sheet_instances(updated, block)

        transactional_write(mutator)
        return _reload_schematic()

    @mcp.tool()
    def sch_add_wire(x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float) -> str:
        """Add a schematic wire."""
        payload = AddWireInput(x1_mm=x1_mm, y1_mm=y1_mm, x2_mm=x2_mm, y2_mm=y2_mm)
        transactional_write(
            lambda current: _append_before_sheet_instances(
                current,
                wire_block(payload.x1_mm, payload.y1_mm, payload.x2_mm, payload.y2_mm),
            )
        )
        return _reload_schematic()

    @mcp.tool()
    def sch_add_label(name: str, x_mm: float, y_mm: float, rotation: int = 0) -> str:
        """Add a schematic label."""
        payload = AddLabelInput(name=name, x_mm=x_mm, y_mm=y_mm, rotation=rotation)
        transactional_write(
            lambda current: _append_before_sheet_instances(
                current,
                label_block(payload.name, payload.x_mm, payload.y_mm, payload.rotation),
            )
        )
        return _reload_schematic()

    @mcp.tool()
    def sch_add_power_symbol(name: str, x_mm: float, y_mm: float, rotation: int = 0) -> str:
        """Add a power symbol from the standard power library."""
        return str(
            sch_add_symbol("power", name, x_mm, y_mm, f"#PWR{new_uuid()[:4]}", name, "", rotation)
        )

    @mcp.tool()
    def sch_add_bus(x1_mm: float, y1_mm: float, x2_mm: float, y2_mm: float) -> str:
        """Add a schematic bus."""
        payload = AddBusInput(x1_mm=x1_mm, y1_mm=y1_mm, x2_mm=x2_mm, y2_mm=y2_mm)
        transactional_write(
            lambda current: _append_before_sheet_instances(
                current,
                wire_block(payload.x1_mm, payload.y1_mm, payload.x2_mm, payload.y2_mm, "bus"),
            )
        )
        return _reload_schematic()

    @mcp.tool()
    def sch_add_bus_wire_entry(x_mm: float, y_mm: float, direction: str = "up_right") -> str:
        """Add a bus wire entry marker."""
        payload = AddBusWireEntryInput(x_mm=x_mm, y_mm=y_mm, direction=direction)
        transactional_write(
            lambda current: _append_before_sheet_instances(
                current,
                bus_entry_block(payload.x_mm, payload.y_mm, payload.direction),
            )
        )
        return _reload_schematic()

    @mcp.tool()
    def sch_add_no_connect(x_mm: float, y_mm: float) -> str:
        """Add a no-connect marker."""
        payload = AddNoConnectInput(x_mm=x_mm, y_mm=y_mm)
        transactional_write(
            lambda current: _append_before_sheet_instances(
                current,
                no_connect_block(payload.x_mm, payload.y_mm),
            )
        )
        return _reload_schematic()

    @mcp.tool()
    def sch_update_properties(reference: str, field: str, value: str) -> str:
        """Update a property on a placed symbol."""
        result = update_symbol_property(reference, field, value)
        return f"{result}\n{_reload_schematic()}"

    @mcp.tool()
    def sch_build_circuit(
        symbols: list[dict[str, Any]] | None = None,
        wires: list[dict[str, Any]] | None = None,
        labels: list[dict[str, Any]] | None = None,
        power_symbols: list[dict[str, Any]] | None = None,
    ) -> str:
        """Build a schematic from structured symbol, wire, and label inputs."""
        # Validate ALL inputs upfront so validation errors surface immediately
        # with clear Pydantic messages — before any file I/O or dict key access.
        validated_symbols = [AddSymbolInput.model_validate(item) for item in (symbols or [])]
        validated_powers = [PowerSymbolInput.model_validate(item) for item in (power_symbols or [])]
        validated_wires = [AddWireInput.model_validate(item) for item in (wires or [])]
        validated_labels = [AddLabelInput.model_validate(item) for item in (labels or [])]

        root_uuid = new_uuid()
        cfg = get_config()
        project_name = cfg.project_file.stem if cfg.project_file is not None else "KiCadMCP"
        lib_defs_added: set[str] = set()
        lib_symbols_content: list[str] = []
        elements: list[str] = []

        # Load lib_symbols for regular symbols
        for sym in validated_symbols:
            key = f"{sym.library}:{sym.symbol_name}"
            if key not in lib_defs_added:
                lib_def = load_lib_symbol(sym.library, sym.symbol_name)
                if lib_def is not None:
                    lib_symbols_content.append(lib_def)
                lib_defs_added.add(key)

        # Load lib_symbols for power symbols
        for pwr in validated_powers:
            key = f"power:{pwr.name}"
            if key not in lib_defs_added:
                lib_def = load_lib_symbol("power", pwr.name)
                if lib_def is not None:
                    lib_symbols_content.append(lib_def)
                lib_defs_added.add(key)

        for sym in validated_symbols:
            elements.append(
                place_symbol_block(
                    lib_id=f"{sym.library}:{sym.symbol_name}",
                    x=sym.x_mm,
                    y=sym.y_mm,
                    reference=sym.reference,
                    value=sym.value,
                    footprint=sym.footprint,
                    rotation=sym.rotation,
                    project_name=project_name,
                    root_uuid=root_uuid,
                )
            )

        for index, pwr in enumerate(validated_powers, start=1):
            elements.append(
                place_symbol_block(
                    lib_id=f"power:{pwr.name}",
                    x=pwr.x,
                    y=pwr.y,
                    reference=f"#PWR{index:03d}",
                    value=pwr.name,
                    rotation=pwr.rotation,
                    project_name=project_name,
                    root_uuid=root_uuid,
                )
            )

        for wire in validated_wires:
            elements.append(wire_block(wire.x1_mm, wire.y1_mm, wire.x2_mm, wire.y2_mm))

        for lbl in validated_labels:
            elements.append(label_block(lbl.name, lbl.x_mm, lbl.y_mm, lbl.rotation))

        lib_section = "\t(lib_symbols\n"
        for symbol in lib_symbols_content:
            lib_section += "\n".join("\t" + line for line in symbol.splitlines()) + "\n"
        lib_section += "\t)"
        content = (
            "(kicad_sch\n"
            "\t(version 20250316)\n"
            '\t(generator "kicad-mcp-pro")\n'
            f'\t(uuid "{root_uuid}")\n'
            '\t(paper "A4")\n'
            f"{lib_section}\n"
            + "\n".join(elements)
            + (
                "\n\t(sheet_instances\n"
                '\t\t(path "/"\n'
                '\t\t\t(page "1")\n'
                "\t\t)\n"
                "\t)\n"
                "\t(embedded_fonts no)\n"
                ")\n"
            )
        )
        _validate_schematic_text(content)
        _get_schematic_file().write_text(content, encoding="utf-8")
        return _reload_schematic()

    @mcp.tool()
    def sch_get_pin_positions(
        library: str,
        symbol_name: str,
        x_mm: float,
        y_mm: float,
        rotation: int = 0,
    ) -> str:
        """Calculate absolute pin positions for a given symbol placement."""
        positions = get_pin_positions(library, symbol_name, x_mm, y_mm, rotation)
        if not positions:
            return f"Could not calculate pin positions for {library}:{symbol_name}."
        lines = [f"{library}:{symbol_name} @ ({x_mm}, {y_mm}) rot={rotation}:"]
        for pin, coords in sorted(positions.items()):
            lines.append(f"- Pin {pin}: ({coords[0]:.4f}, {coords[1]:.4f}) mm")
        return "\n".join(lines)

    @mcp.tool()
    def sch_check_power_flags() -> str:
        """Check whether common power nets appear to be flagged."""
        data = parse_schematic_file(_get_schematic_file())
        named_power = {
            label["name"]
            for label in data["labels"]
            if label["name"].upper() in {"GND", "VCC", "+3V3", "+5V", "+12V"}
        }
        power_symbols = {symbol["value"].upper() for symbol in data["power_symbols"]}
        missing = sorted(name for name in named_power if name.upper() not in power_symbols)
        if not missing:
            return "No obvious missing power flags were detected."
        return "Potential missing power flags:\n" + "\n".join(f"- {name}" for name in missing)

    @mcp.tool()
    def sch_annotate(start_number: int = 1, order: str = "alpha") -> str:
        """Renumber schematic references sequentially."""
        payload = AnnotateInput(start_number=start_number, order=order)
        data = parse_schematic_file(_get_schematic_file())
        symbols = list(data["symbols"])
        if payload.order == "sheet":
            symbols.sort(key=lambda item: (item["y"], item["x"]))
        else:
            symbols.sort(key=lambda item: item["reference"])

        counters: dict[str, int] = {}
        updates: list[tuple[str, str]] = []
        for symbol in symbols:
            prefix_match = re.match(r"([A-Za-z#]+)", symbol["reference"])
            prefix = prefix_match.group(1) if prefix_match else "U"
            counters.setdefault(prefix, payload.start_number)
            new_reference = f"{prefix}{counters[prefix]}"
            counters[prefix] += 1
            updates.append((symbol["reference"], new_reference))

        def mutator(current: str) -> str:
            updated = current
            for old_reference, new_reference in updates:
                updated = updated.replace(
                    f'(property "Reference" "{old_reference}"',
                    f'(property "Reference" "{new_reference}"',
                    1,
                )
            return updated

        transactional_write(mutator)
        return f"Annotated {len(updates)} symbol(s).\n{_reload_schematic()}"

    @mcp.tool()
    def sch_reload() -> str:
        """Ask KiCad to reload the active schematic."""
        return _reload_schematic()
