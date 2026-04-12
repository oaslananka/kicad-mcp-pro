from __future__ import annotations

from pathlib import Path

from kicad_mcp.config import KiCadMCPConfig


def test_config_reads_env_vars(sample_project: Path, monkeypatch) -> None:
    monkeypatch.setenv("KICAD_MCP_LOG_LEVEL", "DEBUG")
    cfg = KiCadMCPConfig()
    assert cfg.project_dir == sample_project
    assert cfg.log_level == "DEBUG"


def test_config_auto_detects_files(sample_project: Path) -> None:
    cfg = KiCadMCPConfig()
    assert cfg.project_file == sample_project / "demo.kicad_pro"
    assert cfg.pcb_file == sample_project / "demo.kicad_pcb"
    assert cfg.sch_file == sample_project / "demo.kicad_sch"


def test_config_resolve_within_project(sample_project: Path) -> None:
    cfg = KiCadMCPConfig()
    resolved = cfg.resolve_within_project("exports/demo.txt")
    assert resolved == sample_project / "exports" / "demo.txt"
