"""Thin FastMCP adapter for manufacturing board-import tools."""

# pyright: reportUnusedFunction=false

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mcp.server.mcpserver import MCPServer as FastMCP

from ..config import get_config
from ..discovery import get_cli_capabilities
from ..manufacturing.imports import ManufacturingImportService
from ..path_safety import resolve_under
from .metadata import headless_compatible


@dataclass(frozen=True)
class ManufacturingImportDependencies:
    service: ManufacturingImportService


def _resolve_path(path_text: str) -> Path:
    cfg = get_config()
    if cfg.project_dir is not None:
        return resolve_under(cfg.project_dir, path_text)
    return Path(path_text).expanduser().resolve()


def _run_cli_variants(variants: list[list[str]]) -> tuple[int, str, str]:
    from . import export_support

    return export_support._run_cli_variants(variants)


def _default_dependencies() -> ManufacturingImportDependencies:
    return ManufacturingImportDependencies(
        service=ManufacturingImportService(
            resolve_path=_resolve_path,
            run_cli_variants=_run_cli_variants,
            get_cli_capabilities=lambda: get_cli_capabilities(get_config().kicad_cli),
        )
    )


def register(
    mcp: FastMCP,
    dependencies: ManufacturingImportDependencies | None = None,
) -> None:
    """Register manufacturing board-import tools."""
    service = (dependencies or _default_dependencies()).service

    # `format` is part of the committed public MCP schema; renaming it is breaking.
    # pylint: disable=redefined-builtin
    @mcp.tool()
    @headless_compatible
    def mfg_check_import_support(format: str) -> str:
        """Report whether the detected KiCad CLI advertises a given board-import format."""
        return service.check_import_support(format)

    # `format` is part of the committed public MCP schema; renaming it is breaking.
    @mcp.tool()
    @headless_compatible
    def pcb_import_board(
        input_file: str,
        output_file: str = "",
        format: str = "auto",
        report_format: str = "none",
        report_file: str = "",
    ) -> str:
        """Import a non-KiCad PCB file to KiCad format.

        Parameters
        ----------
        input_file : str
            Path to the non-KiCad board file.
        output_file : str
            Optional path for the imported KiCad PCB file.
        format : str
            Input format: auto, pads, altium, eagle, cadstar, fabmaster, pcad, solidworks.
        report_format : str
            Import report format: none, json, text.
        report_file : str
            Optional file path for the import report.
        """
        return service.import_board(
            input_file=input_file,
            output_file=output_file,
            import_format=format,
            report_format=report_format,
            report_file=report_file,
        )

    # pylint: enable=redefined-builtin

    @mcp.tool()
    @headless_compatible
    def mfg_import_allegro(allegro_brd_path: str, output_dir: str = "") -> str:
        """Import an Allegro board into a KiCad project directory."""
        return service.import_allegro(allegro_brd_path, output_dir)

    @mcp.tool()
    @headless_compatible
    def mfg_import_pads(pads_pcb_path: str, output_dir: str = "") -> str:
        """Import a PADS PCB into a KiCad project directory."""
        return service.import_pads(pads_pcb_path, output_dir)

    @mcp.tool()
    @headless_compatible
    def mfg_import_geda(geda_pcb_path: str, output_dir: str = "") -> str:
        """Import a gEDA PCB into a KiCad project directory."""
        return service.import_geda(geda_pcb_path, output_dir)

    @mcp.tool()
    @headless_compatible
    def mfg_import_specctra(specctra_ses_path: str, output_dir: str = "") -> str:
        """Import a Specctra DSN/SES file into a KiCad project directory."""
        return service.import_specctra(specctra_ses_path, output_dir)
