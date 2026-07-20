from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from kicad_mcp.tools import version_control


class FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self) -> Callable[[Callable[..., object]], Callable[..., object]]:
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


def test_version_control_helper_functions(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(version_control.shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="Git was not found"):
        version_control._git_executable()

    project_dir = tmp_path / "project"
    project_dir.mkdir()
    assert version_control._resolve_project_dir(str(project_dir)) == project_dir.resolve()

    monkeypatch.setattr(
        version_control,
        "get_config",
        lambda: SimpleNamespace(project_dir=None, pcb_file=None),
    )
    with pytest.raises(ValueError, match="No active project directory"):
        version_control._resolve_project_dir()

    with pytest.raises(FileNotFoundError):
        version_control._resolve_project_dir(str(tmp_path / "missing"))

    monkeypatch.setattr(version_control, "_git_executable", lambda: "git")

    def failing_run(
        cmd: list[str],
        *,
        cwd: Path,
        capture_output: bool,
        text: bool,
        timeout: int,
        check: bool,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        _ = (cmd, cwd, capture_output, text, timeout, check)
        _ = kwargs
        return subprocess.CompletedProcess(["git"], 1, stdout="", stderr="broken")

    monkeypatch.setattr(version_control.subprocess, "run", failing_run)
    with pytest.raises(ValueError, match="Git command failed"):
        version_control._run_git(project_dir, "status")

    gitignore_dir = tmp_path / "gitignore-project"
    gitignore_dir.mkdir()
    version_control._ensure_gitignore(gitignore_dir)
    version_control._ensure_gitignore(gitignore_dir)
    assert (gitignore_dir / ".gitignore").read_text(encoding="utf-8").splitlines() == [
        "output/",
        "*.step",
        "*.stp",
        "*.zip",
    ]

    monkeypatch.setattr(version_control, "_project_status", lambda *_args: [])
    assert version_control._stash_project_state(project_dir, ".", "abc123") is None

    monkeypatch.setattr(version_control, "_project_status", lambda *_args: [" M board.kicad_pcb"])
    monkeypatch.setattr(
        version_control,
        "_run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(["git"], 0, stdout="", stderr=""),
    )
    assert (
        version_control._stash_project_state(project_dir, ".", "abc123")
        == "kicad-mcp backup before restore abc123"
    )

    monkeypatch.setattr(
        version_control,
        "_run_git",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["git"], 0, stdout="Saved working directory", stderr=""
        ),
    )
    assert (
        version_control._stash_project_state(project_dir, ".", "abc123")
        == "Saved working directory"
    )
    assert version_control._has_session_scraps(["?? demo.kicad_pro.lock"]) == "demo.kicad_pro.lock"
    assert version_control._has_session_scraps(["?? notes/~$demo.xlsx"]) == "notes/~$demo.xlsx"
    assert version_control._has_session_scraps([" M demo.kicad_pcb"]) is None


def test_git_subprocess_environment_drops_caller_repository_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for variable in version_control._REPOSITORY_LOCAL_GIT_ENV:
        monkeypatch.setenv(variable, f"hostile-{variable.lower()}")
    monkeypatch.setenv("HOME", "/safe/home")

    env = version_control._git_subprocess_env()

    assert env["HOME"] == "/safe/home"
    assert set(version_control._REPOSITORY_LOCAL_GIT_ENV).isdisjoint(env)


def test_project_pathspec_and_destructive_scope_fail_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo_root = tmp_path / "repo"
    project_dir = repo_root / "project"
    outside = tmp_path / "outside"
    project_dir.mkdir(parents=True)
    outside.mkdir()

    assert version_control._project_pathspec(repo_root, project_dir) == "project"
    with pytest.raises(ValueError, match="outside Git repository"):
        version_control._project_pathspec(repo_root, outside)

    monkeypatch.setattr(version_control, "_git_repo_root", lambda _path: outside)
    with pytest.raises(ValueError, match="repository context changed"):
        version_control._verify_repo_scope(repo_root, project_dir)


def test_commit_blocked_by_drc_branches(monkeypatch, tmp_path: Path) -> None:
    pcb_file = tmp_path / "demo.kicad_pcb"
    pcb_file.write_text("board", encoding="utf-8")

    monkeypatch.setattr(
        version_control,
        "get_config",
        lambda: SimpleNamespace(pcb_file=None),
    )
    assert version_control._commit_blocked_by_drc() is None

    monkeypatch.setattr(
        version_control,
        "get_config",
        lambda: SimpleNamespace(pcb_file=pcb_file),
    )
    monkeypatch.setattr(
        version_control,
        "_run_drc_report",
        lambda _name: (None, None, "cli missing"),
    )
    assert "cli missing" in version_control._commit_blocked_by_drc()

    monkeypatch.setattr(
        version_control,
        "_run_drc_report",
        lambda _name: (None, {"violations": [1, 2], "unconnected_items": [1]}, None),
    )
    monkeypatch.setattr(version_control, "_entries", lambda report, key: report[key])
    assert "2 violation(s) and 1 unconnected item(s)" in version_control._commit_blocked_by_drc()

    monkeypatch.setattr(
        version_control,
        "_run_drc_report",
        lambda _name: (None, {"violations": [], "unconnected_items": []}, None),
    )
    assert version_control._commit_blocked_by_drc() is None


def test_register_version_control_tools(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    project_dir = repo_root / "project"
    project_dir.mkdir(parents=True)

    mcp = FakeMCP()
    version_control.register(mcp)
    vcs_init_git = mcp.tools["vcs_init_git"]
    vcs_commit_checkpoint = mcp.tools["vcs_commit_checkpoint"]
    vcs_list_checkpoints = mcp.tools["vcs_list_checkpoints"]
    vcs_restore_checkpoint = mcp.tools["vcs_restore_checkpoint"]
    vcs_diff_with_checkpoint = mcp.tools["vcs_diff_with_checkpoint"]
    vcs_tag_release = mcp.tools["vcs_tag_release"]

    monkeypatch.setattr(version_control, "_resolve_project_dir", lambda path=None: project_dir)
    monkeypatch.setattr(version_control, "_git_repo_root", lambda _path: None)
    init_calls: list[tuple[Path, tuple[str, ...]]] = []
    monkeypatch.setattr(
        version_control,
        "_run_git",
        lambda repo, *args, **kwargs: (
            init_calls.append((repo, args))
            or subprocess.CompletedProcess(["git"], 0, stdout="", stderr="")
        ),
    )
    monkeypatch.setattr(
        version_control,
        "_ensure_git_identity",
        lambda _root: ["user.name=KiCad MCP Pro"],
    )
    ensured: list[Path] = []
    monkeypatch.setattr(version_control, "_ensure_gitignore", lambda path: ensured.append(path))
    init_text = vcs_init_git(str(project_dir))
    assert "Created new repo: yes" in init_text
    assert ensured == [project_dir]
    assert init_calls[0][1] == ("init", "--initial-branch", "main")

    monkeypatch.setattr(version_control, "_git_repo_root", lambda _path: repo_root)
    monkeypatch.setattr(version_control, "_ensure_git_identity", lambda _root: [])
    assert "Created new repo: no" in vcs_init_git(str(project_dir))

    with pytest.raises(ValueError, match="must not be empty"):
        vcs_commit_checkpoint("   ")

    monkeypatch.setattr(version_control, "_resolve_project_dir", lambda: project_dir)
    monkeypatch.setattr(version_control, "_git_repo_root", lambda _path: None)
    with pytest.raises(ValueError, match="No Git repository was found"):
        vcs_commit_checkpoint("checkpoint")

    monkeypatch.setattr(version_control, "_git_repo_root", lambda _path: repo_root)
    monkeypatch.setattr(version_control, "_project_pathspec", lambda _root, _project: "project")
    monkeypatch.setattr(version_control, "_ensure_git_identity", lambda _root: [])
    monkeypatch.setattr(version_control, "_commit_blocked_by_drc", lambda: "DRC blocked")
    with pytest.raises(ValueError, match="DRC blocked"):
        vcs_commit_checkpoint("checkpoint")

    monkeypatch.setattr(version_control, "_commit_blocked_by_drc", lambda: None)
    monkeypatch.setattr(version_control, "_project_status", lambda *_args: [])
    add_calls: list[tuple[str, ...]] = []

    def record_add(
        _repo: Path,
        *args: str,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        _ = kwargs
        add_calls.append(args)
        return subprocess.CompletedProcess(["git"], 0, stdout="", stderr="")

    monkeypatch.setattr(version_control, "_run_git", record_add)
    assert "No project changes were detected" in vcs_commit_checkpoint("checkpoint", auto_drc=False)
    assert add_calls[0] == ("add", "--", "project")

    monkeypatch.setattr(
        version_control,
        "_project_status",
        lambda *_args: [" M project/demo.kicad_pcb"],
    )

    def run_commit(
        repo: Path,
        *args: str,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        _ = (repo, kwargs)
        if args == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(["git"], 0, stdout="deadbeef\n", stderr="")
        return subprocess.CompletedProcess(["git"], 0, stdout="", stderr="")

    monkeypatch.setattr(version_control, "_run_git", run_commit)
    commit_text = vcs_commit_checkpoint("checkpoint", auto_drc=False)
    assert "Checkpoint committed." in commit_text
    assert "deadbeef" in commit_text
    assert "Auto DRC: disabled" in commit_text

    monkeypatch.setattr(
        version_control,
        "_project_status",
        lambda *_args: ["?? project/demo.kicad_pro.lock"],
    )
    with pytest.raises(ValueError, match="session scrap files"):
        vcs_commit_checkpoint("checkpoint", auto_drc=False)

    monkeypatch.setattr(
        version_control,
        "_run_git",
        lambda _repo, *args, **kwargs: subprocess.CompletedProcess(
            ["git"], 0, stdout="", stderr=""
        ),
    )
    assert "No KiCad MCP checkpoints were found" in vcs_list_checkpoints()

    monkeypatch.setattr(
        version_control,
        "_run_git",
        lambda _repo, *args, **kwargs: subprocess.CompletedProcess(
            ["git"],
            0,
            stdout="deadbeef\tdeadbee\t2026-04-15T20:00:00+00:00\tcheckpoint\n",
            stderr="",
        ),
    )
    assert "Checkpoints (1 total):" in vcs_list_checkpoints()

    with pytest.raises(ValueError, match="must not be empty"):
        vcs_restore_checkpoint("  ")

    monkeypatch.setattr(version_control, "_stash_project_state", lambda *_args: "stash@{0}")
    monkeypatch.setattr(
        version_control,
        "_create_restore_branch",
        lambda *_args: "mcp-restore-deadbee",
    )
    monkeypatch.setattr(
        version_control,
        "_run_git",
        lambda _repo, *args, **kwargs: subprocess.CompletedProcess(
            ["git"], 0, stdout="", stderr=""
        ),
    )
    restore_preview = vcs_restore_checkpoint("deadbeef")
    restored = vcs_restore_checkpoint("deadbeef", confirm=True)
    assert "Dry run: checkpoint restore was not executed." in restore_preview
    assert "Previous uncommitted state was backed up: stash@{0}" in restored
    assert "Recovery branch: mcp-restore-deadbee" in restored

    monkeypatch.setattr(version_control, "_stash_project_state", lambda *_args: None)
    assert "already clean" in vcs_restore_checkpoint("deadbeef", confirm=True)

    with pytest.raises(ValueError, match="must not be empty"):
        vcs_diff_with_checkpoint(" ")

    monkeypatch.setattr(
        version_control,
        "_run_git",
        lambda _repo, *args, **kwargs: subprocess.CompletedProcess(
            ["git"],
            0,
            stdout="" if "--name-status" in args else "",
            stderr="",
        ),
    )
    assert "No project changes were found" in vcs_diff_with_checkpoint("deadbeef")

    def run_diff(
        _repo: Path,
        *args: str,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        _ = kwargs
        stdout = "M\tproject/demo.kicad_pcb" if "--name-status" in args else " 1 file changed"
        return subprocess.CompletedProcess(["git"], 0, stdout=stdout, stderr="")

    monkeypatch.setattr(version_control, "_run_git", run_diff)
    diff_text = vcs_diff_with_checkpoint("deadbeef")
    assert "Diff versus checkpoint deadbeef:" in diff_text
    assert "M\tproject/demo.kicad_pcb" in diff_text
    assert "1 file changed" in diff_text

    with pytest.raises(ValueError, match="Release tag must not be empty"):
        vcs_tag_release(" ", "release")
    with pytest.raises(ValueError, match="message must not be empty"):
        vcs_tag_release("v2.4.0", " ")

    monkeypatch.setattr(version_control, "_combined_status", lambda _outcomes: "FAIL")
    monkeypatch.setattr(version_control, "_evaluate_project_gate", lambda: [])
    with pytest.raises(ValueError, match="project_quality_gate\\(\\) returns PASS"):
        vcs_tag_release("v2.4.0", "release")

    monkeypatch.setattr(version_control, "_combined_status", lambda _outcomes: "PASS")

    def tag_exists(
        _repo: Path,
        *args: str,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        _ = kwargs
        if args[:2] == ("tag", "--list"):
            return subprocess.CompletedProcess(["git"], 0, stdout="v2.4.0\n", stderr="")
        return subprocess.CompletedProcess(["git"], 0, stdout="", stderr="")

    monkeypatch.setattr(version_control, "_run_git", tag_exists)
    with pytest.raises(ValueError, match="already exists"):
        vcs_tag_release("v2.4.0", "release")

    def create_tag(
        _repo: Path,
        *args: str,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        _ = kwargs
        if args[:2] == ("tag", "--list"):
            return subprocess.CompletedProcess(["git"], 0, stdout="", stderr="")
        if args == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(["git"], 0, stdout="deadbeef\n", stderr="")
        return subprocess.CompletedProcess(["git"], 0, stdout="", stderr="")

    monkeypatch.setattr(version_control, "_run_git", create_tag)
    tag_preview = vcs_tag_release("v2.4.0", "release")
    tag_text = vcs_tag_release("v2.4.0", "release", dry_run=False, confirm=True)
    assert "Dry run: release tag was not created." in tag_preview
    assert "Release tag created." in tag_text
    assert "deadbeef" in tag_text
