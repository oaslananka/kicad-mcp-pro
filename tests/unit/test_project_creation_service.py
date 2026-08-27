from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _service_type():
    assert importlib.util.find_spec("kicad_mcp.project.creation") is not None
    return importlib.import_module("kicad_mcp.project.creation").ProjectCreationService


def test_create_refuses_nonempty_directory_without_confirmation(tmp_path: Path) -> None:
    service_cls = _service_type()
    existing = tmp_path / "demo"
    existing.mkdir()
    (existing / "keep.txt").write_text("keep", encoding="utf-8")

    cfg = SimpleNamespace(workspace_root=None, workspace=tmp_path, kicad_cli=Path("/missing"))
    service = service_cls(
        get_config=lambda: cfg,
        assert_within=lambda _root, _candidate: None,
        new_project_files=lambda project_dir, name: (
            project_dir / f"{name}.kicad_pro",
            project_dir / f"{name}.kicad_pcb",
            project_dir / f"{name}.kicad_sch",
        ),
        new_project_payload=lambda _cli, project_file: {"meta": {"filename": project_file.name}},
        upgrade_file=lambda _path, _kind, _root: SimpleNamespace(upgraded=True, detail=""),
        reset_connection=lambda: None,
        reset_live_edit=lambda: None,
    )

    output = service.create(str(tmp_path), "demo", confirm_overwrite=False)
    assert "Refusing to create a project over an existing non-empty directory." in output
    assert (existing / "keep.txt").read_text(encoding="utf-8") == "keep"


def test_create_checks_workspace_boundary_before_refusing_existing_dir(tmp_path: Path) -> None:
    service_cls = _service_type()
    existing = tmp_path / "demo"
    existing.mkdir()
    (existing / "keep.txt").write_text("keep", encoding="utf-8")
    checked: list[tuple[Path, Path]] = []
    cfg = SimpleNamespace(
        workspace_root=tmp_path,
        workspace=tmp_path,
        kicad_cli=Path("/missing"),
    )
    service = service_cls(
        get_config=lambda: cfg,
        assert_within=lambda root, candidate: checked.append((root, candidate)),
        new_project_files=lambda project_dir, name: (
            project_dir / f"{name}.kicad_pro",
            project_dir / f"{name}.kicad_pcb",
            project_dir / f"{name}.kicad_sch",
        ),
        new_project_payload=lambda _cli, project_file: {"meta": {"filename": project_file.name}},
        upgrade_file=lambda _path, _kind, _root: SimpleNamespace(upgraded=True, detail=""),
        reset_connection=lambda: None,
        reset_live_edit=lambda: None,
    )

    service.create(str(tmp_path), "demo")
    assert checked == [(tmp_path, tmp_path.resolve())]


def test_create_reports_unavailable_format_migration(tmp_path: Path) -> None:
    service_cls = _service_type()
    applied: list[Path] = []
    resets: list[object] = []
    cfg = SimpleNamespace(
        workspace_root=None,
        workspace=tmp_path,
        kicad_cli=Path("/missing"),
        apply_project=lambda project_dir, **_kwargs: applied.append(project_dir),
    )
    service = service_cls(
        get_config=lambda: cfg,
        assert_within=lambda _root, _candidate: None,
        new_project_files=lambda project_dir, name: (
            project_dir / f"{name}.kicad_pro",
            project_dir / f"{name}.kicad_pcb",
            project_dir / f"{name}.kicad_sch",
        ),
        new_project_payload=lambda _cli, project_file: {"meta": {"filename": project_file.name}},
        upgrade_file=lambda _path, _kind, _root: SimpleNamespace(
            upgraded=False, detail="cli unavailable"
        ),
        reset_connection=lambda: resets.append(True),
        reset_live_edit=lambda: resets.append("live-edit"),
    )

    output = service.create(str(tmp_path), "fresh")
    assert "Format note (pcb)" in output
    assert "Format note (sch)" in output
    assert "cli unavailable" in output
    assert applied == [tmp_path / "fresh"]
    assert resets == [True, "live-edit"]
