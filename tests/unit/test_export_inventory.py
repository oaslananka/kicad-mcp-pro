from __future__ import annotations

from pathlib import Path

from kicad_mcp.export.inventory import (
    IPC2581_DEFAULT_NAME,
    discover_drill_output_files,
    discover_gerber_output_files,
)


def test_gerber_discovery_preserves_existing_service_pattern_semantics(tmp_path: Path) -> None:
    for name in ("board-F_Cu.gtl", "board-B_Cu.gbl", "board-Edge_Cuts.gm1", "board-job.gbrjob"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("ignore", encoding="utf-8")

    assert [path.name for path in discover_gerber_output_files(tmp_path)] == [
        "board-B_Cu.gbl",
        "board-Edge_Cuts.gm1",
        "board-F_Cu.gtl",
        "board-job.gbrjob",
    ]


def test_gerber_discovery_returns_exact_gbr_once(tmp_path: Path) -> None:
    (tmp_path / "legacy.gbr").write_text("gerber", encoding="utf-8")

    assert [path.name for path in discover_gerber_output_files(tmp_path)] == ["legacy.gbr"]


def test_drill_discovery_and_ipc2581_default_contract(tmp_path: Path) -> None:
    for name in ("board.drl", "board.xnc", "ignore.txt"):
        (tmp_path / name).write_text(name, encoding="utf-8")

    assert [path.name for path in discover_drill_output_files(tmp_path)] == [
        "board.drl",
        "board.xnc",
    ]
    assert IPC2581_DEFAULT_NAME == "board.ipc2581"
