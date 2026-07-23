"""Pure orchestration for explicit destructive schematic edits."""

from __future__ import annotations

import re
from collections.abc import Callable, Hashable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

type ParsedRecord = Mapping[str, Any]
type SymbolMatch = tuple[str, int, int, ParsedRecord]
type ActiveSchematicFile = Callable[[], Path]
type ReadSchematicText = Callable[[Path], str]
type ExtractWires = Callable[[str], list[ParsedRecord]]
type WireIdMatches = Callable[[str, str], bool]
type WireSignature = Callable[[Any, Any, Any, Any], Hashable]
type ExtractBlock = Callable[[str, int], tuple[str, int]]
type ParseBlock = Callable[[str], ParsedRecord | None]
type FormatMm = Callable[[float], str]
type ReloadSchematic = Callable[[], str]
type FindPlacedSymbolBlocks = Callable[[str, str], list[SymbolMatch]]
type SymbolConnectionPoints = Callable[[ParsedRecord], set[tuple[float, float]]]
type CoordinateKey = Callable[[Any, Any], tuple[float, float]]
type SnapPoint = Callable[[float, float, bool], tuple[float, float]]
type SnapNotice = Callable[[tuple[float, ...], tuple[float, ...]], str]
type NormalizeLabelJustify = Callable[[str | None], str | None]
type SetLabelJustify = Callable[[str, str], str]


class TransactionalWrite(Protocol):
    """Transaction boundary used by schematic edit orchestration."""

    def __call__(
        self,
        mutator: Callable[[str], str],
        *,
        allow_node_loss: bool = False,
    ) -> str: ...


