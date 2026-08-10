from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

from kicad_mcp.schematic.topology import SchematicTopologyService


class _SheetManager:
    def __init__(
        self,
        *,
        children: list[dict[str, object]] | None = None,
        sheet_info: dict[str, object] | None = None,
    ) -> None:
        self.children = children or []
        self.sheet_info = sheet_info

    def get_sheet_hierarchy(self) -> dict[str, object]:
        return {"root": {"children": self.children}}

    def get_sheet_by_name(self, sheet_name: str) -> dict[str, object] | None:
        return self.sheet_info if sheet_name == "Power" else None


class _LoadedSchematic:
    def __init__(self, sheets: _SheetManager) -> None:
        self.sheets = sheets


def _service(
    *,
    loaded: _LoadedSchematic | Exception | None = None,
    groups: list[dict[str, Any]] | None = None,
    child_paths: list[tuple[str, Path]] | None = None,
    parsed: dict[Path, dict[str, Any]] | None = None,
    warnings: list[tuple[str, dict[str, object]]] | None = None,
) -> SchematicTopologyService:
    warning_records = warnings if warnings is not None else []

    def load_schematic(_path: Path) -> _LoadedSchematic:
        if isinstance(loaded, Exception):
            raise loaded
        return loaded or _LoadedSchematic(_SheetManager())

    return SchematicTopologyService(
        load_schematic=load_schematic,
        with_diagnostics=lambda message, path: f"{message}\nDiagnostics: {path.name}",
        build_connectivity_groups=lambda _path: groups or [],
        iter_child_sheet_paths=lambda _path: child_paths or [],
        parse_schematic=lambda path: (parsed or {})[path],
        warn=lambda event, **context: warning_records.append((event, context)),
        read_text=lambda _path: (_ for _ in ()).throw(AssertionError("must not read text")),
    )


def test_list_sheets_formats_hierarchy() -> None:
    children = [
        {
            "name": "Power",
            "filename": "power.kicad_sch",
            "position": SimpleNamespace(x=10.0, y=20.0),
            "size": SimpleNamespace(x=50.0, y=30.0),
        }
    ]
    service = _service(loaded=_LoadedSchematic(_SheetManager(children=children)))

    assert service.list_sheets(Path("demo.kicad_sch")) == (
        "Child sheets (1 total):\n- Power -> power.kicad_sch @ (10.00, 20.00) size=(50.00, 30.00)"
    )


def test_list_sheets_preserves_diagnostics_and_warning_on_load_failure() -> None:
    warnings: list[tuple[str, dict[str, object]]] = []
    service = _service(loaded=RuntimeError("broken hierarchy"), warnings=warnings)
    path = Path("demo.kicad_sch")

    assert service.list_sheets(path) == (
        "Could not inspect sheet hierarchy: broken hierarchy\nDiagnostics: demo.kicad_sch"
    )
    assert warnings == [
        (
            "schematic_list_sheets_failed",
            {"schematic_file": "demo.kicad_sch", "error": "broken hierarchy"},
        )
    ]


def test_list_sheets_preserves_empty_hierarchy_diagnostics() -> None:
    service = _service()

    assert service.list_sheets(Path("demo.kicad_sch")) == (
        "The active schematic has no child sheets.\nDiagnostics: demo.kicad_sch"
    )


def test_sheet_info_formats_existing_sheet() -> None:
    info: dict[str, object] = {
        "filename": "power.kicad_sch",
        "position": {"x": 10.0, "y": 20.0},
        "size": {"width": 50.0, "height": 30.0},
        "page_number": "2",
        "pins": [{"name": "VIN"}, {"name": "GND"}],
    }
    service = _service(loaded=_LoadedSchematic(_SheetManager(sheet_info=info)))

    assert service.sheet_info(Path("demo.kicad_sch"), "Power") == (
        "Sheet 'Power'\n"
        "- File: power.kicad_sch\n"
        "- Position: (10.00, 20.00) mm\n"
        "- Size: (50.00, 30.00) mm\n"
        "- Page: 2\n"
        "- Pins: 2"
    )


def test_sheet_info_preserves_missing_and_failure_results() -> None:
    service = _service()
    assert service.sheet_info(Path("demo.kicad_sch"), "Missing") == (
        "Sheet 'Missing' was not found."
    )

    warnings: list[tuple[str, dict[str, object]]] = []
    failing = _service(loaded=RuntimeError("bad sheet"), warnings=warnings)
    assert failing.sheet_info(Path("demo.kicad_sch"), "Power") == (
        "Could not inspect sheet 'Power': bad sheet"
    )
    assert warnings[0][0] == "schematic_get_sheet_info_failed"
    assert warnings[0][1]["sheet_name"] == "Power"


def test_connectivity_graph_formats_named_no_connect_and_unnamed_groups() -> None:
    groups = [
        {
            "names": ["VCC"],
            "pins": [{"reference": "U1", "pin": "1"}],
            "points": [(1.0, 2.0), (3.0, 4.0)],
            "no_connect": False,
        },
        {"names": [], "pins": [], "points": [(5.0, 6.0)], "no_connect": True},
        {"names": [], "pins": [], "points": [(7.0, 8.0)], "no_connect": False},
    ]
    service = _service(groups=groups)

    assert service.connectivity_graph(Path("demo.kicad_sch")) == (
        "Connectivity groups (3 total):\n"
        "- Group 1: VCC | pins=U1:1 | points=2\n"
        "- Group 2: ~no-connect | pins=none | points=1\n"
        "- Group 3: ~unnamed | pins=none | points=1"
    )


def test_connectivity_graph_preserves_empty_diagnostics() -> None:
    service = _service()

    assert service.connectivity_graph(Path("demo.kicad_sch")) == (
        "The active schematic has no connectivity to summarize.\nDiagnostics: demo.kicad_sch"
    )


def test_trace_net_combines_top_level_and_child_sheet_matches(tmp_path: Path) -> None:
    child = tmp_path / "power.kicad_sch"
    child.write_text("(kicad_sch)\n", encoding="utf-8")
    groups = [
        {
            "names": ["VCC"],
            "pins": [
                {"reference": "U1", "pin": "1"},
                {"reference": "C1", "pin": "1"},
            ],
            "points": [(1.0, 2.0), (3.0, 4.0)],
            "no_connect": False,
        }
    ]
    parsed = {
        child: {
            "labels": [{"name": "VCC"}],
            "power_symbols": [{"value": "VCC"}, {"value": "GND"}],
        }
    }
    service = _service(
        groups=groups,
        child_paths=[("Power", child)],
        parsed=parsed,
    )

    assert service.trace_net(Path("demo.kicad_sch"), "VCC") == (
        "Trace for net 'VCC':\n"
        "- Top level match 1: pins=U1:1, C1:1 points=2\n"
        "Child sheet matches:\n"
        "- Power: labels=1 power_symbols=1"
    )


def test_trace_net_preserves_not_found_result(tmp_path: Path) -> None:
    missing_child = tmp_path / "missing.kicad_sch"
    service = _service(child_paths=[("Missing", missing_child)])

    assert service.trace_net(Path("demo.kicad_sch"), "NOPE") == (
        "Net 'NOPE' was not found in the active schematic or child sheets."
    )
