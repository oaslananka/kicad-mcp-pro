from __future__ import annotations

from pathlib import Path

from kicad_mcp.discovery import scan_project_dir


def test_scan_finds_kicad_files(tmp_path: Path) -> None:
    (tmp_path / "board.kicad_pcb").touch()
    (tmp_path / "schematic.kicad_sch").touch()
    (tmp_path / "demo.kicad_pro").touch()
    result = scan_project_dir(tmp_path)
    assert result["pcb"] is not None
    assert result["schematic"] is not None
    assert result["project"] is not None
