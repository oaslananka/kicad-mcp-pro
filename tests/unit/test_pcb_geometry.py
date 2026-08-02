from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from kicad_mcp.pcb.geometry import (
    BoardGeometryError,
    point_xy_mm,
    track_segment_length_mm,
)


def _point_nm(x_nm: object, y_nm: object) -> SimpleNamespace:
    return SimpleNamespace(x_nm=x_nm, y_nm=y_nm)


def _point_native(x: object, y: object) -> SimpleNamespace:
    return SimpleNamespace(x=x, y=y)


@pytest.mark.parametrize(
    ("point", "expected"),
    [
        (_point_nm(1_250_000, -2_500_000), (1.25, -2.5)),
        (_point_native(300_000, 400_000), (0.3, 0.4)),
    ],
)
def test_point_xy_mm_uses_canonical_coordinate_conversion(
    point: object,
    expected: tuple[float, float],
) -> None:
    assert point_xy_mm(point) == pytest.approx(expected, abs=1e-12)


def test_point_xy_mm_rejects_malformed_points() -> None:
    with pytest.raises(BoardGeometryError, match="Could not read point geometry"):
        point_xy_mm(SimpleNamespace(x_nm=1))


@pytest.mark.parametrize(
    ("start", "end", "expected_mm"),
    [
        (_point_nm(0, 0), _point_nm(3_000_000, 0), 3.0),
        (_point_nm(0, 0), _point_nm(0, 4_000_000), 4.0),
        (_point_nm(0, 0), _point_nm(3_000_000, 4_000_000), 5.0),
        (_point_nm(1_000_000, -2_000_000), _point_nm(1_000_000, -2_000_000), 0.0),
        (_point_native(0, 0), _point_native(300_000, 400_000), 0.5),
    ],
)
def test_track_segment_length_mm_uses_explicit_start_end_nanometre_geometry(
    start: object,
    end: object,
    expected_mm: float,
) -> None:
    track = SimpleNamespace(start=start, end=end)

    assert track_segment_length_mm(track) == pytest.approx(expected_mm, abs=1e-12)


def test_track_segment_length_mm_preserves_sub_nanometre_conversion_precision() -> None:
    track = SimpleNamespace(
        start=_point_nm(0, 0),
        end=_point_nm(1, 1),
    )

    assert track_segment_length_mm(track) == pytest.approx(2**0.5 / 1_000_000, abs=1e-15)


@pytest.mark.parametrize(
    "track",
    [
        SimpleNamespace(start=_point_nm(0, 0)),
        SimpleNamespace(start=_point_nm(0, 0), end=SimpleNamespace(x_nm=1)),
        SimpleNamespace(start=_point_nm(0, 0), end=_point_nm("invalid", 1)),
        SimpleNamespace(start=_point_nm(0, 0), end=_point_nm(float("inf"), 1)),
    ],
)
def test_track_segment_length_mm_rejects_malformed_segment_tracks(track: object) -> None:
    with pytest.raises(BoardGeometryError, match="Could not read segment track start/end geometry"):
        track_segment_length_mm(track)


def test_track_segment_length_matches_legacy_analysis_and_routing_tolerance() -> None:
    start = _point_nm(101, -203)
    end = _point_nm(2_345_679, 8_765_431)
    track = SimpleNamespace(start=start, end=end)
    dx_nm = end.x_nm - start.x_nm
    dy_nm = end.y_nm - start.y_nm
    legacy_analysis_mm = math.hypot(dx_nm, dy_nm) / 1_000_000
    legacy_routing_mm = int(round(math.hypot(dx_nm, dy_nm))) / 1_000_000
    canonical_mm = track_segment_length_mm(track)

    assert canonical_mm == pytest.approx(legacy_analysis_mm, abs=1e-12)
    assert abs(canonical_mm - legacy_routing_mm) <= 0.5 / 1_000_000


def test_analysis_modules_import_the_same_canonical_length_function() -> None:
    from kicad_mcp.tools import emc_compliance, power_integrity, routing, signal_integrity

    for module in (emc_compliance, power_integrity, routing, signal_integrity):
        assert module.track_segment_length_mm is track_segment_length_mm


def test_analysis_modules_import_the_same_canonical_point_function() -> None:
    from kicad_mcp.tools import emc_compliance, power_integrity, signal_integrity

    for module in (emc_compliance, power_integrity, signal_integrity):
        assert module.point_xy_mm is point_xy_mm


def test_analysis_modules_do_not_bypass_canonical_point_conversion() -> None:
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    modules = (
        "src/kicad_mcp/tools/emc_compliance.py",
        "src/kicad_mcp/tools/power_integrity.py",
        "src/kicad_mcp/tools/routing.py",
        "src/kicad_mcp/tools/signal_integrity.py",
    )

    for relative_path in modules:
        source = (repo_root / relative_path).read_text(encoding="utf-8")
        assert "_coord_nm" not in source, relative_path


def test_analysis_modules_do_not_redefine_footprint_position_conversion() -> None:
    import ast
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    modules = (
        "src/kicad_mcp/tools/emc_compliance.py",
        "src/kicad_mcp/tools/power_integrity.py",
        "src/kicad_mcp/tools/signal_integrity.py",
    )

    for relative_path in modules:
        tree = ast.parse((repo_root / relative_path).read_text(encoding="utf-8"))
        definitions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "_footprint_position_mm" not in definitions, relative_path


def test_analysis_modules_do_not_redefine_track_segment_length() -> None:
    import ast
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    modules = (
        "src/kicad_mcp/tools/emc_compliance.py",
        "src/kicad_mcp/tools/power_integrity.py",
        "src/kicad_mcp/tools/routing.py",
        "src/kicad_mcp/tools/signal_integrity.py",
    )

    for relative_path in modules:
        tree = ast.parse((repo_root / relative_path).read_text(encoding="utf-8"))
        definitions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert "_track_length_mm" not in definitions, relative_path


def test_architecture_checker_tracks_canonical_pcb_geometry_module() -> None:
    from scripts import check_architecture_boundaries as boundaries

    assert "kicad_mcp.pcb.geometry" in boundaries.DOMAIN_MODULES
    assert "kicad_mcp.pcb.geometry" in boundaries.PURE_HELPERS
