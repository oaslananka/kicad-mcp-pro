"""FastMCP-free orchestration for schematic hierarchy authoring."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from .sheet_pins import (
    EDGES,
    PIN_TYPES,
    SheetBlock,
    SheetPinPlan,
    apply_plan,
    insert_pin,
    parse_hierarchical_labels,
    parse_sheet_blocks,
    placement_on_edge,
    plan_sheet_pins,
)


class SchematicTarget(Protocol):
    """Minimal resolved-target surface used by hierarchy label authoring."""

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


class ChildSchematic(Protocol):
    """Minimal child schematic created by kicad-sch-api."""

    def save(self, path: Path, preserve_format: bool = True) -> object: ...


class SheetManager(Protocol):
    """Minimal sheet lookup surface exposed by a loaded schematic."""

    def get_sheet_by_name(self, name: str) -> object | None: ...


class RootSchematic(Protocol):
    """Minimal loaded schematic surface required to add a child sheet."""

    sheets: SheetManager

    def add_sheet(
        self,
        name: str,
        filename: str,
        position: tuple[float, float],
        size: tuple[float, float],
        stroke_width: float | None = None,
        stroke_type: str = "solid",
        project_name: str | None = None,
        page_number: str | None = None,
        uuid: str | None = None,
    ) -> str: ...

    def save(
        self,
        file_path: Path | str | None = None,
        preserve_format: bool = True,
    ) -> object: ...


class LabelBlock(Protocol):
    """Create a hierarchical or global label S-expression block."""

    def __call__(
        self,
        name: str,
        x: float,
        y: float,
        rotation: int = 0,
        global_label: bool = False,
        shape: str | None = None,
        kind: str | None = None,
        justify: str | None = None,
    ) -> str: ...


class TransactionalWrite(Protocol):
    """Apply a guarded schematic mutation to a selected file."""

    def __call__(
        self,
        mutator: Callable[[str], str],
        sch_file: Path | None = None,
        *,
        allow_node_loss: bool = False,
    ) -> str: ...


class Warn(Protocol):
    """Emit a structured warning without coupling to a logging implementation."""

    def __call__(self, event: str, **fields: object) -> object: ...


type ActiveSchematicFile = Callable[[], Path]
type ResolveCreateSchematic = Callable[[], Callable[[str], ChildSchematic]]
type LoadSchematic = Callable[[Path], RootSchematic]
type SnapPoint = Callable[[float, float, bool], tuple[float, float]]
type SnapNotice = Callable[[tuple[float, ...], tuple[float, ...]], str]
type ProjectName = Callable[[], str]
type AppendBeforeSheetInstances = Callable[[str, str], str]
type ReloadSchematic = Callable[[], str]
type ReadText = Callable[[Path], str]
type GridMM = Callable[[], float]
type NewUUID = Callable[[], str]


@dataclass(frozen=True)
class SchematicHierarchyAuthoringService:
    """Compose child-sheet and hierarchy-label operations from injected helpers."""

    active_schematic_file: ActiveSchematicFile
    resolve_target: ResolveTarget
    resolve_create_schematic: ResolveCreateSchematic
    load_schematic: LoadSchematic
    snap_point: SnapPoint
    snap_notice: SnapNotice
    project_name: ProjectName
    default_sheet_size: tuple[float, float]
    label_block: LabelBlock
    append_before_sheet_instances: AppendBeforeSheetInstances
    transactional_write: TransactionalWrite
    reload_schematic: ReloadSchematic
    warn: Warn
    read_text: ReadText
    grid_mm: GridMM
    new_uuid: NewUUID

    @staticmethod
    def _format_target_detail(target: SchematicTarget) -> str:
        kind = "root" if target.is_root else "child"
        return f"Target schematic ({kind}): {target.path}"

    def create_sheet(
        self,
        name: str,
        filename: str,
        x_mm: float,
        y_mm: float,
        snap_to_grid: bool,
        sheet_pins: Sequence[tuple[str, str]] = (),
    ) -> str:
        """Create a child schematic and add it to the active root schematic.

        ``sheet_pins``, if given, is applied after the sheet is created through
        the same text splice ``import_sheet_pins`` uses -- never through
        ``kicad_sch_api.add_sheet()``'s own ``sheet_pins`` argument, whose
        load/save round trip silently drops ``(comment N ...)`` nodes from the
        schematic's ``title_block``. That is a second write on top of the one
        that creates the sheet: if it fails, the sheet already exists (and is
        reported as created) but is pinless, and the returned text says so
        explicitly rather than looking like the whole call failed.
        """
        try:
            create_schematic = self.resolve_create_schematic()
        except Exception as exc:
            self.warn("schematic_create_sheet_dependency_missing", error=str(exc))
            return "kicad-sch-api is unavailable, so child sheet creation could not run."

        top_schematic_path = self.active_schematic_file()
        sheet_x, sheet_y = self.snap_point(x_mm, y_mm, snap_to_grid)
        snap_note = self.snap_notice((x_mm, y_mm), (sheet_x, sheet_y))
        child_name = filename
        if not child_name.endswith(".kicad_sch"):
            child_name = f"{child_name}.kicad_sch"
        child_path = top_schematic_path.parent / child_name
        child_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            schematic = self.load_schematic(top_schematic_path)
            if schematic.sheets.get_sheet_by_name(name) is not None:
                return f"Sheet '{name}' already exists."
            if not child_path.exists():
                child_schematic = create_schematic(name)
                child_schematic.save(child_path, preserve_format=True)
            schematic.add_sheet(
                name,
                str(child_path.relative_to(top_schematic_path.parent)).replace("\\", "/"),
                (sheet_x, sheet_y),
                self.default_sheet_size,
                project_name=self.project_name(),
            )
            schematic.save(top_schematic_path, preserve_format=True)
        except Exception as exc:
            self.warn(
                "schematic_create_sheet_failed",
                name=name,
                filename=str(child_path),
                error=str(exc),
            )
            return f"Could not create child sheet '{name}': {exc}"

        pin_detail = (
            self._apply_sheet_pins(name, top_schematic_path, sheet_pins) if sheet_pins else ""
        )

        result = self.reload_schematic()
        detail = f"Created child sheet '{name}' -> {child_path.name}."
        if snap_note:
            detail = f"{detail}\n{snap_note}"
        return f"{result}\n{detail}{pin_detail}"

    def _add_label(
        self,
        *,
        kind: str,
        text: str,
        x_mm: float,
        y_mm: float,
        shape: str,
        rotation: int,
        snap_to_grid: bool,
        justify: str | None,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        target = self.resolve_target(sheet=sheet, sheet_file=sheet_file)
        label_x, label_y = self.snap_point(x_mm, y_mm, snap_to_grid)
        snap_note = self.snap_notice((x_mm, y_mm), (label_x, label_y))
        self.transactional_write(
            lambda current: self.append_before_sheet_instances(
                current,
                self.label_block(
                    text,
                    label_x,
                    label_y,
                    rotation,
                    kind=kind,
                    shape=shape,
                    justify=justify,
                ),
            ),
            target.path,
        )
        result = self.reload_schematic()
        return "\n".join(
            part for part in (result, self._format_target_detail(target), snap_note) if part
        )

    def add_hierarchical_label(
        self,
        text: str,
        x_mm: float,
        y_mm: float,
        shape: str,
        rotation: int,
        snap_to_grid: bool,
        justify: str | None,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        """Add a hierarchical label to a resolved schematic target."""
        return self._add_label(
            kind="hierarchical_label",
            text=text,
            x_mm=x_mm,
            y_mm=y_mm,
            shape=shape,
            rotation=rotation,
            snap_to_grid=snap_to_grid,
            justify=justify,
            sheet=sheet,
            sheet_file=sheet_file,
        )

    def add_global_label(
        self,
        text: str,
        x_mm: float,
        y_mm: float,
        shape: str,
        rotation: int,
        snap_to_grid: bool,
        justify: str | None,
        sheet: str | None,
        sheet_file: str | None,
    ) -> str:
        """Add a global label to a resolved schematic target."""
        return self._add_label(
            kind="global_label",
            text=text,
            x_mm=x_mm,
            y_mm=y_mm,
            shape=shape,
            rotation=rotation,
            snap_to_grid=snap_to_grid,
            justify=justify,
            sheet=sheet,
            sheet_file=sheet_file,
        )

    def _stamp_uuids(self, plan: SheetPinPlan) -> SheetPinPlan:
        placements = tuple(
            placement if placement.uuid else replace(placement, uuid=self.new_uuid())
            for placement in plan.placements
        )
        return replace(plan, placements=placements)

    def _apply_sheet_pins(
        self,
        name: str,
        top_schematic_path: Path,
        sheet_pins: Sequence[tuple[str, str]],
    ) -> str:
        """Splice ``sheet_pins`` onto a just-created sheet, as a report suffix.

        Called only from ``create_sheet`` once the sheet itself is created and
        saved. This is a second, independent write on top of that one, through
        the same text splice ``import_sheet_pins`` uses: never through
        ``kicad_sch_api.add_sheet()``'s own ``sheet_pins`` argument, whose
        load/save round trip silently drops ``(comment N ...)`` nodes from the
        schematic's ``title_block``. Never raises -- a failure here is folded
        into the returned string so the sheet stays reported as created even
        if its pins could not be written.
        """
        plan_labels = tuple(sheet_pins)
        root_text = self.read_text(top_schematic_path)
        block = next(
            (candidate for candidate in parse_sheet_blocks(root_text) if candidate.name == name),
            None,
        )
        if block is None:
            return f"\nSheet '{name}' was created, but its block could not be re-read to add pins."

        plan = self._stamp_uuids(plan_sheet_pins(plan_labels, block, grid_mm=self.grid_mm()))

        def mutator(current: str, _name: str = name, _plan: SheetPinPlan = plan) -> str:
            target = next(
                (candidate for candidate in parse_sheet_blocks(current) if candidate.name == _name),
                None,
            )
            if target is None:
                raise ValueError(f"Sheet '{_name}' disappeared before the pin write.")
            return apply_plan(current, target, _plan)

        try:
            self.transactional_write(mutator, top_schematic_path)
        except Exception as exc:
            self.warn("schematic_create_sheet_pins_failed", name=name, error=str(exc))
            return f"\nSheet '{name}' was created, but its pins could not be written: {exc}"

        pin_names = ", ".join(placement.name for placement in plan.placements)
        pin_detail = f"\nAdded {len(plan.placements)} sheet pins: {pin_names}."
        if plan.conflicts:
            pin_detail += (
                f" Conflicting pin types for {', '.join(plan.conflicts)} (first occurrence wins)."
            )
        return pin_detail

    @staticmethod
    def _describe(sheet: SheetBlock, plan: SheetPinPlan) -> str:
        counts = {"add": 0, "retype": 0, "keep": 0}
        for placement in plan.placements:
            counts[placement.action] += 1
        detail = (
            f"- {sheet.name}: {counts['add']} added, {counts['retype']} retyped, "
            f"{counts['keep']} unchanged"
        )
        if plan.size != sheet.size:
            detail += f"; resized to {plan.size[0]} x {plan.size[1]} mm"
        if plan.orphans:
            detail += f"; kept without a matching label: {', '.join(plan.orphans)}"
        if plan.conflicts:
            detail += f"; conflicting shapes (first wins): {', '.join(plan.conflicts)}"
        return detail

    def import_sheet_pins(
        self,
        sheet: str | None,
        grow_sheet: bool,
        dry_run: bool,
    ) -> str:
        """Mirror each child sheet's hierarchical labels as pins on its sheet symbol."""
        root_path = self.active_schematic_file()
        try:
            root_text = self.read_text(root_path)
        except OSError as exc:
            self.warn("schematic_import_sheet_pins_unreadable", error=str(exc))
            return f"Could not read the top-level schematic: {exc}"

        blocks = parse_sheet_blocks(root_text)
        if sheet is not None:
            blocks = tuple(block for block in blocks if block.name == sheet)
            if not blocks:
                return f"Sheet '{sheet}' was not found in {root_path.name}."
        if not blocks:
            return f"{root_path.name} has no child sheets, so there is nothing to import."

        grid = self.grid_mm()
        lines: list[str] = []
        pending: list[tuple[str, SheetPinPlan, tuple[float, float], tuple[float, float]]] = []
        for block in blocks:
            child_path = root_path.parent / block.filename
            try:
                child_text = self.read_text(child_path)
            except OSError as exc:
                lines.append(f"- {block.name}: blocked, child sheet unreadable ({exc}).")
                continue
            plan = plan_sheet_pins(
                parse_hierarchical_labels(child_text),
                block,
                grid_mm=grid,
                grow_sheet=grow_sheet,
            )
            if plan.overflow:
                lines.append(
                    f"- {block.name}: blocked, {len(plan.overflow)} pins do not fit at the "
                    f"current size and grow_sheet is off ({', '.join(plan.overflow)})."
                )
                continue
            lines.append(self._describe(block, plan))
            lines.extend(f"  note: {note}" for note in plan.notes)
            pending.append((block.name, self._stamp_uuids(plan), block.origin, block.size))

        if not pending:
            return "\n".join(["No sheet pins could be imported.", *lines])

        def mutator(current: str) -> str:
            for name, plan, origin, size in pending:
                block = next(
                    (
                        candidate
                        for candidate in parse_sheet_blocks(current)
                        if candidate.name == name
                    ),
                    None,
                )
                if block is None:
                    continue
                if block.origin != origin or block.size != size:
                    raise ValueError(
                        f"Sheet '{name}' moved or resized since it was read "
                        f"(origin {origin} -> {block.origin}, size {size} -> {block.size}); "
                        "refusing to overwrite it. Re-run sch_import_sheet_pins."
                    )
                current = apply_plan(current, block, plan)
            return current

        try:
            mutated = mutator(root_text)
        except ValueError as exc:
            self.warn("schematic_import_sheet_pins_failed", error=str(exc))
            return "\n".join([f"Could not import sheet pins: {exc}", *lines])

        if mutated == root_text:
            return "\n".join(["Sheet pins are already up to date; nothing was written.", *lines])
        if dry_run:
            return "\n".join(["Dry run -- nothing was written.", *lines])

        try:
            self.transactional_write(mutator, root_path)
        except Exception as exc:
            self.warn("schematic_import_sheet_pins_failed", error=str(exc))
            return f"Could not write sheet pins: {exc}"

        result = self.reload_schematic()
        return "\n".join([result, "Imported sheet pins.", *lines])

    def add_sheet_pin(
        self,
        sheet: str,
        name: str,
        pin_type: str,
        edge: str,
        position_along_edge: float,
    ) -> str:
        """Add one sheet pin at an explicit edge position, without auto-layout."""
        if pin_type not in PIN_TYPES:
            return f"Unknown sheet pin type '{pin_type}'. Use one of: {', '.join(PIN_TYPES)}."
        if edge not in EDGES:
            return f"Unknown sheet edge '{edge}'. Use one of: {', '.join(EDGES)}."

        root_path = self.active_schematic_file()
        try:
            root_text = self.read_text(root_path)
        except OSError as exc:
            return f"Could not read the top-level schematic: {exc}"

        block = next(
            (candidate for candidate in parse_sheet_blocks(root_text) if candidate.name == sheet),
            None,
        )
        if block is None:
            return f"Sheet '{sheet}' was not found in {root_path.name}."

        placement = placement_on_edge(
            block, name, pin_type, edge, position_along_edge, self.new_uuid()
        )

        def mutator(current: str) -> str:
            target = next(
                (candidate for candidate in parse_sheet_blocks(current) if candidate.name == sheet),
                None,
            )
            if target is None:
                raise ValueError(f"Sheet '{sheet}' disappeared before the write.")
            if target.origin != block.origin or target.size != block.size:
                raise ValueError(
                    f"Sheet '{sheet}' moved or resized since it was read "
                    f"(origin {block.origin} -> {target.origin}, "
                    f"size {block.size} -> {target.size}); "
                    "refusing to overwrite it. Re-run sch_add_sheet_pin."
                )
            return insert_pin(current, target, placement)

        try:
            self.transactional_write(mutator, root_path)
        except Exception as exc:
            self.warn("schematic_add_sheet_pin_failed", sheet=sheet, name=name, error=str(exc))
            return f"Could not add sheet pin '{name}': {exc}"

        result = self.reload_schematic()
        return (
            f"{result}\nAdded pin '{name}' ({pin_type}) to sheet '{sheet}' "
            f"on the {edge} edge at {placement.x_mm}, {placement.y_mm} mm."
        )
