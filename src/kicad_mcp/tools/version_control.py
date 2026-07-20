"""Version-control helpers for project checkpoints."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from .gates import _combined_status
from .metadata import headless_compatible
from .validation import _entries, _evaluate_project_gate, _run_drc_report

_CHECKPOINT_TRAILER = "KiCad-MCP-Checkpoint: true"
_DEFAULT_GIT_NAME = "KiCad MCP Pro"
_DEFAULT_GIT_EMAIL = "kicad-mcp@example.invalid"
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


def _git_executable() -> str:
    git = shutil.which("git")
    if git is None:
        raise ValueError("Git was not found on PATH. Install Git and retry.")
    return git


def _resolve_project_dir(project_dir: str | None = None) -> Path:
    if project_dir:
        path = Path(project_dir).expanduser().resolve()
    else:
        cfg = get_config()
        if cfg.project_dir is None:
            raise ValueError(
                "No active project directory is configured. Call kicad_set_project() or "
                "pass project_dir explicitly."
            )
        path = cfg.project_dir.resolve()
    if not path.exists():
        raise FileNotFoundError(f"Project directory '{path}' does not exist.")
    return path


def _git_subprocess_env() -> dict[str, str]:
    """Return a Git environment detached from the caller repository context."""
    env = os.environ.copy()
    for variable in _REPOSITORY_LOCAL_GIT_ENV:
        env.pop(variable, None)
    return env


def _run_git(
    repo_dir: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        [_git_executable(), *args],
        cwd=repo_dir,
        capture_output=True,
        text=True,
        errors="replace",
        env=_git_subprocess_env(),
        timeout=30,
        check=False,
    )
    if check and result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or "unknown git error"
        raise ValueError(f"Git command failed ({' '.join(args)}): {error}")
    return result


def _git_repo_root(project_dir: Path) -> Path | None:
    result = _run_git(project_dir, "rev-parse", "--show-toplevel", check=False)
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _project_pathspec(repo_root: Path, project_dir: Path) -> str:
    resolved_root = repo_root.resolve()
    resolved_project = project_dir.resolve()
    if resolved_root == resolved_project:
        return "."
    try:
        return resolved_project.relative_to(resolved_root).as_posix()
    except ValueError as exc:
        raise ValueError(
            f"Project directory {resolved_project} is outside Git repository {resolved_root}."
        ) from exc


def _verify_repo_scope(repo_root: Path, project_dir: Path) -> None:
    """Fail closed when Git resolves a different repository than the active project."""
    expected = repo_root.resolve()
    _project_pathspec(expected, project_dir)
    actual = _git_repo_root(project_dir)
    if actual != expected:
        raise ValueError(
            "Git repository context changed before a destructive operation: "
            f"expected {expected}, resolved {actual or '<none>'}."
        )


def _ensure_git_identity(repo_root: Path) -> list[str]:
    notes: list[str] = []
    for key, default in (
        ("user.name", _DEFAULT_GIT_NAME),
        ("user.email", _DEFAULT_GIT_EMAIL),
    ):
        existing = _run_git(repo_root, "config", "--get", key, check=False).stdout.strip()
        if existing:
            continue
        _run_git(repo_root, "config", key, default)
        notes.append(f"{key}={default}")
    return notes


def _ensure_gitignore(project_dir: Path) -> None:
    gitignore = project_dir / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    wanted = ["output/", "*.step", "*.stp", "*.zip"]
    missing = [line for line in wanted if line not in lines]
    if not missing:
        return
    updated = "\n".join(lines + missing) + "\n" if lines else "\n".join(missing) + "\n"
    gitignore.write_text(
        updated,
        encoding="utf-8",
    )


def _project_status(repo_root: Path, pathspec: str) -> list[str]:
    result = _run_git(repo_root, "status", "--short", "--", pathspec)
    return [line for line in result.stdout.splitlines() if line.strip()]


def _tracked_path_from_status_line(line: str) -> str:
    parts = line.split(maxsplit=1)
    if len(parts) == 1:
        return ""
    return parts[1].strip()


def _has_session_scraps(status_lines: list[str]) -> str | None:
    for line in status_lines:
        path = _tracked_path_from_status_line(line)
        if path.endswith(".kicad_pro.lock"):
            return path
        for segment in Path(path).parts:
            if segment.startswith("~$"):
                return path
    return None


def _checkpoint_log_args(repo_root: Path, pathspec: str) -> list[str]:
    return [
        "log",
        "--grep",
        _CHECKPOINT_TRAILER,
        "--pretty=format:%H%x09%h%x09%cI%x09%s",
        "--",
        pathspec,
    ]


def _stash_project_state(repo_root: Path, pathspec: str, checkpoint_hash: str) -> str | None:
    status_lines = _project_status(repo_root, pathspec)
    if not status_lines:
        return None
    message = f"kicad-mcp backup before restore {checkpoint_hash}"
    result = _run_git(
        repo_root,
        "stash",
        "push",
        "--include-untracked",
        "-m",
        message,
        "--",
        pathspec,
    )
    output = result.stdout.strip()
    if not output:
        return message
    return output


def _create_restore_branch(repo_root: Path, checkpoint_hash: str) -> str:
    branch_name = f"mcp-restore-{checkpoint_hash[:7]}"
    _run_git(repo_root, "branch", "-f", branch_name, "refs/stash")
    return branch_name


def _commit_blocked_by_drc() -> str | None:
    cfg = get_config()
    if cfg.pcb_file is None or not cfg.pcb_file.exists():
        return None
    _, report, error = _run_drc_report("vcs_checkpoint_drc.json")
    if report is None:
        return f"DRC could not run before committing: {error or 'unknown error'}"
    violations = _entries(report, "violations")
    unconnected = _entries(report, "unconnected_items")
    if not violations and not unconnected:
        return None
    return (
        f"DRC reported {len(violations)} violation(s) and {len(unconnected)} "
        "unconnected item(s). Resolve them or rerun with auto_drc=False."
    )


def register(mcp: FastMCP) -> None:
    """Register version-control tools."""

    @mcp.tool()
    @headless_compatible
    def vcs_init_git(project_dir: str) -> str:
        """Initialize a Git repository for the KiCad project directory."""
        target_dir = _resolve_project_dir(project_dir)
        repo_root = _git_repo_root(target_dir)
        created = False
        if repo_root is None:
            _run_git(target_dir, "init", "--initial-branch", "main")
            repo_root = target_dir
            created = True

        identity_notes = _ensure_git_identity(repo_root)
        _ensure_gitignore(target_dir)
        return "\n".join(
            [
                "Git repository ready.",
                f"- Repo root: {repo_root}",
                f"- Project dir: {target_dir}",
                f"- Created new repo: {'yes' if created else 'no'}",
                (
                    "- Local identity defaults: " + ", ".join(identity_notes)
                    if identity_notes
                    else "- Local identity defaults: unchanged"
                ),
            ]
        )

    @mcp.tool()
    @headless_compatible
    def vcs_commit_checkpoint(message: str, auto_drc: bool = True) -> str:
        """Commit the current project state as a named checkpoint."""
        if not message.strip():
            raise ValueError("Checkpoint message must not be empty.")
        project_dir = _resolve_project_dir()
        repo_root = _git_repo_root(project_dir)
        if repo_root is None:
            raise ValueError("No Git repository was found. Run vcs_init_git() first.")
        pathspec = _project_pathspec(repo_root, project_dir)
        _ensure_git_identity(repo_root)

        if auto_drc:
            if blocked_reason := _commit_blocked_by_drc():
                raise ValueError(blocked_reason)

        _run_git(repo_root, "add", "--", pathspec)
        status_lines = _project_status(repo_root, pathspec)
        if not status_lines:
            return "No project changes were detected, so no checkpoint commit was created."
        if scrap_path := _has_session_scraps(status_lines):
            raise ValueError(
                "Refusing to commit KiCad session scrap files. Remove the lock/temp file first: "
                f"{scrap_path}"
            )

        body = f"{_CHECKPOINT_TRAILER}\nProject-Path: {pathspec}"
        _run_git(repo_root, "commit", "-m", message.strip(), "-m", body, "--", pathspec)
        commit_hash = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()
        return "\n".join(
            [
                "Checkpoint committed.",
                f"- Commit: {commit_hash}",
                f"- Message: {message.strip()}",
                f"- Path scope: {pathspec}",
                f"- Auto DRC: {'enabled' if auto_drc else 'disabled'}",
            ]
        )

    @mcp.tool()
    @headless_compatible
    def vcs_list_checkpoints() -> str:
        """List checkpoint commits created by the MCP tool."""
        project_dir = _resolve_project_dir()
        repo_root = _git_repo_root(project_dir)
        if repo_root is None:
            raise ValueError("No Git repository was found. Run vcs_init_git() first.")
        pathspec = _project_pathspec(repo_root, project_dir)
        result = _run_git(repo_root, *_checkpoint_log_args(repo_root, pathspec))
        entries = [line for line in result.stdout.splitlines() if line.strip()]
        if not entries:
            return "No KiCad MCP checkpoints were found for the active project."

        lines = [f"Checkpoints ({len(entries)} total):"]
        for entry in entries[:20]:
            commit_hash, short_hash, created_at, subject = entry.split("\t", 3)
            lines.append(f"- {short_hash} | {created_at} | {subject} | commit={commit_hash}")
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def vcs_restore_checkpoint(commit_hash: str, confirm: bool = False) -> str:
        """Restore project files and keep a recovery branch for the stashed pre-restore state."""
        if not commit_hash.strip():
            raise ValueError("Commit hash must not be empty.")
        project_dir = _resolve_project_dir()
        repo_root = _git_repo_root(project_dir)
        if repo_root is None:
            raise ValueError("No Git repository was found. Run vcs_init_git() first.")
        pathspec = _project_pathspec(repo_root, project_dir)
        _run_git(repo_root, "rev-parse", "--verify", commit_hash)
        if not confirm:
            return "\n".join(
                [
                    "Dry run: checkpoint restore was not executed.",
                    f"- Commit: {commit_hash}",
                    f"- Path scope: {pathspec}",
                    "Rerun with confirm=true to restore project files.",
                ]
            )
        _verify_repo_scope(repo_root, project_dir)
        stash_note = _stash_project_state(repo_root, pathspec, commit_hash)
        _run_git(
            repo_root,
            "restore",
            "--source",
            commit_hash,
            "--staged",
            "--worktree",
            "--",
            pathspec,
        )
        lines = [
            "Checkpoint restored.",
            f"- Commit: {commit_hash}",
            f"- Path scope: {pathspec}",
        ]
        if stash_note is not None:
            recovery_branch = _create_restore_branch(repo_root, commit_hash)
            lines.append(f"- Previous uncommitted state was backed up: {stash_note}")
            lines.append(f"- Recovery branch: {recovery_branch}")
        else:
            lines.append("- Previous uncommitted state was already clean.")
        return "\n".join(lines)

    @mcp.tool()
    @headless_compatible
    def vcs_diff_with_checkpoint(commit_hash: str) -> str:
        """Show the current project diff versus a checkpoint commit."""
        if not commit_hash.strip():
            raise ValueError("Commit hash must not be empty.")
        project_dir = _resolve_project_dir()
        repo_root = _git_repo_root(project_dir)
        if repo_root is None:
            raise ValueError("No Git repository was found. Run vcs_init_git() first.")
        pathspec = _project_pathspec(repo_root, project_dir)
        _run_git(repo_root, "rev-parse", "--verify", commit_hash)
        summary = _run_git(repo_root, "diff", "--stat", commit_hash, "--", pathspec).stdout.strip()
        changed = _run_git(
            repo_root,
            "diff",
            "--name-status",
            commit_hash,
            "--",
            pathspec,
        ).stdout.strip()
        if not changed:
            return f"No project changes were found versus checkpoint {commit_hash}."
        return "\n".join(
            [
                f"Diff versus checkpoint {commit_hash}:",
                changed,
                "",
                "Stat summary:",
                summary or "(no summary available)",
            ]
        )

    @mcp.tool()
    @headless_compatible
    def vcs_tag_release(tag: str, message: str, dry_run: bool = True, confirm: bool = False) -> str:
        """Create an annotated release tag after the full project quality gate passes."""
        if not tag.strip():
            raise ValueError("Release tag must not be empty.")
        if not message.strip():
            raise ValueError("Release tag message must not be empty.")
        project_dir = _resolve_project_dir()
        repo_root = _git_repo_root(project_dir)
        if repo_root is None:
            raise ValueError("No Git repository was found. Run vcs_init_git() first.")
        if _combined_status(_evaluate_project_gate()) != "PASS":
            raise ValueError(
                "Release tagging is only allowed after project_quality_gate() returns PASS."
            )
        _run_git(repo_root, "rev-parse", "--verify", "HEAD")
        existing = _run_git(repo_root, "tag", "--list", tag.strip(), check=False).stdout.strip()
        if existing:
            raise ValueError(f"Git tag '{tag.strip()}' already exists.")
        if dry_run:
            return "\n".join(
                [
                    "Dry run: release tag was not created.",
                    f"- Tag: {tag.strip()}",
                    f"- Message: {message.strip()}",
                    "Rerun with dry_run=false and confirm=true after local and CI gates pass.",
                ]
            )
        if not confirm:
            raise ValueError("Release tagging requires dry_run=false and confirm=true.")
        _run_git(repo_root, "tag", "-a", tag.strip(), "-m", message.strip())
        commit_hash = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()
        return "\n".join(
            [
                "Release tag created.",
                f"- Tag: {tag.strip()}",
                f"- Commit: {commit_hash}",
                f"- Message: {message.strip()}",
            ]
        )
