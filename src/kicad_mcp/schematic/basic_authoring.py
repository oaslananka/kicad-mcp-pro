"""Pure orchestration for basic schematic symbol, wire, and label authoring."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


class SchematicTarget(Protocol):
    """Minimal resolved-target surface used by basic authoring."""

    @property
    def path(self) -> Path: ...

    @property
    def is_root(self) -> bool: ...


class ResolveTarget(Protocol):
    """Resolve an optional child-sheet selector."""

    def __call__(
        self,
        sheet: str | None = None,
        sheet_file: str | None = None,
    ) -> SchematicTarget: ...


class PlaceSymbolBlock(Protocol):
    """Create a placed-symbol S-expression block."""

    def __call__(
        self,
        *,
        lib_id: str,
        x: float,
        y: float,
        reference: str,
        value: str,
        footprint: str = "",
        rotation: int = 0,
        unit: int = 1,
        project_name: str,
        root_uuid: str,
    ) -> str: ...


class LabelBlock(Protocol):
    """Create a local-label S-expression block."""

    def __call__(
        self,
        name: str,
        x: float,
        y: float,
        rotation: int = 0,
        *,
        justify: str | None = None,
    ) -> str: ...


type ParseSchematic = Callable[[Path], Mapping[str, Any]]
type ProjectName = Callable[[], str]
type LoadLibSymbol = Callable[[str, str], str | None]
type SuggestSymbolNames = Callable[[str, str], list[str]]
type SymbolAvailableUnits = Callable[[str, str], set[int]]
type FormatAvailableUnits = Callable[[set[int]], str]
type SnapPoint = Callable[[float, float, bool], tuple[float, float]]
type SnapLine = Callable[
    [float, float, float, float, bool],
    tuple[float, float, float, float],
]
type SnapNotice = Callable[[tuple[float, ...], tuple[float, ...]], str]
type PointNearExisting = Callable[[float, float, list[dict[str, Any]]], str | None]
type ValidateFootprint = Callable[[str], str | None]
type WireBlock = Callable[[float, float, float, float], str]
type AppendBeforeSheetInstances = Callable[[str, str], str]
type TransactionalWrite = Callable[[Callable[[str], str], Path], str]
type ReloadSchematic = Callable[[], str]
type NewUuid = Callable[[], str]
type FormatMm = Callable[[float], str]


@dataclass(frozen=True)
class SchematicBasicAuthoringService:
    """Compose basic authoring operations from injected deterministic helpers."""

    resolve_target: ResolveTarget
    parse_schematic: ParseSchematic
    project_name: ProjectName
    load_lib_symbol: LoadLibSymbol
    suggest_symbol_names: SuggestSymbolNames
    symbol_available_units: SymbolAvailableUnits
    format_available_units: FormatAvailableUnits
    snap_point: SnapPoint
    snap_line: SnapLine
    snap_notice: SnapNotice
    point_near_existing: PointNearExisting
    validate_footprint: ValidateFootprint
    place_symbol_block: PlaceSymbolBlock
    wire_block: WireBlock
    label_block: LabelBlock
    append_before_sheet_instances: AppendBeforeSheetInstances
    transactional_write: TransactionalWrite
    reload_schematic: ReloadSchematic
    new_uuid: NewUuid
    format_mm: FormatMm

    @staticmethod
    def _format_target_detail(target: SchematicTarget) -> str:
        kind = "root" if target.is_root else "child"
        return f"Target schematic ({kind}): {target.path}"

    def add_symbol(
        self,
        library: str,
        symbol_name: str,
        x_mm: float,
        y_mm: float,
        reference: str,
        value: str,
        footprint: str,
        rotation: int,
        snap_to_grid: bool,
        unit: int,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        """Add one placed symbol while preserving current warnings and ordering."""
        symbol_x, symbol_y = self.snap_point(x_mm, y_mm, snap_to_grid)
        snap_note = self.snap_notice((x_mm, y_mm), (symbol_x, symbol_y))
        lib_definition = self.load_lib_symbol(library, symbol_name)
        if lib_definition is None:
            suggestions = self.suggest_symbol_names(library, symbol_name)
            hint = f" Did you mean: {', '.join(suggestions)}?" if suggestions else ""
            return f"Symbol '{library}:{symbol_name}' was not found.{hint}"

        available_units = self.symbol_available_units(library, symbol_name)
        if available_units and unit not in available_units:
            return (
                f"Symbol '{library}:{symbol_name}' does not support unit {unit}. "
                f"Available units: {self.format_available_units(available_units)}."
            )

        target = self.resolve_target(sheet=sheet, sheet_file=sheet_file)
        schematic_data = self.parse_schematic(target.path)
        root_uuid = str(schematic_data["uuid"] or self.new_uuid())
        lib_id = f"{library}:{symbol_name}"
        existing = [
            *schematic_data["symbols"],
            *schematic_data["power_symbols"],
        ]
        overlap_warning = self.point_near_existing(symbol_x, symbol_y, existing)

        def mutator(current: str) -> str:
            updated = current
            if f'(symbol "{lib_id}"' not in updated:
                if "(lib_symbols)" in updated:
                    updated = updated.replace(
                        "(lib_symbols)",
                        f"(lib_symbols\n\t{lib_definition}\n\t)",
                        1,
                    )
                else:
                    updated = updated.replace(
                        "\t(lib_symbols\n",
                        f"\t(lib_symbols\n\t{lib_definition}\n",
                        1,
                    )
            block = self.place_symbol_block(
                lib_id=lib_id,
                x=symbol_x,
                y=symbol_y,
                reference=reference,
                value=value,
                footprint=footprint,
                rotation=rotation,
                unit=unit,
                project_name=self.project_name(),
                root_uuid=root_uuid,
            )
            return self.append_before_sheet_instances(updated, block)

        self.transactional_write(mutator, target.path)
        result = self.reload_schematic()
        footprint_warning = self.validate_footprint(footprint or "")
        return "\n".join(
            part
            for part in (
                result,
                self._format_target_detail(target),
                snap_note,
                overlap_warning,
                footprint_warning,
            )
            if part
        )

    def add_wire(
        self,
        x1_mm: float,
        y1_mm: float,
        x2_mm: float,
        y2_mm: float,
        snap_to_grid: bool,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        """Add one wire to a resolved schematic target."""
        target = self.resolve_target(sheet=sheet, sheet_file=sheet_file)
        wire_coordinates = self.snap_line(
            x1_mm,
            y1_mm,
            x2_mm,
            y2_mm,
            snap_to_grid,
        )
        snap_note = self.snap_notice(
            (x1_mm, y1_mm, x2_mm, y2_mm),
            wire_coordinates,
        )
        self.transactional_write(
            lambda current: self.append_before_sheet_instances(
                current,
                self.wire_block(*wire_coordinates),
            ),
            target.path,
        )
        result = self.reload_schematic()
        return "\n".join(
            part for part in (result, self._format_target_detail(target), snap_note) if part
        )

    def add_label(
        self,
        name: str,
        x_mm: float,
        y_mm: float,
        rotation: int,
        snap_to_grid: bool,
        justify: str | None,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        """Add one local label to a resolved schematic target."""
        target = self.resolve_target(sheet=sheet, sheet_file=sheet_file)
        label_x, label_y = self.snap_point(x_mm, y_mm, snap_to_grid)
        snap_note = self.snap_notice((x_mm, y_mm), (label_x, label_y))
        self.transactional_write(
            lambda current: self.append_before_sheet_instances(
                current,
                self.label_block(
                    name,
                    label_x,
                    label_y,
                    rotation,
                    justify=justify,
                ),
            ),
            target.path,
        )
        result = self.reload_schematic()
        return "\n".join(
            part for part in (result, self._format_target_detail(target), snap_note) if part
        )

    def add_power_symbol(
        self,
        name: str,
        x_mm: float,
        y_mm: float,
        rotation: int,
        snap_to_grid: bool,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        """Add a generated-reference power symbol through the symbol path."""
        placed_x, placed_y = self.snap_point(x_mm, y_mm, snap_to_grid)
        result = self.add_symbol(
            library="power",
            symbol_name=name,
            x_mm=x_mm,
            y_mm=y_mm,
            reference=f"#PWR{self.new_uuid()[:4]}",
            value=name,
            footprint="",
            rotation=rotation,
            snap_to_grid=snap_to_grid,
            unit=1,
            sheet=sheet,
            sheet_file=sheet_file,
        )
        if "was not found" in result:
            return result
        return (
            f"{result}\nPower symbol {name} placed at "
            f"({self.format_mm(placed_x)}, {self.format_mm(placed_y)})"
        )
