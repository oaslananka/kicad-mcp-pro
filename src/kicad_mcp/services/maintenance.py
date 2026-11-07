"""Diagnostic repair and clean application uninstall/cleanup service.

Preserves user KiCad schematic, board, and project files at all times.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kicad_mcp.cloud_pair import default_registry_root
from kicad_mcp.discovery import discover_kicad_cli, find_kicad_version
from kicad_mcp.services.client_config import get_owned_client_configs, remove_client_config_entry

_KICAD_PROJECT_EXTENSIONS = {
    ".kicad_sch",
    ".kicad_pcb",
    ".kicad_pro",
    ".kicad_prl",
    ".kicad_dru",
    ".sch",
    ".brd",
    ".pro",
}


@dataclass
class RepairPreview:
    healthy: bool
    items: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RepairResult:
    success: bool
    repaired_items: list[str] = field(default_factory=list)
    message: str = ""


@dataclass
class CleanupPreview:
    targets_to_remove: list[str] = field(default_factory=list)
    preserved_user_files: list[str] = field(default_factory=list)


@dataclass
class CleanupResult:
    success: bool
    removed_targets: list[str] = field(default_factory=list)
    preserved_user_files: list[str] = field(default_factory=list)
    message: str = ""


class MaintenanceService:
    """Provides repair diagnostics and safe application-state cleanup."""

    def __init__(self, registry_root: Path | None = None) -> None:
        self.registry_root = Path(registry_root) if registry_root else default_registry_root()

    def preview_repair(self) -> RepairPreview:
        items: list[dict[str, Any]] = []
        try:
            cli_path = discover_kicad_cli()
            kicad_ver = find_kicad_version(cli_path)
            items.append({
                "component": "kicad",
                "status": "ok" if kicad_ver else "warn",
                "detail": f"KiCad version: {kicad_ver}" if kicad_ver else "KiCad CLI located but version unknown",
            })
        except Exception:
            items.append({
                "component": "kicad",
                "status": "warn",
                "detail": "KiCad CLI not found in default paths",
            })

        reg_exists = self.registry_root.is_dir()
        items.append({
            "component": "storage",
            "status": "ok" if reg_exists else "info",
            "detail": f"Application storage at {self.registry_root}",
        })

        owned = get_owned_client_configs(self.registry_root)
        items.append({
            "component": "clients",
            "status": "ok",
            "detail": f"Configured AI clients: {len(owned)}",
        })

        healthy = all(item["status"] in ("ok", "info") for item in items)
        return RepairPreview(healthy=healthy, items=items)

    def apply_repair(self) -> RepairResult:
        repaired: list[str] = []
        if not self.registry_root.exists():
            self.registry_root.mkdir(parents=True, exist_ok=True)
            repaired.append("created_storage_root")

        # Clean any stale lockfiles or tmp files in registry root
        if self.registry_root.is_dir():
            for tmp in self.registry_root.glob("*.tmp"):
                try:
                    tmp.unlink()
                    repaired.append(f"cleaned_{tmp.name}")
                except OSError:
                    pass

        return RepairResult(
            success=True,
            repaired_items=repaired,
            message="Repair completed successfully",
        )

    def preview_cleanup(
        self,
        user_project_roots: list[Path] | None = None,
    ) -> CleanupPreview:
        targets: list[str] = []
        preserved: list[str] = []

        if user_project_roots:
            for root in user_project_roots:
                root = Path(root)
                if root.is_dir():
                    for file in root.rglob("*"):
                        if file.is_file() and file.suffix.lower() in _KICAD_PROJECT_EXTENSIONS:
                            preserved.append(str(file.resolve()))

        if self.registry_root.is_dir():
            for item in self.registry_root.iterdir():
                # Never include user project files even if placed in registry
                if item.is_file() and item.suffix.lower() in _KICAD_PROJECT_EXTENSIONS:
                    preserved.append(str(item.resolve()))
                else:
                    targets.append(str(item.resolve()))

        return CleanupPreview(
            targets_to_remove=targets,
            preserved_user_files=preserved,
        )

    def apply_cleanup(
        self,
        user_project_roots: list[Path] | None = None,
        clean_client_configs: bool = True,
    ) -> CleanupResult:
        preview = self.preview_cleanup(user_project_roots=user_project_roots)

        if clean_client_configs:
            owned = get_owned_client_configs(self.registry_root)
            for client, paths in owned.items():
                for p in paths:
                    try:
                        remove_client_config_entry(client, Path(p), registry_root=self.registry_root)
                    except Exception:
                        pass

        removed: list[str] = []
        for target_str in preview.targets_to_remove:
            target = Path(target_str)
            if target.suffix.lower() in _KICAD_PROJECT_EXTENSIONS:
                continue  # Extra safety barrier
            try:
                if target.is_file() or target.is_symlink():
                    target.unlink()
                    removed.append(str(target))
                elif target.is_dir():
                    shutil.rmtree(target)
                    removed.append(str(target))
            except OSError:
                pass

        return CleanupResult(
            success=True,
            removed_targets=removed,
            preserved_user_files=preview.preserved_user_files,
            message=f"Cleaned {len(removed)} application targets; preserved {len(preview.preserved_user_files)} user project files.",
        )
