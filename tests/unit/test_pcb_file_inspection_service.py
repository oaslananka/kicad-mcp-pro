from __future__ import annotations

import json
from pathlib import Path

from kicad_mcp.pcb.file_inspection import PcbFileInspectionService


def _readability_report(
    footprints: dict[str, dict[str, object]], bounds: tuple[float, float, float, float] | None
) -> dict[str, object]:
    assert bounds is not None
    return {
        "status": "PASS",
        "footprint_count": len(footprints),
        "bounds": list(bounds),
    }


def _service(board_file: Path) -> PcbFileInspectionService:
    return PcbFileInspectionService(
        get_board_file=lambda: board_file,
        normalize_board_content=lambda content: f"normalized:{content}",
        parse_board_footprints=lambda content: {
            "R1": {"block": f"block:{content}"},
        },
        footprint_layers=lambda block: ["F_Cu", "In1_Cu", "B_Cu"],
        board_file_diagnostics=lambda board_file, status: {
            "board_file": str(board_file),
            "status": status,
        },
        edge_cuts_bounds=lambda content: (0.0, 0.0, 100.0, 80.0),
        readability_report=_readability_report,
    )


def test_footprint_layers_preserves_found_and_missing_payloads(tmp_path: Path) -> None:
    board_file = tmp_path / "board.kicad_pcb"
    board_file.write_text("board", encoding="utf-8")
    service = _service(board_file)

    found = json.loads(service.footprint_layers_for("R1"))
    missing = json.loads(service.footprint_layers_for("U1"))

    assert found == {
        "reference": "R1",
        "found": True,
        "layers": ["F_Cu", "In1_Cu", "B_Cu"],
        "diagnostics": {
            "board_file": str(board_file),
            "status": "using file-backed footprint parser",
        },
    }
    assert missing == {
        "reference": "U1",
        "found": False,
        "layers": [],
        "diagnostics": {
            "board_file": str(board_file),
            "status": "footprint reference not present in board file",
        },
    }


def test_visual_qa_delegates_file_geometry_without_fastmcp(tmp_path: Path) -> None:
    board_file = tmp_path / "board.kicad_pcb"
    board_file.write_text("board", encoding="utf-8")

    payload = json.loads(_service(board_file).visual_qa())

    assert payload == {
        "status": "PASS",
        "footprint_count": 1,
        "bounds": [0.0, 0.0, 100.0, 80.0],
    }
