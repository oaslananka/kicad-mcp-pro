"""FastMCP-free orchestration for schematic hierarchy authoring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


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
    ) -> str:
        """Create a child schematic and add it to the active root schematic."""
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

        result = self.reload_schematic()
        detail = f"Created child sheet '{name}' -> {child_path.name}."
        if snap_note:
            detail = f"{detail}\n{snap_note}"
        return f"{result}\n{detail}"

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
