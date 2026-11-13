"""Pure saved-file acceptance contract; no KiCad, Cloud or Windows side effects."""

from __future__ import annotations

import pytest

from kicad_mcp.cloud_native_write_dispatch import _saved_disk_move_matches

REF = "R1"


def board(*, x: float = 3.5, y: float = 4.25, angle: float = 0) -> str:
    return (
        '(kicad_pcb\n  (footprint "Test:R"\n    (layer "F.Cu")\n'
        f"    (at {x} {y} {angle})\n"
        '    (property "Reference" "R1")\n  )\n)\n'
    )


@pytest.mark.parametrize(
    ("x", "y", "angle", "expected", "accepted"),
    [
        (3.5, 4.25, 0, None, True),
        (3.5, 4.25, 90, 90.0, True),
        (3.5, 4.25, -270, 90.0, True),
        (3.5, 4.25, 0, 90.0, False),
        (9.0, 4.25, 0, None, False),
        (3.5, 9.0, 0, None, False),
    ],
)
def test_saved_board_pins_exact_position_and_rotation(
    x: float, y: float, angle: float, expected: float | None, accepted: bool
) -> None:
    command = {"xMm": 3.5, "yMm": 4.25, "rotationDeg": expected}
    assert _saved_disk_move_matches(board(x=x, y=y, angle=angle), REF, command) is accepted


def test_saved_board_refuses_ambiguous_or_missing_footprints() -> None:
    command = {"xMm": 3.5, "yMm": 4.25, "rotationDeg": None}
    assert _saved_disk_move_matches(board() + board(), REF, command) is False
    assert _saved_disk_move_matches("(kicad_pcb)", REF, command) is False
