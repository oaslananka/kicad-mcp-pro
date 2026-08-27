"""Active project context behavior independent of FastMCP."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ApplyProjectProtocol(Protocol):
    def __call__(
        self,
        project_dir: Path,
        *,
        project_file: Path | None = None,
        pcb_file: Path | None = None,
        sch_file: Path | None = None,
        output_dir: Path | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class ProjectContextService:
    """Resolve and activate the current project without depending on FastMCP."""

    scan_project_dir: Callable[[Path], Mapping[str, Path | None]]
    apply_project: ApplyProjectProtocol
    clear_cache: Callable[[], None]
    reset_connection: Callable[[], None]
    reset_live_edit: Callable[[], None]
    render_project_info: Callable[[], str]

    def set_project(
        self,
        project_dir: str,
        pcb_file: str = "",
        sch_file: str = "",
        output_dir: str = "",
    ) -> str:
        """Set the active project directory and resolved KiCad file paths."""
        project_path = Path(project_dir).expanduser().resolve()
        if not project_path.exists() or not project_path.is_dir():
            return "Project directory does not exist or is not a directory."

        scan = self.scan_project_dir(project_path)
        selected_pcb = Path(pcb_file).expanduser().resolve() if pcb_file else scan.get("pcb")
        selected_sch = Path(sch_file).expanduser().resolve() if sch_file else scan.get("schematic")
        selected_project = scan.get("project")
        if selected_project is not None and selected_pcb is None and selected_sch is None:
            return (
                "E_PROJECT_SCAN_INCOMPLETE: Found a .kicad_pro file but no matching "
                ".kicad_pcb or .kicad_sch file in the selected directory. "
                "Add at least one board or schematic file before activating this project."
            )
        selected_output = (
            Path(output_dir).expanduser().resolve() if output_dir else project_path / "output"
        )

        self.apply_project(
            project_path,
            project_file=selected_project,
            pcb_file=selected_pcb,
            sch_file=selected_sch,
            output_dir=selected_output,
        )
        self.clear_cache()
        self.reset_connection()
        self.reset_live_edit()
        return self.render_project_info()

    def get_project_info(self) -> str:
        """Render the current project configuration."""
        return self.render_project_info()
