from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from kicad_mcp.server import build_server
from tests.conftest import call_tool_text

SOURCE_ROOT = Path(__file__).resolve().parents[2]

_REPOSITORY_LOCAL_GIT_ENV = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_IMPLICIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PREFIX",
    "GIT_QUARANTINE_PATH",
    "GIT_WORK_TREE",
)


@pytest.fixture(autouse=True)
def isolated_git_process_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep test-owned repositories detached from user and caller Git configuration."""
    git_env = tmp_path / "git-environment"
    home = git_env / "home"
    xdg = git_env / "xdg"
    templates = git_env / "templates"
    hostile_hooks = git_env / "hostile-hooks"
    for directory in (home, xdg, templates, hostile_hooks):
        directory.mkdir(parents=True)

    hostile_marker = git_env / "hostile-hook-ran"
    hook = hostile_hooks / "pre-commit"
    hook.write_text(
        '#!/bin/sh\nprintf hostile > "$HOSTILE_GIT_HOOK_MARKER"\nexit 91\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    (home / ".gitconfig").write_text(
        f"[core]\n\thooksPath = {hostile_hooks.as_posix()}\n",
        encoding="utf-8",
    )
    global_config = git_env / "global.gitconfig"
    system_config = git_env / "system.gitconfig"
    global_config.write_text("", encoding="utf-8")
    system_config.write_text("", encoding="utf-8")

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(xdg))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", str(system_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(templates))
    monkeypatch.setenv("HOSTILE_GIT_HOOK_MARKER", str(hostile_marker))
    for variable in _REPOSITORY_LOCAL_GIT_ENV:
        monkeypatch.delenv(variable, raising=False)
    return hostile_marker


def _clean_git_env() -> dict[str, str]:
    env = os.environ.copy()
    for variable in _REPOSITORY_LOCAL_GIT_ENV:
        env.pop(variable, None)
    return env


def _git_output(repo: Path, *args: str) -> str:
    git = shutil.which("git")
    assert git is not None
    return subprocess.run(
        [git, *args],
        cwd=repo,
        env=_clean_git_env(),
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _caller_checkout_snapshot() -> tuple[str, str, str]:
    return (
        _git_output(SOURCE_ROOT, "status", "--porcelain=v1", "--untracked-files=all"),
        _git_output(SOURCE_ROOT, "diff", "--binary"),
        _git_output(SOURCE_ROOT, "diff", "--cached", "--binary"),
    )


def _commit_hash(text: str) -> str:
    match = re.search(r"- Commit: ([0-9a-f]{40})", text)
    if match is None:
        raise AssertionError(f"Unable to extract commit hash from: {text}")
    return match.group(1)


@pytest.mark.anyio
async def test_vcs_checkpoint_diff_and_restore_roundtrip(
    sample_project: Path,
    isolated_git_process_environment: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller_before = _caller_checkout_snapshot()
    git_dir = _git_output(SOURCE_ROOT, "rev-parse", "--absolute-git-dir").strip()
    git_index = _git_output(SOURCE_ROOT, "rev-parse", "--git-path", "index").strip()
    monkeypatch.setenv("GIT_DIR", git_dir)
    monkeypatch.setenv("GIT_WORK_TREE", str(SOURCE_ROOT))
    monkeypatch.setenv("GIT_INDEX_FILE", git_index)
    monkeypatch.setenv("GIT_PREFIX", "hostile-prefix/")

    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})

    init_text = await call_tool_text(
        server,
        "vcs_init_git",
        {"project_dir": str(sample_project)},
    )
    initial_schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")

    checkpoint_text = await call_tool_text(
        server,
        "vcs_commit_checkpoint",
        {"message": "Initial checkpoint", "auto_drc": False},
    )
    checkpoint_hash = _commit_hash(checkpoint_text)

    (sample_project / "demo.kicad_sch").write_text(
        initial_schematic + "\n; modified by test\n",
        encoding="utf-8",
    )

    diff_text = await call_tool_text(
        server,
        "vcs_diff_with_checkpoint",
        {"commit_hash": checkpoint_hash},
    )
    checkpoints_text = await call_tool_text(server, "vcs_list_checkpoints", {})
    restore_dry_run = await call_tool_text(
        server,
        "vcs_restore_checkpoint",
        {"commit_hash": checkpoint_hash},
    )
    restore_text = await call_tool_text(
        server,
        "vcs_restore_checkpoint",
        {"commit_hash": checkpoint_hash, "confirm": True},
    )
    restored_schematic = (sample_project / "demo.kicad_sch").read_text(encoding="utf-8")

    assert "Git repository ready." in init_text
    assert (sample_project / ".git").exists()
    assert "Checkpoint committed." in checkpoint_text
    assert "Diff versus checkpoint" in diff_text
    assert "demo.kicad_sch" in diff_text
    assert "Checkpoints (1 total):" in checkpoints_text
    assert "Initial checkpoint" in checkpoints_text
    assert "Dry run: checkpoint restore was not executed." in restore_dry_run
    assert "Checkpoint restored." in restore_text
    assert "backed up" in restore_text
    assert "Recovery branch: mcp-restore-" in restore_text
    assert restored_schematic == initial_schematic
    assert not isolated_git_process_environment.exists()
    assert _caller_checkout_snapshot() == caller_before


@pytest.mark.anyio
async def test_vcs_tag_release_requires_clean_gate(sample_project: Path, monkeypatch) -> None:
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(server, "vcs_init_git", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "vcs_commit_checkpoint",
        {"message": "Release candidate", "auto_drc": False},
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.version_control._evaluate_project_gate",
        lambda: [],
    )
    monkeypatch.setattr(
        "kicad_mcp.tools.version_control._combined_status",
        lambda _outcomes: "PASS",
    )

    tag_text = await call_tool_text(
        server,
        "vcs_tag_release",
        {
            "tag": "v2.4.0-test",
            "message": "Release candidate",
            "dry_run": False,
            "confirm": True,
        },
    )

    assert "Release tag created." in tag_text


@pytest.mark.anyio
async def test_vcs_tag_release_defaults_to_dry_run(sample_project: Path, monkeypatch) -> None:
    server = build_server("full")
    await call_tool_text(server, "kicad_set_project", {"project_dir": str(sample_project)})
    await call_tool_text(server, "vcs_init_git", {"project_dir": str(sample_project)})
    await call_tool_text(
        server,
        "vcs_commit_checkpoint",
        {"message": "Release candidate", "auto_drc": False},
    )
    monkeypatch.setattr("kicad_mcp.tools.version_control._evaluate_project_gate", lambda: [])
    monkeypatch.setattr(
        "kicad_mcp.tools.version_control._combined_status",
        lambda _outcomes: "PASS",
    )

    tag_text = await call_tool_text(
        server,
        "vcs_tag_release",
        {"tag": "v2.4.1-test", "message": "Release candidate"},
    )

    assert "Dry run: release tag was not created." in tag_text
