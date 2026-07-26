from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from kicad_mcp.schematic.layout_automation import (
    SchematicLayoutAutomationService,
    SchematicLike,
)


@dataclass(frozen=True)
class FakeDesignIntent:
    functional_spacing_mm: float


class FakeComponent:
    def __init__(self) -> None:
        self.moves: list[tuple[float, float]] = []

    def move(self, x: float, y: float) -> None:
        self.moves.append((x, y))


class FakeComponents:
    def __init__(self, values: dict[str, FakeComponent]) -> None:
        self.values = values

    def get(self, reference: str) -> FakeComponent | None:
        return self.values.get(reference)


class FakeSchematic:
    def __init__(
        self,
        values: dict[str, FakeComponent] | None = None,
        *,
        save_error: Exception | None = None,
    ) -> None:
        self.components = FakeComponents(values or {})
        self.save_error = save_error
        self.saved: list[tuple[Path, bool]] = []

    def save(self, path: Path, *, preserve_format: bool) -> None:
        if self.save_error is not None:
            raise self.save_error
        self.saved.append((path, preserve_format))


def _service(
    schematic_file: Path,
    *,
    loaded: FakeSchematic | Exception | None = None,
    parsed: dict[str, Any] | None = None,
    warnings: list[tuple[str, dict[str, Any]]] | None = None,
    next_cells: list[tuple[float, float]] | None = None,
    visual_reports: list[dict[str, Any]] | None = None,
    field_builder: Callable[..., tuple[Callable[[str], str], list[str], list[str]]] | None = None,
    transactional_calls: list[tuple[Path, Callable[[str], str]]] | None = None,
    resize_calls: list[tuple[Path, str]] | None = None,
    respace_result: list[str] | None = None,
    field_apply_result: list[str] | None = None,
    reload_calls: list[bool] | None = None,
    normalized_anchors: list[str] | None = None,
    paper: str = "A4",
    usable_cols: int = 9,
    usable_rows: int = 9,
    functional_origin: tuple[int, int] = (0, 0),
    functional_spacing_mm: float = 12.7,
) -> SchematicLayoutAutomationService:
    loaded_value = loaded if loaded is not None else FakeSchematic()
    parsed_value = parsed or {"symbols": [], "power_symbols": []}
    warning_log = warnings if warnings is not None else []
    cell_values = list(next_cells or [(25.4, 17.78)])
    report_values = list(visual_reports or [{"status": "PASS", "findings": []}])
    transaction_log = transactional_calls if transactional_calls is not None else []
    resize_log = resize_calls if resize_calls is not None else []
    reload_log = reload_calls if reload_calls is not None else []

    def load_schematic(_path: Path) -> SchematicLike:
        if isinstance(loaded_value, Exception):
            raise loaded_value
        return loaded_value

    def next_free_cell(_occupied: set[tuple[int, int]], **_kwargs: object) -> tuple[float, float]:
        return cell_values.pop(0) if cell_values else (25.4, 17.78)

    def run_visual_qa(_text: str) -> dict[str, Any]:
        if len(report_values) > 1:
            return report_values.pop(0)
        return report_values[0]

    def default_field_builder(
        _path: Path, _references: list[str] | None
    ) -> tuple[Callable[[str], str], list[str], list[str]]:
        return (lambda current: current + "-updated", ["R1"], ["R1"])

    def reload_schematic() -> str:
        reload_log.append(True)
        return "Reloaded"

    def resize_sheet_apply(path: Path, target: str) -> bool:
        resize_log.append((path, target))
        return True

    def load_design_intent() -> FakeDesignIntent:
        return FakeDesignIntent(functional_spacing_mm=functional_spacing_mm)

    def classify_symbol(*, ref: str, value: str, lib_id: str) -> str:
        del ref, value, lib_id
        return "passive"

    def functional_zone_origin(
        category: str,
        *,
        max_cols: int,
        max_rows: int,
        spacing_mm: float,
    ) -> tuple[int, int]:
        del category, max_cols, max_rows, spacing_mm
        return functional_origin

    def warn(event: str, **payload: object) -> None:
        warning_log.append((event, dict(payload)))

    return SchematicLayoutAutomationService(
        active_schematic_file=lambda: schematic_file,
        load_schematic=load_schematic,
        parse_schematic=lambda _path: parsed_value,
        with_diagnostics=lambda message, path: f"diag:{path.name}:{message}",
        estimate_occupied_cells=lambda symbols: {(len(symbols), 0)} if symbols else set(),
        next_free_cell=next_free_cell,
        snap_point=lambda x, y, _enabled: (x + 0.1, y + 0.2),
        reload_schematic=reload_schematic,
        build_autoplace_fields_mutator=field_builder or default_field_builder,
        transactional_write_to_schematic_file=lambda path, mutator: transaction_log.append(
            (path, mutator)
        ),
        run_visual_qa=run_visual_qa,
        read_sheet_paper=lambda _path: paper,
        paper_ladder=("A4", "A3", "A2", "A1", "A0"),
        resize_sheet_apply=resize_sheet_apply,
        schematic_has_connections=lambda _text: False,
        respace_symbols_apply=lambda _path: list(respace_result or []),
        autoplace_fields_apply=lambda _path: list(field_apply_result or []),
        load_design_intent=load_design_intent,
        normalize_anchor_refs=lambda _anchor: list(normalized_anchors or []),
        sheet_usable_cols=lambda _paper: usable_cols,
        sheet_usable_rows=lambda _paper: usable_rows,
        paper_sizes_mm={"A4": (297.0, 210.0), "A3": (420.0, 297.0)},
        classify_symbol=classify_symbol,
        functional_zone_origin=functional_zone_origin,
        functional_zones=("passive", "connector"),
        zone_max_cols=3,
        auto_layout_origin_x_mm=25.4,
        auto_layout_origin_y_mm=17.78,
        auto_layout_column_spacing_mm=25.4,
        auto_layout_row_spacing_mm=17.78,
        warn=warn,
    )


