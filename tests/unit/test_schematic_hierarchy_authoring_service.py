from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from kicad_mcp.schematic.hierarchy_authoring import SchematicHierarchyAuthoringService


class _ChildSchematic:
    def __init__(self) -> None:
        self.saved: list[tuple[Path, bool]] = []

    def save(self, path: Path, preserve_format: bool = True) -> None:
        self.saved.append((path, preserve_format))
        path.write_text("child", encoding="utf-8")


class _SheetManager:
    def __init__(self, duplicate: bool = False) -> None:
        self.duplicate = duplicate

    def get_sheet_by_name(self, _name: str) -> dict[str, Any] | None:
        return {"name": "existing"} if self.duplicate else None


class _RootSchematic:
    def __init__(self, duplicate: bool = False) -> None:
        self.sheets = _SheetManager(duplicate)
        self.added: list[dict[str, Any]] = []
        self.saved: list[tuple[Path, bool]] = []

    def add_sheet(
        self,
        name: str,
        filename: str,
        position: tuple[float, float],
        size: tuple[float, float],
        *,
        project_name: str | None = None,
    ) -> str:
        self.added.append(
            {
                "name": name,
                "filename": filename,
                "position": position,
                "size": size,
                "project_name": project_name,
            }
        )
        return "sheet-uuid"

    def save(self, path: Path, preserve_format: bool = True) -> None:
        self.saved.append((path, preserve_format))


class _TransactionRecorder:
    def __init__(self, current: str = "(sheet_instances)") -> None:
        self.current = current
        self.calls: list[tuple[Path, str]] = []

    def __call__(self, mutator: Callable[[str], str], path: Path) -> str:
        updated = mutator(self.current)
        self.calls.append((path, updated))
        return updated


def _service(
    *,
    root_path: Path,
    root: _RootSchematic | None = None,
    child: _ChildSchematic | None = None,
    dependency_error: Exception | None = None,
    load_error: Exception | None = None,
    transaction: _TransactionRecorder | None = None,
    warnings: list[tuple[str, dict[str, Any]]] | None = None,
) -> tuple[
    SchematicHierarchyAuthoringService,
    _RootSchematic,
    _ChildSchematic,
    _TransactionRecorder,
    list[tuple[str, dict[str, Any]]],
]:
    root_schematic = root or _RootSchematic()
    child_schematic = child or _ChildSchematic()
    tx = transaction or _TransactionRecorder()
    warning_calls = warnings if warnings is not None else []

    def resolve_create_schematic() -> Callable[[str], _ChildSchematic]:
        if dependency_error is not None:
            raise dependency_error
        return lambda _name: child_schematic

    def load_schematic(_path: Path) -> _RootSchematic:
        if load_error is not None:
            raise load_error
        return root_schematic

    return (
        SchematicHierarchyAuthoringService(
            active_schematic_file=lambda: root_path,
            resolve_target=lambda sheet=None, sheet_file=None: SimpleNamespace(
                path=Path(sheet_file or sheet or root_path),
                is_root=not bool(sheet or sheet_file),
            ),
            resolve_create_schematic=resolve_create_schematic,
            load_schematic=load_schematic,
            snap_point=lambda x, y, enabled: (10.16, 20.32) if enabled else (x, y),
            snap_notice=lambda original, snapped: (
                "" if original == snapped else f"Grid snap: {original} -> {snapped}"
            ),
            project_name=lambda: "DemoProject",
            default_sheet_size=(30.48, 20.32),
            label_block=lambda text, x, y, rotation, **kwargs: (
                f"({kwargs['kind']} {text} {x} {y} {rotation} "
                f"{kwargs['shape']} {kwargs.get('justify')})"
            ),
            append_before_sheet_instances=lambda current, block: current.replace(
                "(sheet_instances)", f"{block}\n(sheet_instances)", 1
            ),
            transactional_write=tx,
            reload_schematic=lambda: "Reloaded schematic.",
            warn=lambda event, **fields: warning_calls.append((event, fields)),
        ),
        root_schematic,
        child_schematic,
        tx,
        warning_calls,
    )


