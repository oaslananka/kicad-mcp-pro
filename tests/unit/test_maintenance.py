"""Tests for diagnostic repair and safe cleanup without touching user KiCad projects."""

from pathlib import Path

from kicad_mcp.services.maintenance import (
    CleanupPreview,
    MaintenanceService,
    RepairPreview,
)


def test_maintenance_preview_repair(tmp_path) -> None:
    svc = MaintenanceService(registry_root=tmp_path / "registry")
    preview = svc.preview_repair()
    assert isinstance(preview, RepairPreview)
    assert hasattr(preview, "healthy")
    assert hasattr(preview, "items")


def test_maintenance_cleanup_preview_preserves_user_projects(tmp_path) -> None:
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


def test_maintenance_apply_cleanup_removes_app_state_only(tmp_path) -> None:
    project_dir = tmp_path / "user_kicad"
    project_dir.mkdir()
    sch = project_dir / "design.kicad_sch"
    sch.write_text("project", encoding="utf-8")

    reg_dir = tmp_path / "registry"
    reg_dir.mkdir()
    app_file = reg_dir / "connector-status.json"
    app_file.write_text("{}", encoding="utf-8")

    svc = MaintenanceService(registry_root=reg_dir)
    res = svc.apply_cleanup(user_project_roots=[project_dir])
    assert res.success is True

    # User files intact
    assert sch.exists()
    assert sch.read_text(encoding="utf-8") == "project"

    # App state cleaned
    assert not app_file.exists()


def test_cleanup_preserves_unknown_and_nested_user_data(tmp_path) -> None:
    root = tmp_path / "registry"
    root.mkdir()
    nested = root / "projects"
    nested.mkdir()
    user_file = nested / "design.kicad_pcb"
    user_file.write_text("board")
    unknown = root / "personal.txt"
    unknown.write_text("data")
    result = MaintenanceService(registry_root=root).apply_cleanup(clean_client_configs=False)
    assert result.success
    assert user_file.read_text() == "board"
    assert unknown.read_text() == "data"


def test_cleanup_preview_lists_owned_client_entries(tmp_path, monkeypatch) -> None:
    import kicad_mcp.services.maintenance as maintenance

    monkeypatch.setattr(
        maintenance,
        "get_owned_client_configs",
        lambda _root: {"claude": [str(tmp_path / "claude-settings.json")]},
    )
    preview = MaintenanceService(registry_root=tmp_path).preview_cleanup()
    assert preview.client_entries_to_remove == [
        {"client": "claude", "config_file": str(tmp_path / "claude-settings.json")}
    ]
    assert not preview.targets_to_remove
