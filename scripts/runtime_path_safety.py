"""Filesystem boundary for repository automation scripts."""

from __future__ import annotations

import tempfile
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def approved_runtime_path(
    raw_path: str | Path,
    *,
    extra_roots: Iterable[Path] = (),
) -> Path:
    """Resolve a path under the repository, system temp, or explicit trusted roots."""
    resolved = Path(raw_path).expanduser().resolve()
    roots = (
        REPO_ROOT,
        Path(tempfile.gettempdir()).resolve(),
        *(Path(root).expanduser().resolve() for root in extra_roots),
    )
    if any(resolved.is_relative_to(root) for root in roots):
        return resolved
    allowed = " or ".join(str(root) for root in roots)
    raise ValueError(f"Path '{resolved}' is outside approved automation roots: {allowed}.")