@dataclass(frozen=True)
class SchematicDestructiveEditService:
    """Perform deterministic destructive edits through injected dependencies."""

    active_schematic_file: ActiveSchematicFile
    read_schematic_text: ReadSchematicText
    extract_wires: ExtractWires
    wire_id_matches: WireIdMatches
    wire_signature: WireSignature
    extract_block: ExtractBlock
    parse_wire_block: ParseBlock
    format_mm: FormatMm
    transactional_write: TransactionalWrite
    reload_schematic: ReloadSchematic
    find_placed_symbol_blocks: FindPlacedSymbolBlocks
    symbol_connection_points: SymbolConnectionPoints
    parse_symbol_block: ParseBlock
    coordinate_key: CoordinateKey
    parse_label_block: ParseBlock
    snap_point: SnapPoint
    snap_notice: SnapNotice
    normalize_label_justify: NormalizeLabelJustify
    set_label_justify: SetLabelJustify

    def delete_wire(self, wire_id: str) -> str:
        """Delete one wire selected by UUID or unique UUID prefix."""
        schematic_file = self.active_schematic_file()
        current = self.read_schematic_text(schematic_file)
        matches = [
            wire
            for wire in self.extract_wires(current)
            if wire.get("uuid") and self.wire_id_matches(str(wire["uuid"]), wire_id)
        ]
        if not matches:
            return f"Wire '{wire_id}' was not found in the active schematic."
        if len(matches) > 1:
            matching_ids = ", ".join(str(wire["uuid"]) for wire in matches[:5])
            return f"Wire identifier '{wire_id}' is ambiguous. Matching UUIDs: {matching_ids}"

        target = matches[0]
        target_signature = self.wire_signature(
            target["x1"],
            target["y1"],
            target["x2"],
            target["y2"],
        )

        def mutator(current_text: str) -> str:
            pieces: list[str] = []
            cursor = 0
            last = 0
            removed = False
            while cursor < len(current_text):
                if current_text[cursor:].startswith("(wire"):
                    block, length = self.extract_block(current_text, cursor)
                    parsed = self.parse_wire_block(block) if block else None
                    if parsed is not None:
                        signature = self.wire_signature(
                            parsed["x1"],
                            parsed["y1"],
                            parsed["x2"],
                            parsed["y2"],
                        )
                        parsed_uuid = str(parsed.get("uuid", ""))
                        if (
                            signature == target_signature
                            and parsed_uuid
                            and self.wire_id_matches(parsed_uuid, str(target["uuid"]))
                        ):
                            pieces.append(current_text[last:cursor])
                            cursor += length
                            last = cursor
                            removed = True
                            continue
                cursor += 1
            pieces.append(current_text[last:])
            if not removed:
                raise ValueError(f"Wire '{wire_id}' could not be removed.")
            return "".join(pieces)

        try:
            self.transactional_write(mutator, allow_node_loss=True)
        except ValueError as exc:
            return str(exc)
        return (
            f"{self.reload_schematic()}\n"
            f"Deleted wire '{target['uuid']}' from "
            f"({self.format_mm(float(target['x1']))}, {self.format_mm(float(target['y1']))}) to "
            f"({self.format_mm(float(target['x2']))}, {self.format_mm(float(target['y2']))})."
        )

    def delete_symbol(self, reference: str) -> str:
        """Delete placed symbol blocks and directly attached wires."""
        removed_wire_count = 0
        removed_symbol_count = 0

        def mutator(current: str) -> str:
            nonlocal removed_symbol_count, removed_wire_count

            matches = self.find_placed_symbol_blocks(current, reference)
            if not matches:
                raise ValueError(f"Reference '{reference}' was not found in the schematic.")
            removed_symbol_count = len(matches)
            connection_points = {
                point
                for _, _, _, parsed in matches
                for point in self.symbol_connection_points(parsed)
            }

            pieces: list[str] = []
            cursor = 0
            last = 0
            while cursor < len(current):
                if current[cursor:].startswith("(symbol"):
                    block, length = self.extract_block(current, cursor)
                    parsed = self.parse_symbol_block(block) if block else None
                    if parsed is not None and parsed["reference"] == reference:
                        pieces.append(current[last:cursor])
                        cursor += length
                        last = cursor
                        continue
                if current[cursor:].startswith("(wire"):
                    block, length = self.extract_block(current, cursor)
                    parsed_wire = self.parse_wire_block(block) if block else None
                    if parsed_wire is not None:
                        start = self.coordinate_key(parsed_wire["x1"], parsed_wire["y1"])
                        end = self.coordinate_key(parsed_wire["x2"], parsed_wire["y2"])
                        if start in connection_points or end in connection_points:
                            removed_wire_count += 1
                            pieces.append(current[last:cursor])
                            cursor += length
                            last = cursor
                            continue
                cursor += 1
            pieces.append(current[last:])
            return "".join(pieces)

        try:
            self.transactional_write(mutator, allow_node_loss=True)
        except ValueError as exc:
            return str(exc)

        return (
            f"{self.reload_schematic()}\n"
            f"Deleted {removed_symbol_count} symbol block(s) for '{reference}' "
            f"and {removed_wire_count} directly connected wire(s)."
        )

    def delete_label(self, name: str, x_mm: float, y_mm: float) -> str:
        """Delete matching label blocks at raw or grid-snapped coordinates."""
        tolerance = 0.05
        removed = 0
        snapped_x, snapped_y = self.snap_point(x_mm, y_mm, True)

        def matches_target(parsed: ParsedRecord) -> bool:
            for target_x, target_y in ((x_mm, y_mm), (snapped_x, snapped_y)):
                if (
                    abs(float(parsed["x"]) - target_x) <= tolerance
                    and abs(float(parsed["y"]) - target_y) <= tolerance
                ):
                    return True
            return False

        def mutator(current: str) -> str:
            nonlocal removed
            pieces: list[str] = []
            cursor = 0
            last = 0
            while cursor < len(current):
                if current[cursor:].startswith(("(label", "(global_label", "(hierarchical_label")):
                    block, length = self.extract_block(current, cursor)
                    parsed = self.parse_label_block(block) if block else None
                    if parsed is not None and parsed["name"] == name and matches_target(parsed):
                        pieces.append(current[last:cursor])
                        cursor += length
                        last = cursor
                        removed += 1
                        continue
                cursor += 1
            pieces.append(current[last:])
            if removed == 0:
                raise ValueError(
                    f"No label '{name}' found near "
                    f"({self.format_mm(x_mm)}, {self.format_mm(y_mm)})."
                )
            return "".join(pieces)

        try:
            self.transactional_write(mutator, allow_node_loss=True)
        except ValueError as exc:
            return str(exc)
        return (
            f"{self.reload_schematic()}\n"
            f"Deleted {removed} label(s) '{name}' at "
            f"({self.format_mm(x_mm)}, {self.format_mm(y_mm)})."
        )

    def move_label(
        self,
        name: str,
        x_mm: float,
        y_mm: float,
        new_x_mm: float,
        new_y_mm: float,
        new_rotation: int | None,
        snap_to_grid: bool,
    ) -> str:
        """Move the first matching label and optionally update its rotation."""
        target_x, target_y = self.snap_point(new_x_mm, new_y_mm, snap_to_grid)
        snap_note = self.snap_notice((new_x_mm, new_y_mm), (target_x, target_y))
        tolerance = 0.05
        moved = 0

        def mutator(current: str) -> str:
            nonlocal moved
            pieces: list[str] = []
            cursor = 0
            last = 0
            while cursor < len(current):
                if moved == 0 and current[cursor:].startswith(
                    ("(label", "(global_label", "(hierarchical_label")
                ):
                    block, length = self.extract_block(current, cursor)
                    parsed = self.parse_label_block(block) if block else None
                    if (
                        parsed is not None
                        and parsed["name"] == name
                        and abs(float(parsed["x"]) - x_mm) <= tolerance
                        and abs(float(parsed["y"]) - y_mm) <= tolerance
                    ):
                        rotation = (
                            int(parsed["rotation"]) if new_rotation is None else int(new_rotation)
                        )
                        updated_block = re.sub(
                            r"\(at\s+[-\d.]+\s+[-\d.]+\s+[-\d.]+\)",
                            f"(at {self.format_mm(target_x)} "
                            f"{self.format_mm(target_y)} {rotation})",
                            block,
                            count=1,
                        )
                        pieces.append(current[last:cursor])
                        pieces.append(updated_block)
                        cursor += length
                        last = cursor
                        moved += 1
                        continue
                cursor += 1
            pieces.append(current[last:])
            if moved == 0:
                raise ValueError(
                    f"No label '{name}' found near "
                    f"({self.format_mm(x_mm)}, {self.format_mm(y_mm)})."
                )
            return "".join(pieces)

        try:
            self.transactional_write(mutator)
        except ValueError as exc:
            return str(exc)
        lines = [
            self.reload_schematic(),
            f"Moved label '{name}' to ({target_x:.2f}, {target_y:.2f}) mm.",
        ]
        if snap_note:
            lines.append(snap_note)
        return "\n".join(lines)

    def modify_label(
        self,
        name: str,
        x_mm: float,
        y_mm: float,
        justify: str,
    ) -> str:
        """Change justification on the first matching label."""
        resolved_justify = self.normalize_label_justify(justify) or ""
        tolerance = 0.05
        modified = 0

        def mutator(current: str) -> str:
            nonlocal modified
            pieces: list[str] = []
            cursor = 0
            last = 0
            while cursor < len(current):
                if modified == 0 and current[cursor:].startswith(
                    ("(label", "(global_label", "(hierarchical_label")
                ):
                    block, length = self.extract_block(current, cursor)
                    parsed = self.parse_label_block(block) if block else None
                    if (
                        parsed is not None
                        and parsed["name"] == name
                        and abs(float(parsed["x"]) - x_mm) <= tolerance
                        and abs(float(parsed["y"]) - y_mm) <= tolerance
                    ):
                        updated_block = self.set_label_justify(block, resolved_justify)
                        pieces.append(current[last:cursor])
                        pieces.append(updated_block)
                        cursor += length
                        last = cursor
                        modified += 1
                        continue
                cursor += 1
            pieces.append(current[last:])
            if modified == 0:
                raise ValueError(
                    f"No label '{name}' found near "
                    f"({self.format_mm(x_mm)}, {self.format_mm(y_mm)})."
                )
            return "".join(pieces)

        try:
            self.transactional_write(mutator)
        except ValueError as exc:
            return str(exc)

        justify_desc = resolved_justify or "none (centered)"
        return (
            f"{self.reload_schematic()}\n"
            f"Set justify='{justify_desc}' on label '{name}' at "
            f"({self.format_mm(x_mm)}, {self.format_mm(y_mm)})."
        )
