from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from kicad_mcp.schematic.hierarchy_authoring import SchematicHierarchyAuthoringService
from kicad_mcp.schematic.sheet_pins import parse_sheet_blocks


def _fake_wire_block(x1: float, y1: float, x2: float, y2: float) -> str:
    return f"\t(wire (pts (xy {x1} {y1}) (xy {x2} {y2})))"


def _fake_label_block(
    name, x, y, rotation=0, global_label=False, shape=None, kind=None, justify=None
):  # type: ignore[no-untyped-def]
    return f'\t({kind or "label"} "{name}" (at {x} {y} {rotation}) (justify {justify}))'


_FAKE_WIRE_RE = re.compile(
    r"\(wire\s*\(pts\s*\(xy\s+(-?[\d.]+)\s+(-?[\d.]+)\)\s*\(xy\s+(-?[\d.]+)\s+(-?[\d.]+)\)\)"
)


def _fake_parse_wire_endpoints(content: str) -> tuple[tuple[float, float], ...]:
    """Mirror the composition root's ``_wire_endpoints`` over ``_fake_wire_block``'s text."""
    points: list[tuple[float, float]] = []
    for match in _FAKE_WIRE_RE.finditer(content):
        points.append((float(match.group(1)), float(match.group(2))))
        points.append((float(match.group(3)), float(match.group(4))))
    return tuple(points)


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
            read_text=lambda path: path.read_text(encoding="utf-8"),
            grid_mm=lambda: 1.27,
            new_uuid=lambda: "uuid-fake",
            wire_block=_fake_wire_block,
            parse_wire_endpoints=_fake_parse_wire_endpoints,
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


ROOT_TEXT = """(kicad_sch
\t(title_block
\t\t(comment 1 "keep me")
\t)
\t(sheet
\t\t(at 80.01 30.48)
\t\t(size 30.48 20.32)
\t\t(property "Sheetname" "02_mcu"
\t\t\t(at 80.01 29.77 0)
\t\t)
\t\t(property "Sheetfile" "child.kicad_sch"
\t\t\t(at 80.01 51.38 0)
\t\t)
\t\t(instances
\t\t\t(project "main" (path "/1" (page "2")))
\t\t)
\t)
)
"""

CHILD_TEXT = (
    '(hierarchical_label "VIN"\n\t(shape input)\n\t(at 1 2 0)\n)\n'
    '(hierarchical_label "VOUT"\n\t(shape output)\n\t(at 3 4 0)\n)\n'
)


class _TextStore:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files
        self.writes: list[str] = []

    def read(self, path: Path) -> str:
        try:
            return self.files[path.name]
        except KeyError as exc:
            raise OSError(f"missing {path.name}") from exc

    def transactional_write(self, mutator, sch_file=None):  # type: ignore[no-untyped-def]
        name = (sch_file or Path("root.kicad_sch")).name
        updated = mutator(self.files[name])
        self.files[name] = updated
        self.writes.append(updated)
        return updated


def _fake_append_before_sheet_instances(current: str, block: str) -> str:
    """Mirror the composition root's fallback: no top-level (sheet_instances) marker
    ever appears in these fixtures, so the block goes in just before the final paren.
    """
    marker = "\t(sheet_instances"
    if marker in current:
        return current.replace(marker, f"{block}\n{marker}", 1)
    return current.rstrip().rstrip(")") + f"\n{block}\n)\n"


def _pin_service(store: _TextStore, root: Path) -> SchematicHierarchyAuthoringService:
    counter = iter(f"uuid-{index}" for index in range(1000))
    return SchematicHierarchyAuthoringService(
        active_schematic_file=lambda: root,
        resolve_target=lambda sheet=None, sheet_file=None: SimpleNamespace(path=root, is_root=True),
        resolve_create_schematic=lambda: lambda name: _ChildSchematic(),
        load_schematic=lambda path: _RootSchematic(),
        snap_point=lambda x, y, snap: (x, y),
        snap_notice=lambda before, after: "",
        project_name=lambda: "main",
        default_sheet_size=(30.48, 20.32),
        label_block=_fake_label_block,
        append_before_sheet_instances=_fake_append_before_sheet_instances,
        transactional_write=store.transactional_write,
        reload_schematic=lambda: "reloaded",
        warn=lambda event, **fields: None,
        read_text=store.read,
        grid_mm=lambda: 1.27,
        new_uuid=lambda: next(counter),
        wire_block=_fake_wire_block,
        parse_wire_endpoints=_fake_parse_wire_endpoints,
    )


