"""Serialize local project-metadata updates and publish complete files."""

from __future__ import annotations

import os
import stat
import tempfile
import threading
from collections.abc import Callable
from functools import wraps
from pathlib import Path

from .cache import clear_ttl_cache

_METADATA_LOCK = threading.RLock()


def serialized_metadata_write[**P, R](func: Callable[P, R]) -> Callable[P, R]:
    """Hold the shared process-local lock across read, mutation and publish."""

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        with _METADATA_LOCK:
            return func(*args, **kwargs)

    return wrapper


def atomic_metadata_write(path: Path, content: str) -> None:
    """Replace the caller-pinned path after flushing the complete payload."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="",
            delete=False,
            dir=path.parent,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            temporary.chmod(stat.S_IMODE(path.stat().st_mode))
        temporary.replace(path)
        clear_ttl_cache()
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