def test_auto_place_symbols_reports_load_failure(tmp_path: Path) -> None:
    schematic_file = tmp_path / "board.kicad_sch"
    warnings: list[tuple[str, dict[str, Any]]] = []
    service = _service(
        schematic_file,
        loaded=RuntimeError("broken"),
        warnings=warnings,
    )

    result = service.auto_place_symbols(["R1"], "grid")

    assert result == "Could not load the active schematic for auto-placement: broken"
    assert warnings == [
        (
            "schematic_auto_place_load_failed",
            {"schematic_file": str(schematic_file), "error": "broken"},
        )
    ]


def test_auto_place_symbols_respects_fixed_obstacles_and_reports_missing(tmp_path: Path) -> None:
    schematic_file = tmp_path / "board.kicad_sch"
    r1 = FakeComponent()
    loaded = FakeSchematic({"R1": r1})
    service = _service(
        schematic_file,
        loaded=loaded,
        parsed={
            "symbols": [
                {"reference": "R1"},
                {"reference": "R2", "x": 10.0, "y": 20.0},
            ],
            "power_symbols": [{"reference": "#PWR01", "x": 1.0, "y": 2.0}],
        },
        next_cells=[(50.8, 35.56)],
    )

    result = service.auto_place_symbols(["R1", "R404"], "grid")

    assert r1.moves == [pytest.approx((50.9, 35.76))]
    assert loaded.saved == [(schematic_file, True)]
    assert "Auto-placed 1 symbol(s) using the grid strategy." in result
    assert "respected 2 fixed obstacle(s)" in result
    assert "Missing: R404." in result


def test_auto_place_symbols_reports_save_failure(tmp_path: Path) -> None:
    schematic_file = tmp_path / "board.kicad_sch"
    warnings: list[tuple[str, dict[str, Any]]] = []
    loaded = FakeSchematic({"R1": FakeComponent()}, save_error=OSError("read-only"))
    service = _service(
        schematic_file,
        loaded=loaded,
        parsed={"symbols": [{"reference": "R1"}], "power_symbols": []},
        warnings=warnings,
    )

    result = service.auto_place_symbols(["R1"])

    assert result == "Could not save auto-placement changes: read-only"
    assert warnings[-1] == (
        "schematic_auto_place_save_failed",
        {"schematic_file": str(schematic_file), "error": "read-only"},
    )


def test_autoplace_fields_dry_run_executes_mutator_without_writing(tmp_path: Path) -> None:
    schematic_file = tmp_path / "board.kicad_sch"
    schematic_file.write_text("original", encoding="utf-8")
    mutated: list[str] = []
    transactions: list[tuple[Path, Callable[[str], str]]] = []

    def build(
        _path: Path, references: list[str] | None
    ) -> tuple[Callable[[str], str], list[str], list[str]]:
        assert references == ["R1"]

        def mutator(current: str) -> str:
            mutated.append(current)
            return current + "-updated"

        return mutator, ["R1"], ["R1"]

    service = _service(
        schematic_file,
        field_builder=build,
        transactional_calls=transactions,
    )

    result = service.autoplace_fields(["R1"], dry_run=True)

    assert mutated == ["original"]
    assert transactions == []
    assert result == "Dry run: would reposition Reference/Value fields on 1 symbol(s): R1."


def test_autoplace_fields_writes_and_reloads(tmp_path: Path) -> None:
    schematic_file = tmp_path / "board.kicad_sch"
    transactions: list[tuple[Path, Callable[[str], str]]] = []
    reloads: list[bool] = []
    service = _service(
        schematic_file,
        transactional_calls=transactions,
        reload_calls=reloads,
    )

    result = service.autoplace_fields()

    assert len(transactions) == 1
    assert transactions[0][0] == schematic_file
    assert reloads == [True]
    assert result == "Reloaded\nAuto-placed Reference/Value fields on 1 symbol(s): R1."


