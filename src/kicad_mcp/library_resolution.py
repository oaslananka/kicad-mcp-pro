"""Active-project KiCad library resolution shared by tool surfaces."""

from __future__ import annotations

from pathlib import Path

from .config import get_config
from .utils.library_tables import (
    footprint_library_dirs as discover_footprint_library_dirs,
)
from .utils.library_tables import resolve_footprint_file


def active_project_dir() -> Path | None:
    """Return the configured project directory used for KiCad table expansion."""
    cfg = get_config()
    if cfg.project_file is not None:
        return cfg.project_file.parent
    return cfg.project_dir


def footprint_library_dirs() -> dict[str, Path]:
    """Return all active configured and table-discovered footprint libraries."""
    cfg = get_config()
    return discover_footprint_library_dirs(
        configured_root=cfg.footprint_library_dir,
        project_dir=active_project_dir(),
    )


def footprint_file(library: str, footprint: str) -> Path:
    """Resolve one footprint against the active project and KiCad configuration."""
    cfg = get_config()
    return resolve_footprint_file(
        library,
        footprint,
        configured_root=cfg.footprint_library_dir,
        project_dir=active_project_dir(),
    )


__all__ = ["active_project_dir", "footprint_file", "footprint_library_dirs"]
