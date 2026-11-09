"""Diagnostic repair and clean application uninstall/cleanup service.

Preserves user KiCad schematic, board, and project files at all times.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from kicad_mcp.cloud_pair import default_registry_root
from kicad_mcp.discovery import discover_kicad_cli, find_kicad_version
from kicad_mcp.services.client_config import (
    ClientConfigError,
    get_owned_client_configs,
    remove_client_config_entry,
)

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
    client_entries_to_remove: list[dict[str, str]] = field(default_factory=list)


@dataclass
class CleanupResult:
    success: bool
    removed_targets: list[str] = field(default_factory=list)
    preserved_user_files: list[str] = field(default_factory=list)
    remaining_targets: list[str] = field(default_factory=list)
    failed_client_configs: list[str] = field(default_factory=list)
    cloud_revocation: str = "not_attempted"
    credentials: str = "preserved"
    message: str = ""


def _preserved_kicad_paths(user_project_roots: list[Path] | None) -> list[str]:
    """Report user-owned design files without changing or deleting any."""
    preserved: list[str] = []
    for folder in user_project_roots or []:
        root = Path(folder)
        if not root.is_dir():
            continue
        for file in root.rglob("*"):
            if file.is_file() and file.suffix.lower() in _KICAD_PROJECT_EXTENSIONS:
                preserved.append(str(file.resolve()))
    return preserved


def _remove_owned_client_entries(registry_root: Path) -> list[str]:
    """Remove only registered entries and report failures for user recovery."""
    failed: list[str] = []
    for client, paths in get_owned_client_configs(registry_root).items():
        for path in paths:
            try:
                remove_client_config_entry(client, Path(path), registry_root=registry_root)
            except (ClientConfigError, OSError):
                failed.append(str(path))
    return failed


def _remove_application_targets(targets: list[str]) -> list[str]:
    """Recheck each previewed target before deleting application state."""
    removed: list[str] = []
    for target_str in targets:
        target = Path(target_str)
        if target.suffix.lower() in _KICAD_PROJECT_EXTENSIONS:
            continue
        try:
            if target.is_file() or target.is_symlink():
                target.unlink()
                removed.append(str(target))
        except OSError:
            pass
    return removed


class MaintenanceService:
    """Provides repair diagnostics and safe application-state cleanup."""

    def __init__(self, registry_root: Path | None = None) -> None:
        self.registry_root = Path(registry_root) if registry_root else default_registry_root()

    def preview_repair(self) -> RepairPreview:
        items: list[dict[str, Any]] = []
        try:
            cli_path = discover_kicad_cli()
            kicad_ver = find_kicad_version(cli_path)
            items.append(
                {
                    "component": "kicad",
                    "status": "ok" if kicad_ver else "warn",
                    "detail": f"KiCad version: {kicad_ver}"
                    if kicad_ver
                    else "KiCad CLI located but version unknown",
                }
            )
        except Exception:
            items.append(
                {
                    "component": "kicad",
                    "status": "warn",
                    "detail": "KiCad CLI not found in default paths",
                }
            )

        reg_exists = self.registry_root.is_dir()
        items.append(
            {
                "component": "storage",
                "status": "ok" if reg_exists else "info",
                "detail": f"Application storage at {self.registry_root}",
            }
        )

        owned = get_owned_client_configs(self.registry_root)
        items.append(
            {
                "component": "clients",
                "status": "ok",
                "detail": f"Configured AI clients: {len(owned)}",
            }
        )

        healthy = all(item["status"] in ("ok", "info") for item in items)
        return RepairPreview(healthy=healthy, items=items)

    def apply_repair(self) -> RepairResult:
        repaired: list[str] = []
        if not self.registry_root.exists():
            self.registry_root.mkdir(parents=True, exist_ok=True)
            repaired.append("created_storage_root")

        status = self.preview_repair()
        return RepairResult(
            success=status.healthy,
            repaired_items=repaired,
            message=(
                "Local repair checks passed."
                if status.healthy
                else "Repair partially completed; unresolved checks need attention."
            ),
        )

    def preview_cleanup(
        self,
        user_project_roots: list[Path] | None = None,
    ) -> CleanupPreview:
        targets: list[str] = []
        preserved = _preserved_kicad_paths(user_project_roots)

        for name in ("connector-enabled.json", "connector-status.json", "active_project.json"):
            item = self.registry_root / name
            if item.is_file() and not item.is_symlink():
                targets.append(str(item))

        client_entries = [
            {"client": client, "config_file": str(path)}
            for client, paths in get_owned_client_configs(self.registry_root).items()
            for path in paths
        ]
        return CleanupPreview(
            targets_to_remove=targets,
            preserved_user_files=preserved,
            client_entries_to_remove=client_entries,
        )

    def apply_cleanup(
        self,
        user_project_roots: list[Path] | None = None,
        clean_client_configs: bool = True,
    ) -> CleanupResult:
        preview = self.preview_cleanup(user_project_roots=user_project_roots)

        failed_configs = (
            _remove_owned_client_entries(self.registry_root) if clean_client_configs else []
        )
        removed = _remove_application_targets(preview.targets_to_remove)
        remaining = [
            name
            for name in preview.targets_to_remove
            if Path(name).exists() or Path(name).is_symlink()
        ]
        complete = not (remaining or failed_configs)
        return CleanupResult(
            success=complete,
            removed_targets=removed,
            preserved_user_files=preview.preserved_user_files,
            remaining_targets=remaining,
            failed_client_configs=failed_configs,
            # A local cleanup is never proof of a Cloud-side access revoke.
            cloud_revocation="not_attempted",
            credentials="preserved",
            message=(
                (
                    "Local connector settings cleaned."
                    if complete
                    else "Local cleanup incomplete; retry after resolving the listed failures."
                )
                + " Cloud access and stored credentials were not revoked."
            ),
        )
