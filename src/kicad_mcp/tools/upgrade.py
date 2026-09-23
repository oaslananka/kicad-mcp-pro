"""KiCad CLI file-format upgrade tools.

Wraps ``kicad-cli sch upgrade`` and ``kicad-cli pcb upgrade`` for
converting legacy project files to the current KiCad file format.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from .export_support import _run_cli
from .metadata import headless_compatible


def register(mcp: FastMCP) -> None:
    """Register file-format upgrade tools."""

    @headless_compatible
    def sch_upgrade(
        input_file: str = "",
        output_file: str = "",
        force: bool = False,
        dry_run: bool = True,
    ) -> str:
        """Upgrade a schematic file to the current KiCad file format.

        Parameters
        ----------
        input_file : str
            Path to the schematic file (``.kicad_sch`` or legacy ``.sch``)
            to upgrade.  If omitted, the active project's schematic is used.
        output_file : str
            Optional output path.  Defaults to the input path (in-place).
        force : bool
            Force resaving regardless of version.
        dry_run : bool
            Only report commands and files that would be affected.
        """
        cfg = get_config()
        if not input_file:
            if cfg.sch_file is None:
                return (
                    "No input file provided and no schematic configured. "
                    "Provide an input_file path or call kicad_set_project() first."
                )
            in_file = str(cfg.sch_file)
        else:
            in_file = input_file

        try:
            from ..path_safety import resolve_under

            if cfg.project_dir is not None:
                in_path = resolve_under(cfg.project_dir, in_file)
            else:
                in_path = Path(in_file).expanduser().resolve()
        except Exception as exc:
            raise ValueError(f"Unsafe input path: {exc}") from exc

        out_raw = output_file.strip() if output_file else ""
        if out_raw:
            try:
                from ..path_safety import resolve_under

                if cfg.project_dir is not None:
                    out_path = str(resolve_under(cfg.project_dir, out_raw))
                else:
                    out_path = str(Path(out_raw).expanduser().resolve())
            except Exception as exc:
                raise ValueError(f"Unsafe output path: {exc}") from exc
        else:
            out_path = str(in_path)

        if dry_run:
            return (
                f"Dry run: Would upgrade schematic file '{in_path}' "
                f"and save to '{out_path}' (force={force})."
            )

        cmd = ["sch", "upgrade"]
        if force:
            cmd.append("--force")
        cmd.extend(["--output", out_path])
        cmd.append(str(in_path))

        code, stdout, stderr = _run_cli(*cmd)
        if code != 0:
            return f"Schematic upgrade failed: {stderr or stdout or 'unknown error'}"
        return f"Schematic upgraded and saved to {out_path}"

    @headless_compatible
    def pcb_upgrade(
        input_file: str = "",
        output_file: str = "",
        force: bool = False,
        dry_run: bool = True,
    ) -> str:
        """Upgrade a PCB file to the current KiCad file format.

        Parameters
        ----------
        input_file : str
            Path to the PCB file (``.kicad_pcb`` or legacy ``.brd``)
            to upgrade.  If omitted, the active project's PCB is used.
        output_file : str
            Optional output path.  Defaults to the input path (in-place).
        force : bool
            Force resaving regardless of version.
        dry_run : bool
            Only report commands and files that would be affected.
        """
        cfg = get_config()
        if not input_file:
            if cfg.pcb_file is None:
                return (
                    "No input file provided and no PCB configured. "
                    "Provide an input_file path or call kicad_set_project() first."
                )
            in_file = str(cfg.pcb_file)
        else:
            in_file = input_file

        try:
            from ..path_safety import resolve_under

            if cfg.project_dir is not None:
                in_path = resolve_under(cfg.project_dir, in_file)
            else:
                in_path = Path(in_file).expanduser().resolve()
        except Exception as exc:
            raise ValueError(f"Unsafe input path: {exc}") from exc

        out_raw = output_file.strip() if output_file else ""
        if out_raw:
            try:
                from ..path_safety import resolve_under

                if cfg.project_dir is not None:
                    out_path = str(resolve_under(cfg.project_dir, out_raw))
                else:
                    out_path = str(Path(out_raw).expanduser().resolve())
            except Exception as exc:
                raise ValueError(f"Unsafe output path: {exc}") from exc
        else:
            out_path = str(in_path)

        if dry_run:
            return (
                f"Dry run: Would upgrade PCB file '{in_path}' "
                f"and save to '{out_path}' (force={force})."
            )

        cmd = ["pcb", "upgrade"]
        if force:
            cmd.append("--force")
        cmd.extend(["--output", out_path])
        cmd.append(str(in_path))

        code, stdout, stderr = _run_cli(*cmd)
        if code != 0:
            return f"PCB upgrade failed: {stderr or stdout or 'unknown error'}"
        return f"PCB upgraded and saved to {out_path}"

    mcp.tool()(sch_upgrade)
    mcp.tool()(pcb_upgrade)
