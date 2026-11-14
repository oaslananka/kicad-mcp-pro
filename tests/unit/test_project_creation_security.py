"""Private security regression tests for safe project creation.

All writable destinations use pytest-owned temporary directories only.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.project.creation import ProjectCreationService


def _service(workspace: Path, *, project_files=None) -> ProjectCreationService:
    workspace.mkdir(exist_ok=True)

    def assert_within(root: Path, candidate: Path) -> None:
        candidate.resolve().relative_to(root.resolve())

    def new_project_files(project_dir: Path, name: str) -> tuple[Path, Path, Path]:
        return (
            project_dir / f"{name}.kicad_pro",
            project_dir / f"{name}.kicad_pcb",
            project_dir / f"{name}.kicad_sch",
        )

    cfg = SimpleNamespace(
        workspace_root=workspace,
        workspace=workspace,
        kicad_cli=workspace / "absent-kicad-cli",
        apply_project=lambda project_dir, **kw: assert_within(workspace, project_dir),
    )
    return ProjectCreationService(
        get_config=lambda: cfg,
        assert_within=assert_within,
        new_project_files=project_files or new_project_files,
        new_project_payload=lambda _cli, output: {"project": output.name},
        upgrade_file=lambda *_args: SimpleNamespace(upgraded=True, detail=""),
        reset_connection=lambda: None,
        reset_live_edit=lambda: None,
    )


def test_parent_traversal_is_rejected_before_changing_other_board(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    outside_board = tmp_path / "outside.kicad_pcb"
    outside_board.write_text("IMPORTANT_EXISTING_BOARD", encoding="utf-8")
    service = _service(workspace)

    with pytest.raises(ValueError):
        service.create(str(workspace), "../outside", confirm_overwrite=False)

    assert outside_board.read_text(encoding="utf-8") == "IMPORTANT_EXISTING_BOARD"
    assert not outside.exists()


def test_absolute_name_is_rejected_without_touching_other_board(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    outside_board = tmp_path / "outside.kicad_pcb"
    outside_board.write_text("IMPORTANT_EXISTING_BOARD", encoding="utf-8")
    service = _service(workspace)

    with pytest.raises(ValueError):
        service.create(str(workspace), str(outside), confirm_overwrite=False)

    assert outside_board.read_text(encoding="utf-8") == "IMPORTANT_EXISTING_BOARD"
    assert not outside.exists()


@pytest.mark.parametrize(
    "name",
    [".", "..", "../escape", r"..\\escape", r"C:\\escape", r"\\\\remote\\share", "drive:project"],
)
def test_invalid_project_names_are_rejected_before_file_io(tmp_path: Path, name: str) -> None:
    workspace = tmp_path / "workspace"
    service = _service(workspace)

    with pytest.raises(ValueError):
        service.create(str(workspace), name)

    assert not list(workspace.iterdir())


def test_symlinked_existing_project_dir_cannot_escape_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel.txt").write_text("protected", encoding="utf-8")
    try:
        (workspace / "demo").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this host")

    service = _service(workspace)
    with pytest.raises(ValueError):
        service.create(str(workspace), "demo", confirm_overwrite=True)

    assert (outside / "sentinel.txt").read_text(encoding="utf-8") == "protected"
    assert not (outside / "demo.kicad_pcb").exists()


def test_symlinked_target_file_cannot_overwrite_other_board_with_confirmation(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    project_dir = workspace / "demo"
    project_dir.mkdir(parents=True)
    outside_board = tmp_path / "protected.kicad_pcb"
    outside_board.write_text("IMPORTANT_EXISTING_BOARD", encoding="utf-8")
    try:
        (project_dir / "demo.kicad_pcb").symlink_to(outside_board)
    except (OSError, NotImplementedError):
        pytest.skip("Symlink creation is unavailable on this host")
    service = _service(workspace)

    with pytest.raises(ValueError):
        service.create(str(workspace), "demo", confirm_overwrite=True)

    assert outside_board.read_text(encoding="utf-8") == "IMPORTANT_EXISTING_BOARD"


def test_generated_file_paths_must_be_inside_new_project(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    other_board = tmp_path / "protected.kicad_pcb"
    other_board.write_text("IMPORTANT_EXISTING_BOARD", encoding="utf-8")

    def unsafe_files(project_dir: Path, name: str) -> tuple[Path, Path, Path]:
        return (
            project_dir / f"{name}.kicad_pro",
            other_board,
            project_dir / f"{name}.kicad_sch",
        )

    service = _service(workspace, project_files=unsafe_files)
    with pytest.raises(ValueError):
        service.create(str(workspace), "demo", confirm_overwrite=False)

    assert other_board.read_text(encoding="utf-8") == "IMPORTANT_EXISTING_BOARD"


def test_fresh_normal_unicode_project_remains_supported(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    service = _service(workspace)
    output = service.create(str(workspace), "Gokyuzu 2026")
    assert "Created project" in output
    project_dir = workspace / "Gokyuzu 2026"
    for suffix in (".kicad_pro", ".kicad_pcb", ".kicad_sch"):
        assert (project_dir / f"Gokyuzu 2026{suffix}").is_file()


def test_existing_project_content_is_preserved_without_confirmation(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    target = workspace / "demo" / "demo.kicad_pcb"
    target.parent.mkdir(parents=True)
    target.write_text("IMPORTANT_EXISTING_BOARD", encoding="utf-8")

    result = _service(workspace).create(str(workspace), "demo", confirm_overwrite=False)
    assert "Refusing to create a project" in result
    assert target.read_text(encoding="utf-8") == "IMPORTANT_EXISTING_BOARD"


def test_explicit_confirmation_can_replace_existing_project_content(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    target = workspace / "demo" / "demo.kicad_pcb"
    target.parent.mkdir(parents=True)
    target.write_text("OLD_DRAFT_BOARD", encoding="utf-8")

    result = _service(workspace).create(str(workspace), "demo", confirm_overwrite=True)
    assert "Created project" in result
    assert target.read_text(encoding="utf-8").startswith("(kicad_pcb")


def test_new_files_are_exclusively_created_if_target_appears_during_creation(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    target = workspace / "demo" / "demo.kicad_pro"

    def race_payload(_cli: Path, project_file: Path) -> dict[str, str]:
        project_file.write_text("IMPORTANT_NEW_OWNER_CONTENT", encoding="utf-8")
        return {"generated": "should-not-overwrite"}

    service = replace(_service(workspace), new_project_payload=race_payload)
    with pytest.raises(FileExistsError):
        service.create(str(workspace), "demo", confirm_overwrite=False)

    assert target.read_text(encoding="utf-8") == "IMPORTANT_NEW_OWNER_CONTENT"
