"""Version-control helpers for project checkpoints."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from .validation import _entries, _run_drc_report

_CHECKPOINT_TRAILER = "KiCad-MCP-Checkpoint: true"
_DEFAULT_GIT_NAME = "KiCad MCP Pro"
_DEFAULT_GIT_EMAIL = "kicad-mcp@example.invalid"


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
    if repo_root == project_dir:
        return "."
    return project_dir.relative_to(repo_root).as_posix()


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
            lines.append(
                f"- {short_hash} | {created_at} | {subject} | commit={commit_hash}"
            )
        return "\n".join(lines)

    @mcp.tool()
    def vcs_restore_checkpoint(commit_hash: str) -> str:
        """Restore project files from a previous checkpoint commit."""
        if not commit_hash.strip():
            raise ValueError("Commit hash must not be empty.")
        project_dir = _resolve_project_dir()
        repo_root = _git_repo_root(project_dir)
        if repo_root is None:
            raise ValueError("No Git repository was found. Run vcs_init_git() first.")
        pathspec = _project_pathspec(repo_root, project_dir)
        _run_git(repo_root, "rev-parse", "--verify", commit_hash)
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
            lines.append(f"- Previous uncommitted state was backed up: {stash_note}")
        else:
            lines.append("- Previous uncommitted state was already clean.")
        return "\n".join(lines)

    @mcp.tool()
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
