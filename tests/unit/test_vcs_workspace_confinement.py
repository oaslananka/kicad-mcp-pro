"""Git checkpoint tools must never escape an explicitly configured workspace.

Run real Git commands only inside pytest's disposable per-test paths.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.errors import UnsafePathError
from kicad_mcp.tools import version_control


def _set_workspace(monkeypatch: pytest.MonkeyPatch, workspace: Path, project: Path) -> None:
    monkeypatch.setattr(
        version_control,
        "get_config",
        lambda: SimpleNamespace(
            workspace_root=workspace,
            workspace=workspace,
            project_dir=project,
            pcb_file=None,
        ),
    )


def _init_git(directory: Path, *, git_dir: Path | None = None) -> None:
    args = ["-c", "init.templateDir=", "init", "--initial-branch=main"]
    if git_dir is not None:
        args.extend(("--separate-git-dir", str(git_dir)))
    version_control._run_git(directory, *args, str(directory))


def test_vcs_init_git_rejects_outside_workspace_without_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "board"
    outside = tmp_path / "outside"
    project.mkdir(parents=True)
    outside.mkdir()
    marker = outside / "existing.txt"
    marker.write_text("preserve", encoding="utf-8")
    _set_workspace(monkeypatch, workspace, project)

    with pytest.raises(UnsafePathError, match="workspace"):
        version_control.vcs_init_git(str(outside))
    assert sorted(p.name for p in outside.iterdir()) == ["existing.txt"]
    assert marker.read_text(encoding="utf-8") == "preserve"


@pytest.mark.parametrize("raw", ["outside", "missing"])
def test_resolver_checks_scope_before_existence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "board"
    project.mkdir(parents=True)
    _set_workspace(monkeypatch, workspace, project)
    outside = tmp_path / raw
    if raw == "outside":
        outside.mkdir()

    with pytest.raises(UnsafePathError, match="workspace"):
        version_control._resolve_project_dir(str(outside))


def test_symlink_to_external_directory_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "board"
    outside = tmp_path / "victim"
    project.mkdir(parents=True)
    outside.mkdir()
    alias = workspace / "alias"
    try:
        alias.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("This host cannot create directory symlinks")
    _set_workspace(monkeypatch, workspace, project)

    with pytest.raises(UnsafePathError, match="workspace"):
        version_control.vcs_init_git(str(alias))
    assert not (outside / ".git").exists()
    assert not (outside / ".gitignore").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX-only cross-platform input")
@pytest.mark.parametrize("raw", [r"C:\foreign\project", r"\\server\share\board"])
def test_foreign_windows_path_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "board"
    project.mkdir(parents=True)
    _set_workspace(monkeypatch, workspace, project)

    with pytest.raises(UnsafePathError):
        version_control._resolve_project_dir(raw)


@pytest.mark.parametrize(
    ("tool_name", "args"),
    [
        ("vcs_init_git", "explicit"),
        ("vcs_commit_checkpoint", ("checkpoint",)),
        ("vcs_list_checkpoints", ()),
        ("vcs_restore_checkpoint", ("deadbeef",)),
        ("vcs_diff_with_checkpoint", ("deadbeef",)),
        ("vcs_tag_release", ("v1.0.0", "checkpoint")),
    ],
)
def test_git_ancestor_above_workspace_rejected_for_every_vcs_tool(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tool_name: str,
    args: str | tuple[str, ...],
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "board"
    project.mkdir(parents=True)
    _init_git(tmp_path)  # Git finds this ancestor outside the workspace.
    config = tmp_path / ".git" / "config"
    before_config = config.read_bytes()
    _set_workspace(monkeypatch, workspace, project)

    def invoke_tool() -> str:
        if tool_name == "vcs_init_git":
            return version_control.vcs_init_git(str(project))
        if tool_name == "vcs_commit_checkpoint":
            return version_control.vcs_commit_checkpoint("checkpoint", auto_drc=False)
        return getattr(version_control, tool_name)(*args)

    with pytest.raises(UnsafePathError, match="workspace"):
        invoke_tool()
    assert config.read_bytes() == before_config
    assert not (project / ".gitignore").exists()


def test_git_metadata_outside_workspace_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "board"
    metadata = tmp_path / "external_git_data"
    project.mkdir(parents=True)
    _init_git(project, git_dir=metadata)  # Working-tree path is inside the workspace.
    before_config = (metadata / "config").read_bytes()
    _set_workspace(monkeypatch, workspace, project)

    with pytest.raises(UnsafePathError, match="workspace"):
        version_control.vcs_init_git(str(project))
    assert before_config == (metadata / "config").read_bytes()
    assert not (project / ".gitignore").exists()


def test_valid_scoped_init_and_repeat_still_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "board"
    project.mkdir(parents=True)
    _set_workspace(monkeypatch, workspace, project)

    assert "Created new repo: yes" in version_control.vcs_init_git(str(project))
    assert "Created new repo: no" in version_control.vcs_init_git(str(project))
    assert (project / ".git" / "config").exists()
    assert (project / ".gitignore").exists()


def test_no_explicit_workspace_keeps_legacy_behavior(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "board"
    project.mkdir()
    monkeypatch.setattr(
        version_control,
        "get_config",
        lambda: SimpleNamespace(project_dir=project, workspace_root=None),
    )
    assert "Created new repo: yes" in version_control.vcs_init_git(str(project))
