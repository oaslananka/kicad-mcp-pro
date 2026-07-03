"""Workspace-safe path helpers."""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath

from .errors import UnsafePathError


def normalize_workspace_root(path: str | Path | None, *, fallback: Path) -> Path:
    """Return an absolute workspace root."""
    if path is None or path == "":
        return fallback.expanduser().resolve()
    return Path(path).expanduser().resolve()


def assert_within(root: Path, path: Path) -> None:
    """Raise when ``path`` is outside ``root`` after resolution."""
    resolved_root = root.expanduser().resolve()
    resolved_path = path.expanduser().resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise UnsafePathError(
            f"The requested path '{resolved_path}' escapes workspace root '{resolved_root}'."
        ) from exc


def resolve_under(root: Path, raw_path: str | Path, *, allow_absolute: bool = True) -> Path:
    """Resolve ``raw_path`` under ``root`` and block traversal outside it."""
    reject_foreign_windows_path(raw_path)
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        if not allow_absolute:
            raise UnsafePathError("Absolute paths are not allowed.")
        resolved = candidate.resolve()
    else:
        resolved = (root / candidate).resolve()
    assert_within(root, resolved)
    return resolved


def relative_subpath(raw_path: str | Path) -> Path:
    """Return a safe relative subpath."""
    reject_foreign_windows_path(raw_path)
    candidate = Path(raw_path).expanduser()
    if candidate.is_absolute():
        raise UnsafePathError("Output subdirectories must be relative to the output directory.")
    if any(part == ".." for part in candidate.parts):
        raise UnsafePathError("Output subdirectories cannot contain parent traversal.")
    return candidate


def reject_foreign_windows_path(raw_path: str | Path) -> None:
    """Reject Windows drive/UNC paths before POSIX treats backslashes as filename bytes."""
    if os.name == "nt":
        return

    windows_path = PureWindowsPath(str(raw_path))
    if windows_path.is_absolute():
        raise UnsafePathError(
            "Windows drive or UNC paths are not valid on this platform; provide a path "
            "inside the configured workspace root using this operating system's path format."
        )