def test_create_sheet_preserves_missing_dependency_result_and_warning(tmp_path: Path) -> None:
    service, root, _child, _tx, warnings = _service(
        root_path=tmp_path / "demo.kicad_sch",
        dependency_error=ImportError("missing module"),
    )

    assert service.create_sheet("Power", "power", 10.0, 20.0, True) == (
        "kicad-sch-api is unavailable, so child sheet creation could not run."
    )
    assert root.added == []
    assert warnings == [("schematic_create_sheet_dependency_missing", {"error": "missing module"})]


def test_create_sheet_preserves_duplicate_result_before_child_creation(tmp_path: Path) -> None:
    root_path = tmp_path / "demo.kicad_sch"
    service, root, child, _tx, warnings = _service(
        root_path=root_path,
        root=_RootSchematic(duplicate=True),
    )

    assert service.create_sheet("Power", "power", 10.0, 20.0, True) == (
        "Sheet 'Power' already exists."
    )
    assert child.saved == []
    assert root.added == []
    assert warnings == []


def test_create_sheet_creates_child_and_root_with_forward_slash_path(tmp_path: Path) -> None:
    root_path = tmp_path / "demo.kicad_sch"
    service, root, child, _tx, warnings = _service(root_path=root_path)

    result = service.create_sheet("Power", "sub/power", 10.0, 20.0, True)

    child_path = tmp_path / "sub" / "power.kicad_sch"
    assert result == (
        "Reloaded schematic.\n"
        "Created child sheet 'Power' -> power.kicad_sch.\n"
        "Grid snap: (10.0, 20.0) -> (10.16, 20.32)"
    )
    assert child.saved == [(child_path, True)]
    assert root.added == [
        {
            "name": "Power",
            "filename": "sub/power.kicad_sch",
            "position": (10.16, 20.32),
            "size": (30.48, 20.32),
            "project_name": "DemoProject",
        }
    ]
    assert root.saved == [(root_path, True)]
    assert warnings == []


def test_create_sheet_reuses_existing_child_file(tmp_path: Path) -> None:
    root_path = tmp_path / "demo.kicad_sch"
    child_path = tmp_path / "existing.kicad_sch"
    child_path.write_text("existing", encoding="utf-8")
    service, root, child, _tx, _warnings = _service(root_path=root_path)

    service.create_sheet("Existing", "existing.kicad_sch", 1.0, 2.0, False)

    assert child.saved == []
    assert root.added[0]["filename"] == "existing.kicad_sch"
    assert root.added[0]["position"] == (1.0, 2.0)


def test_create_sheet_preserves_failure_result_and_warning(tmp_path: Path) -> None:
    root_path = tmp_path / "demo.kicad_sch"
    service, _root, _child, _tx, warnings = _service(
        root_path=root_path,
        load_error=RuntimeError("cannot parse root"),
    )

    assert service.create_sheet("Power", "power", 10.0, 20.0, True) == (
        "Could not create child sheet 'Power': cannot parse root"
    )
    assert warnings == [
        (
            "schematic_create_sheet_failed",
            {
                "name": "Power",
                "filename": str(tmp_path / "power.kicad_sch"),
                "error": "cannot parse root",
            },
        )
    ]


def test_add_hierarchical_label_preserves_block_target_and_result(tmp_path: Path) -> None:
    root_path = tmp_path / "demo.kicad_sch"
    service, _root, _child, tx, _warnings = _service(root_path=root_path)

    result = service.add_hierarchical_label(
        "OUT",
        10.0,
        20.0,
        "output",
        90,
        True,
        "left",
        "Power",
        None,
    )

    assert result == (
        "Reloaded schematic.\n"
        "Target schematic (child): Power\n"
        "Grid snap: (10.0, 20.0) -> (10.16, 20.32)"
    )
    assert tx.calls == [
        (Path("Power"), "(hierarchical_label OUT 10.16 20.32 90 output left)\n(sheet_instances)")
    ]


def test_add_global_label_preserves_unsnapped_root_result(tmp_path: Path) -> None:
    root_path = tmp_path / "demo.kicad_sch"
    service, _root, _child, tx, _warnings = _service(root_path=root_path)

    result = service.add_global_label(
        "VCC",
        1.0,
        2.0,
        "bidirectional",
        0,
        False,
        None,
        None,
        None,
    )

    assert result == f"Reloaded schematic.\nTarget schematic (root): {root_path}"
    assert tx.calls == [
        (
            root_path,
            "(global_label VCC 1.0 2.0 0 bidirectional None)\n(sheet_instances)",
        )
    ]
