"""Device-scoped, owner-selected secondary project bindings for POSIX MCP."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from kicad_mcp import cloud_pair_keys
from kicad_mcp.cloud_folder_browse_receiver import (
    BrowserFolderService,
    _posix_owner_native_picker,
)
from kicad_mcp.cloud_local_folder_browser import LocalFolderBrowser
from kicad_mcp.cloud_local_registry import _STEM, _UUID, LocalRegisteredRead
from kicad_mcp.cloud_readonly_boundary import OperatorProject

_DENIED = "Invalid local project binding."


def _folder(root: Path, record: dict[str, str]) -> Path:
    if not _UUID.fullmatch(record["deviceId"]):
        raise ValueError(_DENIED)
    return root / "project-bindings" / record["deviceId"]


def _valid_file(file: Path) -> bool:
    return (
        file.is_absolute()
        and file.suffix == ".kicad_pro"
        and _STEM.fullmatch(file.stem) is not None
        and file.is_file()
        and not file.is_symlink()
        and file.resolve(strict=True) == file
    )


def _document(record: dict[str, str], pid: str, file: Path) -> dict[str, str]:
    return {
        "ownerSub": record["ownerSub"],
        "origin": record["cloudOrigin"],
        "deviceId": record["deviceId"],
        "keySlot": record["keySlot"],
        "projectId": pid,
        "file": str(file),
    }


def resolve_secondary(root: Path, record: dict[str, str], pid: str) -> OperatorProject | None:
    """Never trust the legacy unscoped browse cache as write authorization."""
    if not isinstance(pid, str) or not _UUID.fullmatch(pid) or pid == record["projectId"]:
        return None
    try:
        data = cloud_pair_keys._read_private_json(_folder(root, record), pid + ".json")
        file = Path(data["file"])
        if data != _document(record, pid, file) or not _valid_file(file):
            return None
        return OperatorProject(record["deviceId"], pid, file.parent, file.stem)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        return None


def _save(root: Path, record: dict[str, str], pid: str, file: Path) -> bool:
    if not isinstance(pid, str) or not _UUID.fullmatch(pid) or not _valid_file(file):
        return False
    directory = _folder(root, record)
    for folder in (directory.parent, directory):
        folder.mkdir(mode=0o700, exist_ok=True)
        fd = cloud_pair_keys._open_owner_private_dir(folder / "probe")
        os.close(fd)
    data = _document(record, pid, file)
    name = pid + ".json"
    if os.path.lexists(directory / name):
        return cloud_pair_keys._read_private_json(directory, name) == data
    cloud_pair_keys._write_private_json(directory, name, data)
    return cloud_pair_keys._read_private_json(directory, name) == data


def folder_service(
    root: Path,
    record: dict[str, str],
    project: LocalRegisteredRead,
    authorized: Callable[[], bool],
    *,
    native_picker: Callable[[], Path | None] = _posix_owner_native_picker,
) -> BrowserFolderService:
    """Record explicit selection in the exact device's private namespace."""

    def on_bound(pid: str, file: Path) -> bool:
        if not authorized():
            return False
        if pid == record["projectId"]:
            return file == project.project_directory / (project.filename_stem + ".kicad_pro")
        return _save(root, record, pid, file)

    def bound_path(pid: str) -> str | None:
        if not authorized():
            return None
        if pid == record["projectId"]:
            file = project.project_directory / (project.filename_stem + ".kicad_pro")
            return str(file) if _valid_file(file) else None
        target = resolve_secondary(root, record, pid)
        if target is None:
            return None
        return str(target.directory / (target.filename_stem + ".kicad_pro"))

    return BrowserFolderService(
        LocalFolderBrowser([], root / "unused-browser-cache.json"),
        native_picker=native_picker,
        authorization=authorized,
        on_bound=on_bound,
        bound_path=bound_path,
    )
