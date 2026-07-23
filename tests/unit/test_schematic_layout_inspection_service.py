from __future__ import annotations

from pathlib import Path
from typing import Any

from kicad_mcp.schematic.layout_inspection import SchematicLayoutInspectionService


class _Recorder:
    def __init__(self) -> None:
        self.path = Path("/project/demo.kicad_sch")
        self.parsed: dict[str, Any] = {"symbols": [], "power_symbols": []}
        self.diagnostics: list[tuple[str, Path]] = []
        self.bbox_refs: list[str] = []
        self.occupied_inputs: list[tuple[list[dict[str, Any]], float, float]] = []
        self.keepout_inputs: list[tuple[list[tuple[float, float, float, float]], float, float]] = []
        self.next_inputs: list[tuple[set[tuple[int, int]], float, float]] = []
        self.next_values: list[tuple[float, float]] = [(25.4, 25.4)]

    def active_schematic_file(self) -> Path:
        return self.path

    def parse_schematic(self, path: Path) -> dict[str, Any]:
        assert path == self.path
        return self.parsed

    def with_diagnostics(self, text: str, path: Path) -> str:
        self.diagnostics.append((text, path))
        return f"diagnostic:{text}"

    def symbol_bbox_bounds(self, symbol: dict[str, Any]) -> tuple[float, float, float, float]:
        ref = str(symbol["reference"])
        self.bbox_refs.append(ref)
        return {
            "U1": (8.0, 18.0, 12.0, 22.0),
            "#PWR01": (28.0, 38.0, 32.0, 42.0),
        }[ref]

    def estimate_occupied_cells(
        self,
        symbols: list[dict[str, Any]],
        cell_w: float,
        cell_h: float,
    ) -> set[tuple[int, int]]:
        self.occupied_inputs.append((symbols, cell_w, cell_h))
        return {(0, 0)}

    def keepout_occupied_cells(
        self,
        keepout_regions: list[tuple[float, float, float, float]],
        *,
        cell_w: float,
        cell_h: float,
    ) -> set[tuple[int, int]]:
        self.keepout_inputs.append((keepout_regions, cell_w, cell_h))
        return {(2, 3)}

    def next_free_cell(
        self,
        occupied: set[tuple[int, int]],
        cell_w: float,
        cell_h: float,
    ) -> tuple[float, float]:
        self.next_inputs.append((set(occupied), cell_w, cell_h))
        value = self.next_values.pop(0)
        occupied.add((len(self.next_inputs), len(self.next_inputs)))
        return value


def _service(recorder: _Recorder) -> SchematicLayoutInspectionService:
    return SchematicLayoutInspectionService(
        active_schematic_file=recorder.active_schematic_file,
        parse_schematic=recorder.parse_schematic,
        with_diagnostics=recorder.with_diagnostics,
        symbol_bbox_bounds=recorder.symbol_bbox_bounds,
        estimate_occupied_cells=recorder.estimate_occupied_cells,
        keepout_occupied_cells=recorder.keepout_occupied_cells,
        next_free_cell=recorder.next_free_cell,
    )


def test_bounding_boxes_for_empty_schematic_preserves_diagnostics() -> None:
    recorder = _Recorder()

    assert _service(recorder).bounding_boxes() == (
        "diagnostic:The active schematic contains no symbols."
    )
    assert recorder.diagnostics == [("The active schematic contains no symbols.", recorder.path)]


def test_bounding_boxes_preserves_order_table_and_occupied_summary() -> None:
    recorder = _Recorder()
    recorder.parsed = {
        "symbols": [{"reference": "U1", "value": "Microcontroller-long", "x": 10.0, "y": 20.0}],
        "power_symbols": [{"reference": "#PWR01", "value": "VCC", "x_mm": 30.0, "y_mm": 40.0}],
    }

    result = _service(recorder).bounding_boxes()

    assert result == "\n".join(
        [
            "Schematic bounding boxes (2 symbols):",
            "Ref        Value                   X        Y    X_min    Y_min    X_max    Y_max",
            "----------------------------------------------------------------------------",
            "U1         Microcontroller-    10.00    20.00     8.00    18.00    12.00    22.00",
            "#PWR01     VCC                 30.00    40.00    28.00    38.00    32.00    42.00",
            "",
            "Sheet occupied region: X=[8.0, 32.0] Y=[18.0, 42.0] mm",
            "Tip: use sch_find_free_placement to get safe coordinates for new symbols.",
        ]
    )
    assert recorder.bbox_refs == ["U1", "#PWR01"]


def test_free_placement_clamps_low_count_and_uses_default_empty_keepouts() -> None:
    recorder = _Recorder()
    recorder.parsed = {"symbols": [{"reference": "R1"}], "power_symbols": []}

    result = _service(recorder).free_placement(
        count=0,
        cell_width_mm=25.4,
        cell_height_mm=17.78,
        keepout_regions=None,
    )

    assert result == "\n".join(
        [
            "Free placement coordinates (1 slot(s) requested, "
            "1 existing symbol(s) avoided, 0 keepout region(s) respected):",
            "  Slot 1: x_mm=25.4, y_mm=25.4",
            "\nPass these coordinates directly to sch_add_symbol(x_mm=..., y_mm=...).",
        ]
    )
    assert recorder.keepout_inputs == []
    assert recorder.occupied_inputs[0][1:] == (25.4, 17.78)


def test_free_placement_respects_keepouts_allocates_sequentially_and_rounds() -> None:
    recorder = _Recorder()
    symbols = [{"reference": "R1"}, {"reference": "#PWR01"}]
    recorder.parsed = {"symbols": symbols[:1], "power_symbols": symbols[1:]}
    recorder.next_values = [(12.34567, 23.45678), (40.0, 50.0)]
    keepouts = [(1.0, 2.0, 3.0, 4.0)]

    result = _service(recorder).free_placement(
        count=2,
        cell_width_mm=20.0,
        cell_height_mm=10.0,
        keepout_regions=keepouts,
    )

    assert result == "\n".join(
        [
            "Free placement coordinates (2 slot(s) requested, "
            "2 existing symbol(s) avoided, 1 keepout region(s) respected):",
            "  Slot 1: x_mm=12.3457, y_mm=23.4568",
            "  Slot 2: x_mm=40.0, y_mm=50.0",
            "\nPass these coordinates directly to sch_add_symbol(x_mm=..., y_mm=...).",
        ]
    )
    assert recorder.occupied_inputs == [(symbols, 20.0, 10.0)]
    assert recorder.keepout_inputs == [(keepouts, 20.0, 10.0)]
    assert recorder.next_inputs == [
        ({(0, 0), (2, 3)}, 20.0, 10.0),
        ({(0, 0), (1, 1), (2, 3)}, 20.0, 10.0),
    ]


def test_free_placement_clamps_high_count_to_64() -> None:
    recorder = _Recorder()
    recorder.next_values = [(float(index), float(index)) for index in range(64)]

    result = _service(recorder).free_placement(
        count=100,
        cell_width_mm=25.4,
        cell_height_mm=17.78,
        keepout_regions=[],
    )

    assert result.startswith("Free placement coordinates (64 slot(s) requested")
    assert len(recorder.next_inputs) == 64
