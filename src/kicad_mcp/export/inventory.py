"""Reviewed manufacturing-export inventory discovery helpers."""

from __future__ import annotations

from pathlib import Path

IPC2581_DEFAULT_NAME = "board.ipc2581"


def discover_gerber_output_files(out_dir: Path) -> list[Path]:
    """Return Gerber files using the existing public export-service discovery contract."""
    return sorted(out_dir.glob("*.g*"))


def discover_drill_output_files(out_dir: Path) -> list[Path]:
    """Return drill files using the existing public export-service discovery contract."""
    return sorted(out_dir.glob("*.drl")) + sorted(out_dir.glob("*.xnc"))


__all__ = [
    "IPC2581_DEFAULT_NAME",
    "discover_drill_output_files",
    "discover_gerber_output_files",
]
