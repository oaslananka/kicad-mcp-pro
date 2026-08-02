from __future__ import annotations

from pathlib import Path

from scripts.check_architecture_boundaries import _targeted_helper_definition_errors


def _write(root: Path, relative_path: str, content: str) -> None:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_targeted_helper_guard_reports_duplicate_symbol_and_locations(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    _write(
        source_root,
        "kicad_mcp/pcb/geometry.py",
        "def track_segment_length_mm(track: object) -> float:\n    return 0.0\n",
    )
    _write(
        source_root,
        "kicad_mcp/tools/example.py",
        "def track_segment_length_mm(track: object) -> float:\n    return 1.0\n",
    )

    errors = _targeted_helper_definition_errors(
        source_root,
        canonical_owners={
            "track_segment_length_mm": Path("kicad_mcp/pcb/geometry.py"),
        },
        legacy_replacements={},
    )

    assert errors == [
        "Targeted shared helper 'track_segment_length_mm' must be defined exactly once in "
        "src/kicad_mcp/pcb/geometry.py; found src/kicad_mcp/pcb/geometry.py:1, "
        "src/kicad_mcp/tools/example.py:1. Import the canonical helper or use a distinctly "
        "named domain-specific helper."
    ]


def test_targeted_helper_guard_reports_legacy_helper_with_remediation(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    _write(
        source_root,
        "kicad_mcp/tools/legacy.py",
        "def _track_length_mm(track: object) -> float:\n    return 0.0\n",
    )

    errors = _targeted_helper_definition_errors(
        source_root,
        canonical_owners={},
        legacy_replacements={
            "_track_length_mm": (
                "track_segment_length_mm",
                "kicad_mcp.pcb.geometry",
            ),
        },
    )

    assert errors == [
        "Legacy duplicate helper '_track_length_mm' is forbidden at "
        "src/kicad_mcp/tools/legacy.py:1. Import 'track_segment_length_mm' from "
        "'kicad_mcp.pcb.geometry' or use a distinctly named domain-specific helper."
    ]


def test_targeted_helper_guard_ignores_methods_and_nested_test_fixtures(tmp_path: Path) -> None:
    source_root = tmp_path / "src"
    _write(
        source_root,
        "kicad_mcp/pcb/board_access.py",
        "def board_vias(board: object) -> list[object]:\n    return []\n",
    )
    _write(
        source_root,
        "kicad_mcp/contracts.py",
        "class BoardProtocol:\n"
        "    def board_vias(self) -> list[object]: ...\n\n"
        "def fixture_factory():\n"
        "    def _board_vias() -> list[object]:\n"
        "        return []\n"
        "    return _board_vias\n",
    )

    assert (
        _targeted_helper_definition_errors(
            source_root,
            canonical_owners={
                "board_vias": Path("kicad_mcp/pcb/board_access.py"),
            },
            legacy_replacements={
                "_board_vias": ("board_vias", "kicad_mcp.pcb.board_access"),
            },
        )
        == []
    )
