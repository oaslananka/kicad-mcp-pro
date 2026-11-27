"""Publish staged files without knowingly overwriting concurrent edits."""

from __future__ import annotations

import time
from pathlib import Path


class FileChangedError(RuntimeError):
    """The destination no longer matches the caller's original bytes."""


def replace_if_unchanged(temporary: Path, destination: Path, original: bytes) -> None:
    """Check the baseline before each replacement; retry Windows sharing errors only."""
    for attempt in range(6):
        if destination.is_symlink() or destination.read_bytes() != original:
            raise FileChangedError(
                f"The file changed before replacement: {destination.name}. "
                "Retry the edit against the current file."
            )
        try:
            temporary.replace(destination)
            return
        except PermissionError as exc:
            if getattr(exc, "winerror", None) not in {5, 32, 33} or attempt == 5:
                raise
            time.sleep(0.02 * (attempt + 1))