def test_autoplace_fields_reports_no_matching_targets(tmp_path: Path) -> None:
    schematic_file = tmp_path / "board.kicad_sch"

    def no_targets(
        _path: Path,
        _references: list[str] | None,
    ) -> tuple[Callable[[str], str], list[str], list[str]]:
        return (lambda value: value, [], [])

    service = _service(
        schematic_file,
        field_builder=no_targets,
    )

    result = service.autoplace_fields(["R9"])

    assert result == "diag:board.kicad_sch:No matching symbols found to auto-place fields for."


def test_fix_readability_applies_available_fixes_until_pass(tmp_path: Path) -> None:
    schematic_file = tmp_path / "board.kicad_sch"
    schematic_file.write_text("sheet", encoding="utf-8")
    resize_calls: list[tuple[Path, str]] = []
    reloads: list[bool] = []
    service = _service(
        schematic_file,
        visual_reports=[
            {
                "status": "FAIL",
                "findings": [
                    {"code": "offsheet_symbol"},
                    {"code": "symbol_overlap"},
                    {"code": "text_overlap"},
                ],
            },
            {"status": "PASS", "findings": []},
        ],
        resize_calls=resize_calls,
        respace_result=["R1", "R2"],
        field_apply_result=["R1"],
        reload_calls=reloads,
    )

    result = service.fix_readability(max_passes=3)

    assert resize_calls == [(schematic_file, "A3")]
    assert reloads == [True]
    assert "Readability fix: FAIL -> PASS over 2 pass(es)." in result
    assert "grew sheet to A3" in result
    assert "re-spaced 2 overlapping symbol(s)" in result
    assert "auto-placed fields on 1 symbol(s)" in result


def test_fix_readability_stops_when_no_safe_fix_exists(tmp_path: Path) -> None:
    schematic_file = tmp_path / "board.kicad_sch"
    schematic_file.write_text("sheet", encoding="utf-8")
    service = _service(
        schematic_file,
        visual_reports=[
            {
                "status": "FAIL",
                "findings": [
                    {"code": "label_overlap"},
                    {"code": "dense_label_fanout"},
                ],
            }
        ],
    )

    result = service.fix_readability(max_passes=0)

    assert "over 1 pass(es)" in result
    assert "No automatic fixes were applied." in result
    assert "dense_label_fanout, label_overlap" in result


def test_auto_place_functional_preserves_anchor_and_reports_missing(tmp_path: Path) -> None:
    schematic_file = tmp_path / "board.kicad_sch"
    r1 = FakeComponent()
    anchor = FakeComponent()
    loaded = FakeSchematic({"R1": r1, "J1": anchor})
    service = _service(
        schematic_file,
        loaded=loaded,
        parsed={
            "symbols": [
                {"reference": "R1", "value": "10k", "lib_id": "Device:R"},
                {"reference": "J1", "value": "Conn", "lib_id": "Connector:Conn_01x02"},
            ],
            "power_symbols": [],
        },
        normalized_anchors=["J1"],
        functional_origin=(1, 2),
    )

    result = service.auto_place_functional(["R1", "J1", "R404"], anchor_ref="J1")

    assert r1.moves == [pytest.approx((50.9, 53.54))]
    assert anchor.moves == []
    assert loaded.saved == [(schematic_file, True)]
    assert "1 symbol(s) placed in 1 zone(s)" in result
    assert "Anchored refs preserved: J1." in result
    assert "Missing refs: R404." in result
    assert "Functional spacing target: 12.70 mm." in result


def test_auto_place_functional_reports_load_failure(tmp_path: Path) -> None:
    service = _service(tmp_path / "board.kicad_sch", loaded=RuntimeError("bad file"))

    assert service.auto_place_functional() == (
        "Could not load the active schematic for functional placement: bad file"
    )


def test_auto_place_functional_reports_overflow(tmp_path: Path) -> None:
    schematic_file = tmp_path / "board.kicad_sch"
    component = FakeComponent()
    loaded = FakeSchematic({"R1": component})
    service = _service(
        schematic_file,
        loaded=loaded,
        parsed={
            "symbols": [{"reference": "R1", "value": "10k", "lib_id": "Device:R"}],
            "power_symbols": [],
        },
        usable_cols=1,
        usable_rows=1,
        functional_origin=(5, 5),
        next_cells=[(1000.0, 1000.0)],
    )

    result = service.auto_place_functional(["R1"])

    assert "WARNING: 1 symbol(s) could not fit within the 'A4' sheet" in result


@pytest.mark.parametrize("strategy", ["cluster", "linear", "star", "grid"])
def test_auto_place_symbols_accepts_all_existing_strategies(tmp_path: Path, strategy: str) -> None:
    schematic_file = tmp_path / "board.kicad_sch"
    component = FakeComponent()
    service = _service(
        schematic_file,
        loaded=FakeSchematic({"R1": component}),
        parsed={"symbols": [{"reference": "R1"}], "power_symbols": []},
    )

    result = service.auto_place_symbols(["R1"], strategy)

    assert f"using the {strategy} strategy" in result
    assert component.moves
