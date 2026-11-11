"""Owner-operated KiCad folder chooser for an authenticated local Connector.

Browsing is deliberately root-confined. Only folder display names, opaque tokens,
and a boolean KiCad-project marker leave the device; absolute paths stay local.
No project is shared merely by browsing or binding an id.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import UUID

from kicad_mcp.cloud_windows_native_picker import choose_project_folder

ROOT_FOLDER_ID = "root"
MAX_CHILDREN = 35
MAX_TOKENS = 2048
MAX_NAME = 76
KICAD_PROJECT_SUFFIX = ".kicad_pro"


class LocalFolderBrowser:
    def __init__(self, roots: list[Path], bindings_file: Path) -> None:
        self._roots = [
            path.resolve(strict=True)
            for path in roots
            if path.is_dir() and not path.is_symlink() and not path.is_junction()
        ]
        self._paths: dict[str, Path | None] = {"root": None}
        self._parents: dict[str, str | None] = {"root": None}
        self._bindings_file = bindings_file
        self._selected_native: dict[str, Path] = {}
        self._native_project_file: dict[str, Path] = {}

    def _issue(self, folder: Path, parent: str) -> str:
        if len(self._paths) >= MAX_TOKENS:
            self._paths = {"root": None}
            self._parents = {"root": None}
            raise ValueError("folder_session_expired")
        token = secrets.token_urlsafe(15)
        self._paths[token] = folder
        self._parents[token] = parent
        return token

    @staticmethod
    def _has_no_reparse_components(root: Path, resolved: Path) -> bool:
        """Reject a junction or symlink at any level below the trusted root."""
        current = root
        for component in resolved.relative_to(root).parts:
            current = current / component
            if current.is_symlink() or current.is_junction():
                return False
        return True

    def _safe(self, path: Path) -> bool:
        if path.is_symlink() or path.is_junction() or not path.is_dir():
            return False
        try:
            resolved = path.resolve(strict=True)
            for root in self._roots:
                if resolved == root or resolved.is_relative_to(root):
                    return self._has_no_reparse_components(root, resolved)
        except (OSError, RuntimeError, ValueError):
            return False
        return False

    @staticmethod
    def _has_project(folder: Path) -> bool:
        try:
            with os.scandir(folder) as items:
                return any(
                    item.is_file(follow_symlinks=False)
                    and item.name.lower().endswith(KICAD_PROJECT_SUFFIX)
                    for item in items
                )
        except OSError:
            return False

    @staticmethod
    def _visible_subfolders(path: Path) -> list[tuple[str, Path]]:
        try:
            with os.scandir(path) as entries:
                folders = [
                    (entry.name, Path(entry.path))
                    for entry in entries
                    if not entry.name.startswith(".")
                    and entry.is_dir(follow_symlinks=False)
                    and not entry.is_symlink()
                ]
        except OSError as exc:
            raise ValueError("folder_unavailable") from exc
        folders.sort(key=lambda item: item[0].casefold())
        return folders

    def choose_native(
        self, picker: Callable[[], Path | None] = choose_project_folder
    ) -> dict[str, Any]:
        """Return a selected *folder* and individual project-file tokens.

        A folder with multiple .kicad_pro files requires explicit secondary
        project selection. Never guess a canonical file, expose absolute paths,
        or register any Cloud project during browsing.
        """
        selected = picker()
        if selected is None:
            return {"status": "cancelled"}
        folder = Path(selected)
        try:
            if not folder.is_dir() or folder.is_symlink() or folder.is_junction():
                return {"status": "invalid"}
            resolved = folder.resolve(strict=True)
            with os.scandir(resolved) as entries:
                files = sorted(
                    (
                        Path(e.path)
                        for e in entries
                        if e.is_file(follow_symlinks=False)
                        and e.name.lower().endswith(KICAD_PROJECT_SUFFIX)
                        and not e.is_symlink()
                    ),
                    key=lambda p: p.name.casefold(),
                )
        except (OSError, RuntimeError, ValueError):
            return {"status": "invalid"}
        if not files or len(files) > 25:
            return {"status": "invalid"}
        projects = []
        for file in files:
            token = self._issue(resolved, "root")
            self._selected_native[token] = resolved
            self._native_project_file[token] = file
            projects.append({"id": token, "name": file.stem[:MAX_NAME]})
        return {
            "status": "selected",
            "folderId": projects[0]["id"],
            "name": resolved.name[:MAX_NAME],
            "projects": projects,
        }

    def list_folder(self, token: str) -> dict[str, Any]:
        if token not in self._paths:
            raise ValueError("unknown_folder")
        path: Path | None
        if token in self._selected_native:
            path = self._selected_native[token]
            if path != self._paths[token] or not path.is_dir() or not self._has_project(path):
                raise ValueError("folder_unavailable")
            return {
                "folderId": token,
                "name": path.name[:MAX_NAME],
                "parentId": None,
                "project": True,
                "folders": [],
                "more": False,
            }
        if token == ROOT_FOLDER_ID:
            folders = [(path.name, path) for path in self._roots]
            title = "This computer"
            is_project = False
        else:
            path = self._paths[token]
            if path is None or not self._safe(path):
                raise ValueError("folder_unavailable")
            title = path.name
            is_project = self._has_project(path)
            folders = self._visible_subfolders(path)
        children = []
        # Keep frame size bounded, and never enumerate a whole device.
        for name, folder in folders[:MAX_CHILDREN]:
            if not self._safe(folder):
                continue
            children.append(
                {
                    "id": self._issue(folder, token),
                    "name": name[:MAX_NAME],
                    "project": self._has_project(folder),
                }
            )
        return {
            "folderId": token,
            "name": title[:MAX_NAME],
            "parentId": self._parents[token],
            "project": is_project,
            "folders": children,
            "more": len(folders) > MAX_CHILDREN,
        }

    def get_project_path(self, project_id: str) -> str | None:
        """Owner-only local path inspection. No Cloud persistence."""
        try:
            UUID(project_id)
            if not self._bindings_file.is_file():
                return None
            stored = json.loads(self._bindings_file.read_text(encoding="utf8"))
            if not isinstance(stored, dict):
                return None
            value = stored.get(project_id)
            if not isinstance(value, str) or len(value) > 2048:
                return None
            file = Path(value)
            if (
                not file.is_absolute()
                or file.is_symlink()
                or file.is_junction()
                or not file.is_file()
                or file.suffix.lower() != KICAD_PROJECT_SUFFIX
            ):
                return None
            return str(file)
        except (OSError, RuntimeError, ValueError, TypeError):
            return None

    def _folder_is_bindable(self, token: str, folder: Path) -> bool:
        native = self._selected_native.get(token)
        if native is not None:
            if (
                native != folder
                or not folder.is_dir()
                or folder.is_symlink()
                or folder.is_junction()
            ):
                return False
        elif not self._safe(folder):
            return False
        return self._has_project(folder)

    @staticmethod
    def _unambiguous_project_file(folder: Path) -> Path | None:
        """Never guess which .kicad_pro file the owner intended."""
        try:
            with os.scandir(folder) as entries:
                project_files = [
                    Path(entry.path)
                    for entry in entries
                    if entry.is_file(follow_symlinks=False)
                    and entry.name.lower().endswith(KICAD_PROJECT_SUFFIX)
                    and not entry.is_symlink()
                ]
        except OSError:
            return None
        return project_files[0] if len(project_files) == 1 else None

    def _bindable_project(self, token: str, folder: Path) -> Path | None:
        if not self._folder_is_bindable(token, folder):
            return None
        project = self._native_project_file.get(token)
        if project is None:
            project = self._unambiguous_project_file(folder)
        if project is None:
            return None
        if (
            not project.is_file()
            or project.is_symlink()
            or project.is_junction()
            or project.suffix.lower() != KICAD_PROJECT_SUFFIX
            or project.parent != folder
        ):
            return None
        return project

    def bind(self, token: str, project_id: str) -> bool:
        try:
            UUID(project_id)
        except (ValueError, AttributeError):
            return False
        folder = self._paths.get(token)
        if folder is None:
            return False
        exact_project = self._bindable_project(token, folder)
        if exact_project is None:
            return False
        # The mapping is per-user and local only, not returned via Cloud.
        existing: dict[str, str] = {}
        if self._bindings_file.exists():
            content = json.loads(self._bindings_file.read_text(encoding="utf8"))
            if not isinstance(content, dict):
                raise ValueError("invalid_binding_store")
            existing = {
                k: v for k, v in content.items() if isinstance(k, str) and isinstance(v, str)
            }
        existing[project_id] = str(exact_project)
        self._bindings_file.parent.mkdir(parents=True, exist_ok=True)
        staging = self._bindings_file.with_suffix(".tmp")
        staging.write_text(json.dumps(existing, ensure_ascii=False), encoding="utf8")
        staging.replace(self._bindings_file)
        self._selected_native.pop(token, None)
        self._native_project_file.pop(token, None)
        self._paths.pop(token, None)
        self._parents.pop(token, None)
        return True
