"""Project discovery behavior independent of FastMCP."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ProjectDiscoveryService:
    """Discover recent projects and inspect directories for KiCad files."""

    find_recent_projects: Callable[[], Sequence[Path]]
    scan_project_dir: Callable[[Path], Mapping[str, Path | None]] = lambda _path: {}

    def list_recent_projects(self) -> str:
        projects = self.find_recent_projects()
        if not projects:
            return "No recent KiCad projects were found on this machine."
        lines = [f"Found {len(projects)} recent project(s):"]
        for index, project in enumerate(projects, start=1):
            lines.append(f"{index}. {project}")
        lines.extend(["", "Call `kicad_set_project()` with one of these paths to activate it."])
        return "\n".join(lines)

    def scan_directory(self, path: str) -> str:
        directory = Path(path).expanduser().resolve()
        if not directory.exists() or not directory.is_dir():
            return "The supplied path is not a directory."
        scan = self.scan_project_dir(directory)
        return "\n".join(
            [
                f"Scan results for {directory}:",
                f"- Project file: {scan['project'] or '(none)'}",
                f"- PCB file: {scan['pcb'] or '(none)'}",
                f"- Schematic file: {scan['schematic'] or '(none)'}",
            ]
        )