def test_import_sheet_pins_writes_one_pin_per_distinct_label(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.import_sheet_pins(None, True, False)

    written = store.files["root.kicad_sch"]
    assert written.count("(pin ") == 2
    assert '(pin "VIN" input' in written
    assert '(pin "VOUT" output' in written
    assert '(comment 1 "keep me")' in written
    assert "02_mcu" in report


def test_import_sheet_pins_dry_run_writes_nothing(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.import_sheet_pins(None, True, True)

    assert store.writes == []
    assert "dry run" in report.casefold()


def test_import_sheet_pins_is_a_no_op_on_the_second_run(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")
    service.import_sheet_pins(None, True, False)
    after_first = store.files["root.kicad_sch"]

    report = service.import_sheet_pins(None, True, False)

    assert len(store.writes) == 1
    assert store.files["root.kicad_sch"] == after_first
    assert "already up to date" in report.casefold()


def test_import_sheet_pins_reports_an_unreadable_child(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.import_sheet_pins(None, True, False)

    assert "blocked" in report.casefold()
    assert store.writes == []


def test_import_sheet_pins_rejects_an_unknown_sheet(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.import_sheet_pins("nope", True, False)

    assert "not found" in report.casefold()
    assert store.writes == []


def test_add_sheet_pin_places_one_pin_on_the_requested_edge(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.add_sheet_pin("02_mcu", "MANUAL", "bidirectional", "top", 5.08)

    written = store.files["root.kicad_sch"]
    assert '(pin "MANUAL" bidirectional' in written
    assert "(at 85.09 30.48 90)" in written
    assert "MANUAL" in report


def test_add_sheet_pin_rejects_an_invalid_type(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.add_sheet_pin("02_mcu", "MANUAL", "nonsense", "left", 5.08)

    assert "nonsense" in report
    assert store.writes == []


def test_create_sheet_writes_the_requested_pins(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.create_sheet(
        "02_mcu", "child.kicad_sch", 80.01, 30.48, True, (("VIN", "input"),)
    )

    assert '(pin "VIN" input' in store.files["root.kicad_sch"]
    assert "VIN" in report


def test_create_sheet_without_pins_behaves_as_before(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    service.create_sheet("02_mcu", "child.kicad_sch", 80.01, 30.48, True, ())

    assert "(pin " not in store.files["root.kicad_sch"]
    # No pins requested -> the pin-splice write path (transactional_write) must
    # never run at all, not merely produce no visible "(pin " text.
    assert store.writes == []


def test_create_sheet_reports_conflicting_duplicate_pin_names(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.create_sheet(
        "02_mcu",
        "child.kicad_sch",
        80.01,
        30.48,
        True,
        (("VIN", "input"), ("VIN", "output")),
    )

    written = store.files["root.kicad_sch"]
    assert written.count('(pin "VIN"') == 1
    assert '(pin "VIN" input' in written
    assert "Conflicting pin types for VIN" in report


def test_create_sheet_dedupes_identical_duplicate_pin_names(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.create_sheet(
        "02_mcu",
        "child.kicad_sch",
        80.01,
        30.48,
        True,
        (("VIN", "input"), ("VIN", "input")),
    )

    written = store.files["root.kicad_sch"]
    assert written.count('(pin "VIN"') == 1
    assert "Conflicting" not in report


def test_create_sheet_reports_a_failed_pin_write_without_losing_the_created_sheet(
    tmp_path: Path,
) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    def _boom(mutator, sch_file=None):  # type: ignore[no-untyped-def]
        raise RuntimeError("disk full")

    service = replace(service, transactional_write=_boom)

    report = service.create_sheet(
        "02_mcu", "child.kicad_sch", 80.01, 30.48, True, (("VIN", "input"),)
    )

    assert "was created" in report
    assert "disk full" in report
    assert "(pin " not in store.files["root.kicad_sch"]


ROOT_TEXT_NO_ANCHOR = """(kicad_sch
\t(title_block
\t\t(comment 1 "keep me")
\t)
\t(sheet
\t\t(at 80.01 30.48)
\t\t(size 30.48 20.32)
\t\t(property "Sheetname" "02_mcu"
\t\t\t(at 80.01 29.77 0)
\t\t)
\t\t(property "Sheetfile" "child.kicad_sch"
\t\t\t(at 80.01 51.38 0)
\t\t)
\t)
)
"""


def test_import_sheet_pins_reports_a_missing_anchor_under_dry_run(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT_NO_ANCHOR, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.import_sheet_pins(None, True, True)

    assert store.writes == []
    assert "02_mcu" in report
    assert "instances" in report.casefold()


def test_import_sheet_pins_reports_a_missing_anchor_when_writing(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT_NO_ANCHOR, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.import_sheet_pins(None, True, False)

    assert store.writes == []
    assert "02_mcu" in report
    assert "instances" in report.casefold()
    assert store.files["root.kicad_sch"] == ROOT_TEXT_NO_ANCHOR


ROOT_TEXT_TWO_SHEETS = """(kicad_sch
\t(title_block
\t\t(comment 1 "keep me")
\t)
\t(sheet
\t\t(at 50.0 30.0)
\t\t(size 20.0 20.0)
\t\t(property "Sheetname" "01_power"
\t\t\t(at 50.0 29.0 0)
\t\t)
\t\t(property "Sheetfile" "power.kicad_sch"
\t\t\t(at 50.0 51.0 0)
\t\t)
\t\t(instances
\t\t\t(project "main" (path "/1" (page "2")))
\t\t)
\t)
\t(sheet
\t\t(at 80.01 30.48)
\t\t(size 30.48 20.32)
\t\t(property "Sheetname" "02_mcu"
\t\t\t(at 80.01 29.77 0)
\t\t)
\t\t(property "Sheetfile" "mcu.kicad_sch"
\t\t\t(at 80.01 51.38 0)
\t\t)
\t\t(instances
\t\t\t(project "main" (path "/1" (page "3")))
\t\t)
\t)
)
"""

POWER_CHILD_TEXT = (
    '(hierarchical_label "VBUS"\n\t(shape input)\n\t(at 1 2 0)\n)\n'
    '(hierarchical_label "GND"\n\t(shape passive)\n\t(at 3 4 0)\n)\n'
    '(hierarchical_label "EN"\n\t(shape output)\n\t(at 5 6 0)\n)\n'
)


def test_import_sheet_pins_applies_multiple_sheets_in_one_transaction(tmp_path: Path) -> None:
    store = _TextStore(
        {
            "root.kicad_sch": ROOT_TEXT_TWO_SHEETS,
            "power.kicad_sch": POWER_CHILD_TEXT,
            "mcu.kicad_sch": CHILD_TEXT,
        }
    )
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.import_sheet_pins(None, True, False)

    written = store.files["root.kicad_sch"]
    assert len(store.writes) == 1

    parsed = {block.name: block for block in parse_sheet_blocks(written)}
    assert set(parsed) == {"01_power", "02_mcu"}
    assert {pin.name for pin in parsed["01_power"].pins} == {"VBUS", "GND", "EN"}
    assert {pin.name for pin in parsed["02_mcu"].pins} == {"VIN", "VOUT"}
    assert "01_power" in report
    assert "02_mcu" in report


ROOT_TEXT_WITH_ORPHAN_PIN = """(kicad_sch
\t(title_block
\t\t(comment 1 "keep me")
\t)
\t(sheet
\t\t(at 80.01 30.48)
\t\t(size 30.48 20.32)
\t\t(property "Sheetname" "02_mcu"
\t\t\t(at 80.01 29.77 0)
\t\t)
\t\t(property "Sheetfile" "child.kicad_sch"
\t\t\t(at 80.01 51.38 0)
\t\t)
\t\t(pin "OLD_SIGNAL" input
\t\t\t(at 80.01 32.0 180)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify left)
\t\t\t)
\t\t\t(uuid "orphan-uuid")
\t\t)
\t\t(instances
\t\t\t(project "main" (path "/1" (page "2")))
\t\t)
\t)
)
"""


def test_import_sheet_pins_keeps_an_orphan_pin_and_reports_it(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT_WITH_ORPHAN_PIN, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.import_sheet_pins(None, True, False)

    written = store.files["root.kicad_sch"]
    parsed = parse_sheet_blocks(written)[0]
    assert {pin.name for pin in parsed.pins} == {"OLD_SIGNAL", "VIN", "VOUT"}
    assert "OLD_SIGNAL" in report


class _GeometryDriftStore(_TextStore):
    """Simulate a sheet whose geometry changes between the read and the write."""

    def __init__(self, files: dict[str, str], drifted_root_text: str) -> None:
        super().__init__(files)
        self.drifted_root_text = drifted_root_text

    def transactional_write(self, mutator, sch_file=None):  # type: ignore[no-untyped-def]
        name = (sch_file or Path("root.kicad_sch")).name
        if name == "root.kicad_sch":
            self.files[name] = self.drifted_root_text
        return super().transactional_write(mutator, sch_file)


ROOT_TEXT_MOVED = ROOT_TEXT.replace("(at 80.01 30.48)", "(at 85.09 30.48)")


def test_import_sheet_pins_rejects_a_sheet_that_moved_before_the_write(tmp_path: Path) -> None:
    store = _GeometryDriftStore(
        {"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT},
        drifted_root_text=ROOT_TEXT_MOVED,
    )
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.import_sheet_pins(None, True, False)

    assert store.writes == []
    assert "02_mcu" in report
    assert "moved" in report.casefold() or "resized" in report.casefold()


def test_add_sheet_pin_rejects_a_sheet_that_moved_before_the_write(tmp_path: Path) -> None:
    store = _GeometryDriftStore(
        {"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT},
        drifted_root_text=ROOT_TEXT_MOVED,
    )
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.add_sheet_pin("02_mcu", "MANUAL", "bidirectional", "top", 5.08)

    assert store.writes == []
    assert "02_mcu" in report
    assert "moved" in report.casefold() or "resized" in report.casefold()


ROOT_TEXT_WITH_RIGHT_EDGE_INPUT = """(kicad_sch
\t(sheet
\t\t(at 80.01 30.48)
\t\t(size 30.48 20.32)
\t\t(property "Sheetname" "02_mcu"
\t\t\t(at 80.01 29.77 0)
\t\t)
\t\t(property "Sheetfile" "child.kicad_sch"
\t\t\t(at 80.01 51.38 0)
\t\t)
\t\t(pin "VIN" input
\t\t\t(at 110.49 33.02 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify right)
\t\t\t)
\t\t\t(uuid "keep-uuid")
\t\t)
\t\t(instances
\t\t\t(project "main" (path "/1" (page "2")))
\t\t)
\t)
)
"""
"""An `input` pin on the right edge -- what ``sch_add_sheet_pin(edge="right")``
writes. The import layout puts inputs on the left, so this pin is relocated."""

VIN_ONLY_CHILD_TEXT = '(hierarchical_label "VIN"\n\t(shape input)\n\t(at 1 2 0)\n)\n'


def test_import_sheet_pins_reports_a_repositioned_pin_as_moved(tmp_path: Path) -> None:
    store = _TextStore(
        {"root.kicad_sch": ROOT_TEXT_WITH_RIGHT_EDGE_INPUT, "child.kicad_sch": VIN_ONLY_CHILD_TEXT}
    )
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.import_sheet_pins(None, True, False)

    written = store.files["root.kicad_sch"]
    assert "(at 80.01 33.02 180)" in written
    assert "- 02_mcu: 0 added, 0 retyped, 1 moved, 0 unchanged" in report
    assert "1 unchanged" not in report


def test_import_sheet_pins_omits_per_sheet_lines_when_nothing_was_written(
    tmp_path: Path,
) -> None:
    """One sheet lacks ``(instances ...)``, so the whole transaction aborts.
    Printing "1 added" for the sibling sheet would describe a write that never
    happened.
    """
    root_text = ROOT_TEXT_TWO_SHEETS.replace(
        '\t\t(instances\n\t\t\t(project "main" (path "/1" (page "3")))\n\t\t)\n', ""
    )
    store = _TextStore(
        {
            "root.kicad_sch": root_text,
            "power.kicad_sch": POWER_CHILD_TEXT,
            "mcu.kicad_sch": CHILD_TEXT,
        }
    )
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.import_sheet_pins(None, True, False)

    assert store.writes == []
    assert "added" not in report
    assert report.startswith("Could not import sheet pins:")
    assert "02_mcu" in report


def test_both_import_failure_paths_have_the_same_shape(tmp_path: Path) -> None:
    """The replay check and the write seam must report failure identically --
    one prefix, one line, no planning lines.
    """
    replay_store = _TextStore(
        {"root.kicad_sch": ROOT_TEXT_NO_ANCHOR, "child.kicad_sch": CHILD_TEXT}
    )
    replay_report = _pin_service(replay_store, tmp_path / "root.kicad_sch").import_sheet_pins(
        None, True, False
    )

    write_store = _GeometryDriftStore(
        {"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT},
        drifted_root_text=ROOT_TEXT_MOVED,
    )
    write_report = _pin_service(write_store, tmp_path / "root.kicad_sch").import_sheet_pins(
        None, True, False
    )

    for report in (replay_report, write_report):
        assert report.startswith("Could not import sheet pins: ")
        assert "\n" not in report


class _VanishingSheetStore(_TextStore):
    """The sheet is gone from the text the write seam hands the mutator."""

    def transactional_write(self, mutator, sch_file=None):  # type: ignore[no-untyped-def]
        name = (sch_file or Path("root.kicad_sch")).name
        if name == "root.kicad_sch":
            self.files[name] = "(kicad_sch\n)\n"
        return super().transactional_write(mutator, sch_file)


def test_import_sheet_pins_reports_a_sheet_that_vanished_before_the_write(
    tmp_path: Path,
) -> None:
    """Silently skipping it would still print "Imported sheet pins." and
    "1 added" for a sheet that was never touched.
    """
    store = _VanishingSheetStore({"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.import_sheet_pins(None, True, False)

    assert "Imported sheet pins." not in report
    assert "added" not in report
    assert "02_mcu" in report
    assert "disappeared" in report


ROOT_TEXT_DEGRADED_SHEET = ROOT_TEXT.replace("\t\t(size 30.48 20.32)\n", "", 1)


def test_import_sheet_pins_distinguishes_an_unusable_sheet_from_a_missing_one(
    tmp_path: Path,
) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT_DEGRADED_SHEET, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    degraded = service.import_sheet_pins("02_mcu", True, False)
    missing = service.import_sheet_pins("nope", True, False)

    assert "not found" not in degraded
    assert "cannot be addressed" in degraded
    assert "size" in degraded
    assert "not found" in missing


def test_add_sheet_pin_warns_when_the_schematic_cannot_be_read(tmp_path: Path) -> None:
    store = _TextStore({})
    warnings: list[tuple[str, dict[str, Any]]] = []
    service = replace(
        _pin_service(store, tmp_path / "root.kicad_sch"),
        warn=lambda event, **fields: warnings.append((event, fields)),
    )

    report = service.add_sheet_pin("02_mcu", "MANUAL", "input", "left", 5.08)

    assert "Could not read" in report
    assert [event for event, _fields in warnings] == ["schematic_add_sheet_pin_unreadable"]


def test_create_sheet_says_pins_were_not_applied_to_an_existing_sheet(tmp_path: Path) -> None:
    root_path = tmp_path / "demo.kicad_sch"
    service, _root, _child, _tx, _warnings = _service(
        root_path=root_path,
        root=_RootSchematic(duplicate=True),
    )

    report = service.create_sheet("Power", "power", 10.0, 20.0, True, (("VIN", "input"),))

    assert "already exists" in report
    assert "no sheet pins were applied" in report


def test_create_sheet_folds_an_unreadable_root_into_its_report(tmp_path: Path) -> None:
    """``_apply_sheet_pins`` documents that it never raises. It runs after the
    sheet is created and saved, outside any ``try`` in ``create_sheet``, so an
    OSError escaping it would fail a call that in fact created the sheet.
    """
    store = _TextStore({"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT})
    warnings: list[tuple[str, dict[str, Any]]] = []

    def _explode(_path: Path) -> str:
        raise OSError("root vanished")

    service = replace(
        _pin_service(store, tmp_path / "root.kicad_sch"),
        read_text=_explode,
        warn=lambda event, **fields: warnings.append((event, fields)),
    )

    report = service.create_sheet(
        "02_mcu", "child.kicad_sch", 80.01, 30.48, True, (("VIN", "input"),)
    )

    assert "was created" in report
    assert "root vanished" in report
    assert [event for event, _fields in warnings] == ["schematic_create_sheet_pins_failed"]


def test_create_sheet_surfaces_the_heuristic_width_note(tmp_path: Path) -> None:
    """The same disclosure sch_import_sheet_pins makes. Without it the tool can
    widen a sheet from an estimated text width and say nothing.
    """
    store = _TextStore({"root.kicad_sch": ROOT_TEXT, "child.kicad_sch": CHILD_TEXT})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.create_sheet(
        "02_mcu",
        "child.kicad_sch",
        80.01,
        30.48,
        True,
        (("A_VERY_LONG_INPUT_SIGNAL_NAME", "input"), ("A_VERY_LONG_OUTPUT_SIGNAL_NAME", "output")),
    )

    assert "heuristic" in report


# ---------------------------------------------------------------------------
# wire_sheet_pins / spread_sheets
# ---------------------------------------------------------------------------

ROOT_TEXT_TWO_SHEETS_WITH_PINS = """(kicad_sch
\t(paper "A4")
\t(sheet
\t\t(at 50.0 30.0)
\t\t(size 20.0 20.0)
\t\t(property "Sheetname" "01_power"
\t\t\t(at 50.0 29.0 0)
\t\t)
\t\t(property "Sheetfile" "power.kicad_sch"
\t\t\t(at 50.0 51.0 0)
\t\t)
\t\t(pin "VBUS" output
\t\t\t(at 70.0 35.0 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify left)
\t\t\t)
\t\t\t(uuid "pin-power-uuid")
\t\t)
\t\t(instances
\t\t\t(project "main" (path "/1" (page "2")))
\t\t)
\t)
\t(sheet
\t\t(at 80.01 30.48)
\t\t(size 30.48 20.32)
\t\t(property "Sheetname" "02_mcu"
\t\t\t(at 80.01 29.77 0)
\t\t)
\t\t(property "Sheetfile" "mcu.kicad_sch"
\t\t\t(at 80.01 51.38 0)
\t\t)
\t\t(pin "VBUS" input
\t\t\t(at 80.01 45.0 180)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify right)
\t\t\t)
\t\t\t(uuid "pin-mcu-uuid")
\t\t)
\t\t(instances
\t\t\t(project "main" (path "/1" (page "3")))
\t\t)
\t)
)
"""
"""Two sheets, each with one pin named ``VBUS`` -- a matching pair. The two
pins sit on different rows (y=35 vs y=45) so their local labels never overlap
and the collision check stays quiet."""


def test_wire_sheet_pins_adds_one_stub_and_one_label_per_pin(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT_TWO_SHEETS_WITH_PINS})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.wire_sheet_pins(None, 2.54, False)

    written = store.files["root.kicad_sch"]
    assert written.count("(wire ") == 2
    assert written.count("(label ") == 2
    assert '(label "VBUS"' in written
    assert len(store.writes) == 1
    assert "2" in report


def test_wire_sheet_pins_is_a_no_op_on_the_second_run(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT_TWO_SHEETS_WITH_PINS})
    service = _pin_service(store, tmp_path / "root.kicad_sch")
    service.wire_sheet_pins(None, 2.54, False)
    after_first = store.files["root.kicad_sch"]

    report = service.wire_sheet_pins(None, 2.54, False)

    assert len(store.writes) == 1
    assert store.files["root.kicad_sch"] == after_first
    assert "already" in report.casefold()


def test_wire_sheet_pins_dry_run_writes_nothing(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT_TWO_SHEETS_WITH_PINS})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.wire_sheet_pins(None, 2.54, True)

    assert store.writes == []
    assert "(wire " not in store.files["root.kicad_sch"]
    assert "dry run" in report.casefold()


def test_wire_sheet_pins_restricts_writes_to_the_named_sheet(tmp_path: Path) -> None:
    """``sheet`` limits *which sheet's pins get a new stub and label* -- a
    version that ignored the argument would wire both sheets and this test
    would not notice from a bare count alone, so it also asserts the untouched
    sheet's own pin block survives byte-for-byte.
    """
    store = _TextStore({"root.kicad_sch": ROOT_TEXT_TWO_SHEETS_WITH_PINS})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    service.wire_sheet_pins("01_power", 2.54, False)

    written = store.files["root.kicad_sch"]
    assert written.count("(wire ") == 1
    assert written.count("(label ") == 1
    # The stub starts exactly on 01_power's own pin -- never on 02_mcu's.
    assert "(xy 70.0 35.0)" in written
    assert "(xy 80.01 45.0)" not in written
    # 02_mcu's own (pin "VBUS" ...) block, in full, is byte-identical to the
    # source text -- not merely "no wire near it", but untouched outright.
    assert (
        '\t\t(pin "VBUS" input\n'
        "\t\t\t(at 80.01 45.0 180)\n"
        "\t\t\t(effects\n"
        "\t\t\t\t(font\n"
        "\t\t\t\t\t(size 1.27 1.27)\n"
        "\t\t\t\t)\n"
        "\t\t\t\t(justify right)\n"
        "\t\t\t)\n"
        '\t\t\t(uuid "pin-mcu-uuid")\n'
        "\t\t)\n"
    ) in written


ROOT_TEXT_ONE_SHEET_ONE_PIN = """(kicad_sch
\t(paper "A4")
\t(sheet
\t\t(at 80.01 30.48)
\t\t(size 30.48 20.32)
\t\t(property "Sheetname" "02_mcu"
\t\t\t(at 80.01 29.77 0)
\t\t)
\t\t(property "Sheetfile" "child.kicad_sch"
\t\t\t(at 80.01 51.38 0)
\t\t)
\t\t(pin "LONELY" input
\t\t\t(at 80.01 35.0 180)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify right)
\t\t\t)
\t\t\t(uuid "lonely-uuid")
\t\t)
\t\t(instances
\t\t\t(project "main" (path "/1" (page "2")))
\t\t)
\t)
)
"""
"""One sheet with one pin ("LONELY") that has no matching pin anywhere else in
the document -- its stub-and-label would connect to nothing."""


def test_wire_sheet_pins_orphan_report_does_not_claim_unselected_pins_were_wired(
    tmp_path: Path,
) -> None:
    text = ROOT_TEXT_TWO_SHEETS_WITH_PINS.replace(
        '(pin "VBUS" output', '(pin "POWER_ONLY" output', 1
    ).replace('(pin "VBUS" input', '(pin "MCU_ONLY" input', 1)
    store = _TextStore({"root.kicad_sch": text})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.wire_sheet_pins("01_power", 2.54, False)

    assert "Pins with no match on another sheet: MCU_ONLY, POWER_ONLY." in report
    assert "wired anyway" not in report


def test_wire_sheet_pins_reports_an_orphan_name(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT_ONE_SHEET_ONE_PIN})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.wire_sheet_pins(None, 2.54, False)

    assert "LONELY" in report


ROOT_TEXT_SPREAD_TWO_COLUMNS = """(kicad_sch
\t(paper "A4")
\t(sheet
\t\t(at 0.0 0.0)
\t\t(size 20.0 20.0)
\t\t(property "Sheetname" "01_left"
\t\t\t(at 0.0 -1.0 0)
\t\t)
\t\t(property "Sheetfile" "left.kicad_sch"
\t\t\t(at 0.0 21.0 0)
\t\t)
\t\t(instances
\t\t\t(project "main" (path "/1" (page "2")))
\t\t)
\t)
\t(sheet
\t\t(at 25.0 0.0)
\t\t(size 20.0 20.0)
\t\t(property "Sheetname" "02_right"
\t\t\t(at 25.0 -1.0 0)
\t\t)
\t\t(property "Sheetfile" "right.kicad_sch"
\t\t\t(at 25.0 21.0 0)
\t\t)
\t\t(pin "OUT" output
\t\t\t(at 45.0 10.0 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify left)
\t\t\t)
\t\t\t(uuid "pin-out-uuid")
\t\t)
\t\t(instances
\t\t\t(project "main" (path "/1" (page "3")))
\t\t)
\t)
)
"""
"""Two columns 5 mm apart (20 -> 25). A ``min_gap_mm`` bigger than that forces
column 2 (with its one pin) to move right by a computed, grid-snapped ``dx``.
Column 1 has no pin, so it is never in the shift map and its ``(at 0.0 0.0)``
must survive untouched."""

ROOT_TEXT_SPREAD_WITH_BROKEN_PIN = """(kicad_sch
\t(paper "A4")
\t(sheet
\t\t(at 0.0 0.0)
\t\t(size 20.0 20.0)
\t\t(property "Sheetname" "01_left"
\t\t\t(at 0.0 -1.0 0)
\t\t)
\t\t(property "Sheetfile" "left.kicad_sch"
\t\t\t(at 0.0 21.0 0)
\t\t)
\t\t(instances
\t\t\t(project "main" (path "/1" (page "2")))
\t\t)
\t)
\t(sheet
\t\t(at 25.0 0.0)
\t\t(size 20.0 20.0)
\t\t(property "Sheetname" "02_right"
\t\t\t(at 25.0 -1.0 0)
\t\t)
\t\t(property "Sheetfile" "right.kicad_sch"
\t\t\t(at 25.0 21.0 0)
\t\t)
\t\t(pin "OUT" output
\t\t\t(at 45.0 10.0 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify left)
\t\t\t)
\t\t\t(uuid "pin-out-uuid")
\t\t)
\t\t(pin "BROKEN" input
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(justify right)
\t\t\t)
\t\t\t(uuid "broken-uuid")
\t\t)
\t\t(instances
\t\t\t(project "main" (path "/1" (page "3")))
\t\t)
\t)
)
"""
"""Same as ``ROOT_TEXT_SPREAD_TWO_COLUMNS``, but ``02_right`` has a second pin,
``BROKEN``, with no ``(at ...)`` node at all -- ``_scan_sheet_blocks`` records a
zero-width span for it. ``spread_sheets`` must leave it alone rather than
splice at that zero-width span, which would insert a spurious ``(at ...)``
instead of replacing one."""

_SPREAD_PIN_EFFECTS_AND_UUID = (
    "\t\t\t(effects\n"
    "\t\t\t\t(font\n"
    "\t\t\t\t\t(size 1.27 1.27)\n"
    "\t\t\t\t)\n"
    "\t\t\t\t(justify left)\n"
    "\t\t\t)\n"
    '\t\t\t(uuid "pin-out-uuid")'
)


def test_spread_sheets_rewrites_only_at_nodes(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT_SPREAD_TWO_COLUMNS})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    service.spread_sheets(10.0, 2.54, False)

    written = store.files["root.kicad_sch"]
    parsed = {block.name: block for block in parse_sheet_blocks(written)}

    left = parsed["01_left"]
    right = parsed["02_right"]
    assert left.origin == (0.0, 0.0)

    dx = right.origin[0] - 25.0
    assert dx > 0
    assert right.pins[0].x_mm - 45.0 == dx
    assert right.pins[0].y_mm == 10.0
    assert right.pins[0].rotation == 0

    # Everything else about the pin -- its (effects ...) and (uuid ...) -- is
    # byte-identical to the source text; only the (at ...) node was rewritten.
    assert _SPREAD_PIN_EFFECTS_AND_UUID in written


def test_spread_sheets_refuses_when_a_pin_is_already_wired(tmp_path: Path) -> None:
    wired_text = ROOT_TEXT_SPREAD_TWO_COLUMNS.replace(
        "\t(sheet\n\t\t(at 0.0 0.0)",
        "\t(wire\n\t\t(pts (xy 45.0 10.0) (xy 48.0 10.0))\n\t\t(stroke (width 0) (type solid))\n"
        '\t\t(uuid "existing-wire-uuid")\n\t)\n\t(sheet\n\t\t(at 0.0 0.0)',
    )
    store = _TextStore({"root.kicad_sch": wired_text})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.spread_sheets(10.0, 2.54, False)

    assert store.writes == []
    assert "02_right" in report


def test_spread_sheets_does_not_treat_a_nearby_wire_as_attached(tmp_path: Path) -> None:
    text = ROOT_TEXT_SPREAD_TWO_COLUMNS.replace(
        "(at 45.0 10.0 0)",
        "(at 45.0004 10.0 0)",
        1,
    ).replace(
        "\t(sheet\n\t\t(at 0.0 0.0)",
        "\t(wire (pts (xy 45.00049 10.0) (xy 48.0 10.0)))\n\t(sheet\n\t\t(at 0.0 0.0)",
        1,
    )
    store = _TextStore({"root.kicad_sch": text})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.spread_sheets(10.0, 2.54, False)

    assert len(store.writes) == 1
    assert "Spread 1 sheet(s): 02_right." in report


def test_spread_sheets_uses_portrait_page_width_for_overflow(tmp_path: Path) -> None:
    text = ROOT_TEXT_SPREAD_TWO_COLUMNS.replace('(paper "A4")', '(paper "A4" portrait)', 1)
    store = _TextStore({"root.kicad_sch": text})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.spread_sheets(180.0, 2.54, False)

    assert store.writes == []
    assert "Nothing was moved." in report
    assert "past the usable edge" in report


def test_spread_sheets_refuses_to_push_past_the_page_edge(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT_SPREAD_TWO_COLUMNS})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.spread_sheets(1000.0, 2.54, False)

    assert store.writes == []
    assert "usable" in report.casefold() or "past" in report.casefold()


def test_spread_sheets_skips_a_pin_with_no_readable_at_node(tmp_path: Path) -> None:
    store = _TextStore({"root.kicad_sch": ROOT_TEXT_SPREAD_WITH_BROKEN_PIN})
    service = _pin_service(store, tmp_path / "root.kicad_sch")

    report = service.spread_sheets(10.0, 2.54, False)

    written = store.files["root.kicad_sch"]
    # The document must still parse cleanly -- the strongest evidence that the
    # zero-width span was not spliced into.
    parsed = {block.name: block for block in parse_sheet_blocks(written)}
    right = parsed["02_right"]
    out_pin = next(pin for pin in right.pins if pin.name == "OUT")
    broken_pin = next(pin for pin in right.pins if pin.name == "BROKEN")

    dx = right.origin[0] - 25.0
    assert dx > 0
    # OUT still moved normally...
    assert out_pin.x_mm - 45.0 == dx
    # ...but BROKEN's block -- including its now-absent (at ...) -- is
    # untouched: no (at ...) was inserted for it.
    assert '\t\t(pin "BROKEN" input\n\t\t\t(effects\n' in written
    assert broken_pin.x_mm == 0.0
    assert broken_pin.y_mm == 0.0
    assert "BROKEN" in report
    assert "02_right" in report


def test_both_methods_write_once_for_all_sheets(tmp_path: Path) -> None:
    wiring_store = _TextStore({"root.kicad_sch": ROOT_TEXT_TWO_SHEETS_WITH_PINS})
    wiring_service = _pin_service(wiring_store, tmp_path / "root.kicad_sch")

    wiring_service.wire_sheet_pins(None, 2.54, False)

    assert len(wiring_store.writes) == 1

    spread_store = _TextStore({"root.kicad_sch": ROOT_TEXT_SPREAD_TWO_COLUMNS})
    spread_service = _pin_service(spread_store, tmp_path / "root.kicad_sch")

    spread_service.spread_sheets(10.0, 2.54, False)

    assert len(spread_store.writes) == 1
