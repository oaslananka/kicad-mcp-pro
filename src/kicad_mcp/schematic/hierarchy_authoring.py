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
    delete_sheet_block,
    insert_pin,
    move_sheet_block,
    parse_hierarchical_labels,
    parse_sheet_blocks,
    parse_skipped_sheet_blocks,
    placement_on_edge,
    plan_sheet_pins,
)
from .sheet_wiring import (
    apply_spread_shifts,
    attached_pin_names,
    page_width_mm,
    plan_sheet_wiring,
    plan_spread,
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
type WireBlock = Callable[[float, float, float, float], str]
type ParseWireEndpoints = Callable[[str], tuple[tuple[float, float], ...]]


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
    wire_block: WireBlock
    parse_wire_endpoints: ParseWireEndpoints

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
                already = f"Sheet '{name}' already exists."
                if sheet_pins:
                    already += (
                        " Nothing was created and no sheet pins were applied -- this early "
                        "return does not touch an existing sheet. Use sch_add_sheet_pin or "
                        "sch_import_sheet_pins to add pins to it."
                    )
                return already
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
        schematic's ``title_block``.

        Never raises. ``create_sheet`` calls it outside any ``try`` and after
        the sheet is already on disk, so an ``OSError`` from the re-read or a
        ``ValueError`` from planning would otherwise surface as a failed
        ``sch_create_sheet`` for a sheet that was in fact created. Every failure
        is folded into the returned string instead.
        """
        plan_labels = tuple(sheet_pins)
        try:
            root_text = self.read_text(top_schematic_path)
            block = next(
                (
                    candidate
                    for candidate in parse_sheet_blocks(root_text)
                    if candidate.name == name
                ),
                None,
            )
            if block is None:
                return (
                    f"\nSheet '{name}' was created, but its block could not be re-read to add pins."
                )
            plan = self._stamp_uuids(plan_sheet_pins(plan_labels, block, grid_mm=self.grid_mm()))
        except Exception as exc:
            self.warn("schematic_create_sheet_pins_failed", name=name, error=str(exc))
            return f"\nSheet '{name}' was created, but its pins could not be planned: {exc}"

        def mutator(current: str) -> str:
            target = next(
                (candidate for candidate in parse_sheet_blocks(current) if candidate.name == name),
                None,
            )
            if target is None:
                raise ValueError(f"Sheet '{name}' disappeared before the pin write.")
            return apply_plan(current, target, plan)

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
        # The same disclosures sch_import_sheet_pins surfaces -- notably that a
        # widened sheet was widened from an estimated text width. Dropping them
        # here would let sch_create_sheet resize a sheet and say nothing.
        pin_detail += "".join(f"\nnote: {note}" for note in plan.notes)
        return pin_detail

    @staticmethod
    def _describe(sheet: SheetBlock, plan: SheetPinPlan) -> str:
        """Summarize what a plan would do to one sheet.

        Only ever appended to a report on a path where that plan was in fact
        written (or explicitly labelled a preview). ``moved`` is counted apart
        from ``unchanged`` because a repositioned pin is rewritten in the file,
        and calling it unchanged would be a false statement about the write.
        """
        counts = {"add": 0, "retype": 0, "move": 0, "keep": 0}
        for placement in plan.placements:
            counts[placement.action] += 1
        detail = (
            f"- {sheet.name}: {counts['add']} added, {counts['retype']} retyped, "
            f"{counts['move']} moved, {counts['keep']} unchanged"
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
                skipped = next(
                    (
                        candidate
                        for candidate in parse_skipped_sheet_blocks(root_text)
                        if candidate.name == sheet
                    ),
                    None,
                )
                if skipped is not None:
                    # The sheet is in the file; it is the block that is unusable.
                    # Saying "not found" here would send the user looking for a
                    # name that is right there.
                    return (
                        f"Sheet '{sheet}' is in {root_path.name} but cannot be addressed: "
                        f"{skipped.reason}. Fix that block in KiCad and retry."
                    )
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
                    raise ValueError(
                        f"Sheet '{name}' disappeared between the read and the write, so its "
                        "pins were not applied. Re-run sch_import_sheet_pins."
                    )
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
            # No per-sheet lines here, and none on the write-failure path below.
            # They describe the *plan*; on a failed path nothing was written, so
            # printing "1 added" for a sheet the transaction rolled back would
            # be false. The two failure returns therefore have the same shape.
            self.warn("schematic_import_sheet_pins_failed", error=str(exc))
            return f"Could not import sheet pins: {exc}"

        if mutated == root_text:
            return "\n".join(["Sheet pins are already up to date; nothing was written.", *lines])
        if dry_run:
            return "\n".join(["Dry run -- nothing was written.", *lines])

        try:
            self.transactional_write(mutator, root_path)
        except Exception as exc:
            self.warn("schematic_import_sheet_pins_failed", error=str(exc))
            return f"Could not import sheet pins: {exc}"

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
            self.warn("schematic_add_sheet_pin_unreadable", sheet=sheet, error=str(exc))
            return f"Could not read the top-level schematic: {exc}"

        block = next(
            (candidate for candidate in parse_sheet_blocks(root_text) if candidate.name == sheet),
            None,
        )
        if block is None:
            skipped = next(
                (
                    candidate
                    for candidate in parse_skipped_sheet_blocks(root_text)
                    if candidate.name == sheet
                ),
                None,
            )
            if skipped is not None:
                return (
                    f"Sheet '{sheet}' is in {root_path.name} but cannot be addressed: "
                    f"{skipped.reason}. Fix that block in KiCad and retry."
                )
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

    def _find_sheet_block(self, root_path: Path, root_text: str, name: str) -> SheetBlock | str:
        """Return the addressable block named ``name``, or a report string if it is not one.

        Mirrors the lookup ``add_sheet_pin`` and ``import_sheet_pins`` use: a
        block that is in the file but unaddressable (bad ``(at ...)``, missing
        size) is reported as such rather than as "not found", so the user is not
        sent looking for a name that is right there.
        """
        block = next(
            (candidate for candidate in parse_sheet_blocks(root_text) if candidate.name == name),
            None,
        )
        if block is not None:
            return block
        skipped = next(
            (
                candidate
                for candidate in parse_skipped_sheet_blocks(root_text)
                if candidate.name == name
            ),
            None,
        )
        if skipped is not None:
            return (
                f"Sheet '{name}' is in {root_path.name} but cannot be addressed: "
                f"{skipped.reason}. Fix that block in KiCad and retry."
            )
        return f"Sheet '{name}' was not found in {root_path.name}."

    def move_sheet(self, name: str, x_mm: float, y_mm: float, snap_to_grid: bool) -> str:
        """Move the hierarchical sheet symbol named ``name`` to a new anchor coordinate.

        Only ``(at ...)`` nodes move -- the sheet's own and each of its pins',
        preserving every pin's offset from the anchor and its rotation -- so
        nothing else about the sheet symbol (size, styling, UUIDs, its
        ``(instances ...)`` path) is touched.
        """
        root_path = self.active_schematic_file()
        try:
            root_text = self.read_text(root_path)
        except OSError as exc:
            self.warn("schematic_move_sheet_unreadable", name=name, error=str(exc))
            return f"Could not read the top-level schematic: {exc}"

        block = self._find_sheet_block(root_path, root_text, name)
        if isinstance(block, str):
            return block

        new_x, new_y = self.snap_point(x_mm, y_mm, snap_to_grid)
        snap_note = self.snap_notice((x_mm, y_mm), (new_x, new_y))
        skipped_pins: list[str] = []

        def mutator(current: str) -> str:
            target = next(
                (candidate for candidate in parse_sheet_blocks(current) if candidate.name == name),
                None,
            )
            if target is None:
                raise ValueError(f"Sheet '{name}' disappeared before the write.")
            if target.origin != block.origin or target.size != block.size:
                raise ValueError(
                    f"Sheet '{name}' moved or resized since it was read "
                    f"(origin {block.origin} -> {target.origin}, "
                    f"size {block.size} -> {target.size}); "
                    "refusing to overwrite it. Re-run sch_move_sheet."
                )
            updated, skipped = move_sheet_block(current, target, new_x, new_y)
            skipped_pins[:] = skipped
            return updated

        try:
            self.transactional_write(mutator, root_path)
        except Exception as exc:
            self.warn("schematic_move_sheet_failed", name=name, error=str(exc))
            return f"Could not move sheet '{name}': {exc}"

        result = self.reload_schematic()
        lines = [result, f"Moved sheet '{name}' to {new_x}, {new_y} mm."]
        if skipped_pins:
            lines.append(
                "Left these pins in place (no readable (at ...) node to rewrite): "
                + ", ".join(skipped_pins)
                + ". Open the file in KiCad and save it once, then retry."
            )
        if snap_note:
            lines.append(snap_note)
        return "\n".join(lines)

    def delete_sheet(self, name: str) -> str:
        """Remove the hierarchical sheet symbol named ``name`` from the top-level schematic.

        The ``(sheet ...)`` block carries its own ``(instances ...)`` path
        bookkeeping, so removing the block is the exact inverse of
        ``sch_create_sheet``. The child ``.kicad_sch`` file on disk is left
        untouched -- only the sheet symbol in the parent is removed.
        """
        root_path = self.active_schematic_file()
        try:
            root_text = self.read_text(root_path)
        except OSError as exc:
            self.warn("schematic_delete_sheet_unreadable", name=name, error=str(exc))
            return f"Could not read the top-level schematic: {exc}"

        block = self._find_sheet_block(root_path, root_text, name)
        if isinstance(block, str):
            return block

        def mutator(current: str) -> str:
            target = next(
                (candidate for candidate in parse_sheet_blocks(current) if candidate.name == name),
                None,
            )
            if target is None:
                raise ValueError(f"Sheet '{name}' disappeared before the write.")
            return delete_sheet_block(current, target)

        try:
            self.transactional_write(mutator, root_path, allow_node_loss=True)
        except Exception as exc:
            self.warn("schematic_delete_sheet_failed", name=name, error=str(exc))
            return f"Could not delete sheet '{name}': {exc}"

        result = self.reload_schematic()
        return f"{result}\nDeleted sheet '{name}' from {root_path.name}."

    def wire_sheet_pins(
        self,
        sheet: str | None,
        stub_mm: float,
        dry_run: bool,
    ) -> str:
        """Add a stub wire and a local label at every sheet pin.

        A sheet pin alone joins nothing -- two sheets become one net only once
        something in the parent connects their pins, and matching names are not
        enough (unlike global labels). This writes the stub-then-label idiom:
        a short wire out of the pin, then a *local* label carrying its name at
        the far end. Same-named local labels on one sheet are one net, so no
        wire ever has to route between sheet symbols.

        ``sheet``, if given, limits which sheet's pins get a new stub and label
        this call -- every sheet's pins still count towards orphan and
        collision detection, since a name only "matches" once its counterpart
        elsewhere in the document is known.
        """
        root_path = self.active_schematic_file()
        try:
            root_text = self.read_text(root_path)
        except OSError as exc:
            self.warn("schematic_wire_sheet_pins_unreadable", error=str(exc))
            return f"Could not read the top-level schematic: {exc}"

        blocks = parse_sheet_blocks(root_text)
        if not blocks:
            return f"{root_path.name} has no child sheets, so there is nothing to wire."
        if sheet is not None and not any(block.name == sheet for block in blocks):
            return f"Sheet '{sheet}' was not found in {root_path.name}."

        wired_points = self.parse_wire_endpoints(root_text)
        plan = plan_sheet_wiring(
            blocks,
            wired_points=wired_points,
            grid_mm=self.grid_mm(),
            stub_mm=stub_mm,
        )
        targets = tuple(
            placement
            for placement in plan.placements
            if placement.action == "add" and (sheet is None or placement.sheet_name == sheet)
        )

        def mutator(current: str) -> str:
            for placement in targets:
                current = self.append_before_sheet_instances(
                    current,
                    self.wire_block(
                        placement.x1_mm, placement.y1_mm, placement.x2_mm, placement.y2_mm
                    ),
                )
                current = self.append_before_sheet_instances(
                    current,
                    self.label_block(
                        placement.name,
                        placement.label_x_mm,
                        placement.label_y_mm,
                        placement.label_rotation,
                        kind="label",
                        justify=placement.label_justify,
                    ),
                )
            return current

        try:
            mutated = mutator(root_text)
        except Exception as exc:
            self.warn("schematic_wire_sheet_pins_failed", error=str(exc))
            return f"Could not wire sheet pins: {exc}"

        lines = list(plan.notes)
        if plan.orphans:
            lines.append("Pins with no match on another sheet: " + ", ".join(plan.orphans) + ".")
        if plan.collisions:
            lines.extend(f"note: {collision}" for collision in plan.collisions)

        if mutated == root_text:
            return "\n".join(["Sheet pins are already wired; nothing was written.", *lines])
        if dry_run:
            return "\n".join(
                [
                    f"Dry run -- would add {len(targets)} stub(s) and label(s); "
                    "nothing was written.",
                    *lines,
                ]
            )

        try:
            self.transactional_write(mutator, root_path)
        except Exception as exc:
            self.warn("schematic_wire_sheet_pins_failed", error=str(exc))
            return f"Could not wire sheet pins: {exc}"

        result = self.reload_schematic()
        return "\n".join(
            [
                result,
                f"Wired {len(targets)} sheet pin(s): added {len(targets)} stub(s) and labels.",
                *lines,
            ]
        )

    def spread_sheets(
        self,
        min_gap_mm: float | None,
        margin_mm: float,
        dry_run: bool,
    ) -> str:
        """Move sheet-symbol columns apart to make room for stub-and-label wiring.

        Only ``(at ...)`` nodes move -- the sheet's own, and each of its pins',
        preserving every pin's rotation -- so nothing else about a sheet symbol
        or its pins (styling, UUIDs) is touched. A sheet with a wire already on
        one of its pins is never moved: moving it would silently disconnect
        that wire, since KiCad joins on exact coordinate equality.
        """
        root_path = self.active_schematic_file()
        try:
            root_text = self.read_text(root_path)
        except OSError as exc:
            self.warn("schematic_spread_sheets_unreadable", error=str(exc))
            return f"Could not read the top-level schematic: {exc}"

        blocks = parse_sheet_blocks(root_text)
        if not blocks:
            return f"{root_path.name} has no child sheets, so there is nothing to spread."

        wired_points = self.parse_wire_endpoints(root_text)
        attached = attached_pin_names(blocks, wired_points)
        effective_page_width_mm = page_width_mm(root_text)

        plan = plan_spread(
            blocks,
            attached=attached,
            grid_mm=self.grid_mm(),
            margin_mm=margin_mm,
            min_gap_mm=min_gap_mm,
            page_width_mm=effective_page_width_mm,
        )
        lines = list(plan.notes)

        if plan.blocked:
            return "\n".join(["Nothing was moved.", *lines])
        if plan.overflow_mm:
            return "\n".join(["Nothing was moved.", *lines])
        if not plan.shifts:
            return "\n".join(["Sheets are already spread out; nothing was written.", *lines])

        dx_by_sheet: dict[str, float] = {
            name: shift.dx_mm for shift in plan.shifts for name in shift.sheet_names
        }
        skipped_pins: list[tuple[str, str]] = []

        def mutator(current: str) -> str:
            updated, skipped = apply_spread_shifts(
                current,
                dx_by_sheet,
                subject=root_path.name,
            )
            skipped_pins[:] = skipped
            return updated

        try:
            mutated = mutator(root_text)
        except ValueError as exc:
            self.warn("schematic_spread_sheets_failed", error=str(exc))
            return f"Could not spread sheets: {exc}"

        if skipped_pins:
            lines.append(
                "Left in place (no readable (at ...) node to rewrite): "
                + ", ".join(f"'{pin}' on '{sheet}'" for sheet, pin in skipped_pins)
                + ". Open the file in KiCad and save it once, then retry."
            )

        if mutated == root_text:
            return "\n".join(["Sheets are already spread out; nothing was written.", *lines])

        moved = ", ".join(sorted(dx_by_sheet))
        if dry_run:
            return "\n".join(
                [f"Dry run -- would move {len(dx_by_sheet)} sheet(s): {moved}.", *lines]
            )

        try:
            self.transactional_write(mutator, root_path)
        except Exception as exc:
            self.warn("schematic_spread_sheets_failed", error=str(exc))
            return f"Could not spread sheets: {exc}"

        result = self.reload_schematic()
        return "\n".join([result, f"Spread {len(dx_by_sheet)} sheet(s): {moved}.", *lines])
