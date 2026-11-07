"""Tests for diagnostic repair and safe cleanup without touching user KiCad projects."""

import json
import pytest
from pathlib import Path

from kicad_mcp.services.maintenance import (
    MaintenanceService,
    RepairPreview,
    CleanupPreview,
)


def test_maintenance_preview_repair(tmp_path):
    svc = MaintenanceService(registry_root=tmp_path / "registry")
    preview = svc.preview_repair()
    assert isinstance(preview, RepairPreview)
    assert hasattr(preview, "healthy")
    assert hasattr(preview, "items")


def test_maintenance_cleanup_preview_preserves_user_projects(tmp_path):
    project_dir = tmp_path / "my_project"
    project_dir.mkdir()
    sch_file = project_dir / "board.kicad_sch"
    sch_file.write_text("(kicad_sch ...)", encoding="utf-8")
    pcb_file = project_dir / "board.kicad_pcb"
    pcb_file.write_text("(kicad_pcb ...)", encoding="utf-8")

    reg_dir = tmp_path / "registry"
    reg_dir.mkdir()
    (reg_dir / "test_artifact.tmp").write_text("temp", encoding="utf-8")

    svc = MaintenanceService(registry_root=reg_dir)
    preview = svc.preview_cleanup(user_project_roots=[project_dir])
    assert isinstance(preview, CleanupPreview)

    # User project files must NEVER be in preview targets
    target_paths = [str(Path(t).resolve()) for t in preview.targets_to_remove]
    assert str(sch_file.resolve()) not in target_paths
    assert str(pcb_file.resolve()) not in target_paths
    assert any(str(sch_file.resolve()) in str(p) for p in preview.preserved_user_files)


def test_maintenance_apply_cleanup_removes_app_state_only(tmp_path):
    project_dir = tmp_path / "user_kicad"
    project_dir.mkdir()
    sch = project_dir / "design.kicad_sch"
    sch.write_text("project", encoding="utf-8")

    reg_dir = tmp_path / "registry"
    reg_dir.mkdir()
    app_file = reg_dir / "pairing_state.json"
    app_file.write_text("{}", encoding="utf-8")

    svc = MaintenanceService(registry_root=reg_dir)
    res = svc.apply_cleanup(user_project_roots=[project_dir])
    assert res.success is True

    # User files intact
    assert sch.exists()
    assert sch.read_text(encoding="utf-8") == "project"

    # App state cleaned
    assert not app_file.exists()
