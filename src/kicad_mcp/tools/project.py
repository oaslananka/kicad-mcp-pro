"""Project setup and discovery tools."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

from .. import __version__
from ..config import get_config
from ..connection import KiCadConnectionError, get_kicad, reset_connection
from ..discovery import find_kicad_version, find_recent_projects, scan_project_dir
from .router import TOOL_CATEGORIES


class ScanDirectoryInput(BaseModel):
    """Directory scan parameters."""

    path: str = Field(min_length=1, max_length=1000)


class CreateProjectInput(BaseModel):
    """New project creation parameters."""

    path: str = Field(min_length=1, max_length=1000)
    name: str = Field(min_length=1, max_length=120)


def _render_project_info() -> str:
    cfg = get_config()
    cli_status = "found" if cfg.kicad_cli.exists() else "missing"
    return "\n".join(
        [
            "Current project configuration:",
            f"- Project directory: {cfg.project_dir or '(not set)'}",
            f"- Project file: {cfg.project_file or '(not set)'}",
            f"- PCB file: {cfg.pcb_file or '(not set)'}",
            f"- Schematic file: {cfg.sch_file or '(not set)'}",
            f"- Output directory: {cfg.output_dir or '(not set)'}",
            f"- KiCad CLI: {cfg.kicad_cli} ({cli_status})",
            f"- Server profile: {cfg.profile}",
            f"- Experimental tools: {cfg.enable_experimental_tools}",
        ]
    )


def _new_project_files(project_dir: Path, name: str) -> tuple[Path, Path, Path]:
    project_file = project_dir / f"{name}.kicad_pro"
    pcb_file = project_dir / f"{name}.kicad_pcb"
    sch_file = project_dir / f"{name}.kicad_sch"
    return project_file, pcb_file, sch_file


def register(mcp: FastMCP) -> None:
    """Register project management tools."""

    @mcp.tool()
    def kicad_set_project(
        project_dir: str,
        pcb_file: str = "",
        sch_file: str = "",
        output_dir: str = "",
    ) -> str:
        """Set the active KiCad project directory and file paths."""
        cfg = get_config()
        project_path = Path(project_dir).expanduser().resolve()
        if not project_path.exists() or not project_path.is_dir():
            return "Project directory does not exist or is not a directory."

        scan = scan_project_dir(project_path)
        selected_pcb = Path(pcb_file).expanduser().resolve() if pcb_file else scan.get("pcb")
        selected_sch = Path(sch_file).expanduser().resolve() if sch_file else scan.get("schematic")
        selected_project = scan.get("project")
        selected_output = (
            Path(output_dir).expanduser().resolve() if output_dir else project_path / "output"
        )

        cfg.apply_project(
            project_path,
            project_file=selected_project,
            pcb_file=selected_pcb,
            sch_file=selected_sch,
            output_dir=selected_output,
        )
        reset_connection()
        return _render_project_info()

    @mcp.tool()
    def kicad_get_project_info() -> str:
        """Show the currently configured KiCad project paths."""
        return _render_project_info()

    @mcp.tool()
    def kicad_list_recent_projects() -> str:
        """List recently opened KiCad projects from KiCad's config files."""
        projects = find_recent_projects()
        if not projects:
            return "No recent KiCad projects were found on this machine."

        lines = [f"Found {len(projects)} recent project(s):"]
        for index, project in enumerate(projects, start=1):
            lines.append(f"{index}. {project}")
        lines.append("")
        lines.append("Call `kicad_set_project()` with one of these paths to activate it.")
        return "\n".join(lines)

    @mcp.tool()
    def kicad_scan_directory(path: str) -> str:
        """Scan a directory and report any KiCad project files it contains."""
        payload = ScanDirectoryInput(path=path)
        directory = Path(payload.path).expanduser().resolve()
        if not directory.exists() or not directory.is_dir():
            return "The supplied path is not a directory."

        scan = scan_project_dir(directory)
        lines = [f"Scan results for {directory}:"]
        lines.append(f"- Project file: {scan['project'] or '(none)'}")
        lines.append(f"- PCB file: {scan['pcb'] or '(none)'}")
        lines.append(f"- Schematic file: {scan['schematic'] or '(none)'}")
        return "\n".join(lines)

    @mcp.tool()
    def kicad_create_new_project(path: str, name: str) -> str:
        """Create a new minimal KiCad project structure and activate it."""
        payload = CreateProjectInput(path=path, name=name)
        project_dir = Path(payload.path).expanduser().resolve() / payload.name
        project_dir.mkdir(parents=True, exist_ok=True)

        project_file, pcb_file, sch_file = _new_project_files(project_dir, payload.name)
        project_file.write_text(
            json.dumps(
                {
                    "board": {"design_settings": {}},
                    "meta": {"filename": project_file.name, "version": 1},
                    "schematic": {"legacy_lib_dir": "", "page_layout_descr_file": ""},
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        pcb_file.write_text(
            '(kicad_pcb (version 20250316) (generator "kicad-mcp-pro"))\n',
            encoding="utf-8",
        )
        sch_file.write_text(
            (
                "(kicad_sch\n"
                "\t(version 20250316)\n"
                '\t(generator "kicad-mcp-pro")\n'
                f'\t(uuid "{uuid.uuid4()}")\n'
                '\t(paper "A4")\n'
                "\t(lib_symbols)\n"
                '\t(sheet_instances (path "/" (page "1")))\n'
                "\t(embedded_fonts no)\n"
                ")\n"
            ),
            encoding="utf-8",
        )

        cfg = get_config()
        cfg.apply_project(
            project_dir,
            project_file=project_file,
            pcb_file=pcb_file,
            sch_file=sch_file,
            output_dir=project_dir / "output",
        )
        reset_connection()
        return "\n".join(
            [
                f"Created project '{payload.name}' at {project_dir}.",
                f"- Project file: {project_file}",
                f"- PCB file: {pcb_file}",
                f"- Schematic file: {sch_file}",
            ]
        )

    @mcp.tool()
    def kicad_get_version() -> str:
        """Get KiCad version information and current connection status."""
        cfg = get_config()
        lines = [f"# KiCad MCP Pro Server v{__version__}", f"CLI path: {cfg.kicad_cli}"]

        cli_version = find_kicad_version(cfg.kicad_cli)
        lines.append(f"CLI version: {cli_version or 'unavailable'}")

        try:
            from kipy.proto.common.types.base_types_pb2 import DocumentType

            kicad = get_kicad()
            lines.append(f"IPC version: {kicad.get_version()}")
            pcb_docs = kicad.get_open_documents(DocumentType.DOCTYPE_PCB)
            sch_docs = kicad.get_open_documents(DocumentType.DOCTYPE_SCHEMATIC)
            lines.append(f"Open PCB documents: {len(pcb_docs)}")
            lines.append(f"Open schematic documents: {len(sch_docs)}")
        except KiCadConnectionError as exc:
            lines.append(f"IPC connection: unavailable ({exc})")
        except Exception:
            lines.append("IPC connection: unavailable")

        lines.append("")
        lines.append("Use `kicad_set_project()` to configure an active project.")
        return "\n".join(lines)

    @mcp.tool()
    def kicad_help() -> str:
        """Show a concise startup guide and all tool categories."""
        lines = [
            "# KiCad MCP Pro Quick Start",
            "",
            "1. Call `kicad_get_version()` to verify the runtime.",
            "2. Call `kicad_set_project()` or `kicad_create_new_project()`.",
            "3. Inspect `kicad://project/info` and `kicad://board/summary`.",
            "4. Call `kicad_list_tool_categories()` to discover the right tool family.",
            "",
            "Available categories:",
        ]
        for category, info in TOOL_CATEGORIES.items():
            lines.append(f"- `{category}`: {info['description']}")
        return "\n".join(lines)
