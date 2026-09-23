"""KiCad CLI symbol tools.

Wraps ``kicad-cli sym`` subcommands for headless symbol export
and file-format upgrade.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from .export_support import _ensure_output_dir, _run_cli, _run_cli_variants
from .metadata import headless_compatible


def register(mcp: FastMCP) -> None:
    """Register symbol management tools."""

    @headless_compatible
    def sym_export(output_path: str = "", format: str = "svg") -> str:
        """Export a KiCad symbol to an interchange format.

        Supported formats depend on the installed ``kicad-cli`` version.
        Common values: ``svg``, ``pdf``.

        Parameters
        ----------
        output_path : str
            Optional output file name (relative to the export directory).
            Defaults to ``<board_name>.<format>``.
        format : str
            Target export format.  Defaults to ``svg``.
        """
        cfg = get_config()
        project_file = cfg.sch_file or cfg.pcb_file
        if project_file is None:
            return "No project file configured. Call kicad_set_project() first."

        out_dir = _ensure_output_dir("symbols")
        out_name = Path(output_path.strip() or f"{project_file.stem}.{format}").name
        out_file = out_dir / out_name

        code, _, stderr = _run_cli_variants(
            [
                ["sym", "export", format, "--output", str(out_file), str(project_file)],
                [
                    "sym",
                    "export",
                    format,
                    "--input",
                    str(project_file),
                    "--output",
                    str(out_file),
                ],
            ]
        )
        if code != 0:
            return f"Symbol export failed: {stderr or 'unknown error'}"
        return f"Symbol exported to {out_file}"

    @headless_compatible
    def sym_export_svg(
        input_file: str,
        output_dir: str = "",
        symbol: str = "",
        theme: str = "",
        black_and_white: bool = False,
        include_hidden_pins: bool = False,
        include_hidden_fields: bool = False,
    ) -> str:
        """Export a symbol or symbol library to SVG format.

        Parameters
        ----------
        input_file : str
            Path to the symbol library file (.kicad_sym).
        output_dir : str
            Optional output directory.
        symbol : str
            Specific symbol name to export within the library.
        theme : str
            Optional color theme name.
        black_and_white : bool
            Export in black and white only.
        include_hidden_pins : bool
            Include hidden pins in the SVG export.
        include_hidden_fields : bool
            Include hidden fields in the SVG export.
        """
        cfg = get_config()
        if not input_file:
            return "Error: input_file parameter is required."

        try:
            from ..path_safety import resolve_under

            if cfg.project_dir is not None:
                in_path = resolve_under(cfg.project_dir, input_file)
            else:
                in_path = Path(input_file).expanduser().resolve()
        except Exception as exc:
            raise ValueError(f"Unsafe input file path: {exc}") from exc

        if not in_path.exists():
            return f"Input symbol library file not found: {input_file}"

        out_dir = _ensure_output_dir("symbols")
        if output_dir:
            try:
                if cfg.project_dir is not None:
                    out_dir = resolve_under(cfg.project_dir, output_dir)
                else:
                    out_dir = Path(output_dir).expanduser().resolve()
            except Exception as exc:
                raise ValueError(f"Unsafe output directory: {exc}") from exc

        cmd = ["sym", "export", "svg"]
        cmd.extend(["--output", str(out_dir)])
        if symbol:
            cmd.extend(["--symbol", symbol])
        if theme:
            cmd.extend(["--theme", theme])
        if black_and_white:
            cmd.append("--black-and-white")
        if include_hidden_pins:
            cmd.append("--include-hidden-pins")
        if include_hidden_fields:
            cmd.append("--include-hidden-fields")
        cmd.append(str(in_path))

        code, stdout, stderr = _run_cli(*cmd)
        if code != 0:
            return f"Symbol SVG export failed: {stderr or stdout or 'unknown error'}"
        return f"Symbol SVG exported successfully to {out_dir}"

    @headless_compatible
    def sym_upgrade(
        input_file: str = "",
        output_file: str = "",
        force: bool = False,
        dry_run: bool = True,
    ) -> str:
        """Upgrade a KiCad symbol library file to the current file format.

        Parameters
        ----------
        input_file : str
            Path to the symbol library file (``.kicad_sym``) to upgrade.
            If omitted, the active schematic's symbol library is used.
        output_file : str
            Optional output path.  Defaults to overwriting the input.
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
            raise ValueError(f"Unsafe input file path: {exc}") from exc

        out_path = output_file.strip() if output_file else ""
        if out_path:
            try:
                if cfg.project_dir is not None:
                    from ..path_safety import resolve_under

                    out_path = str(resolve_under(cfg.project_dir, out_path))
                else:
                    out_path = str(Path(out_path).expanduser().resolve())
            except Exception as exc:
                raise ValueError(f"Unsafe output path: {exc}") from exc
        else:
            out_dir = _ensure_output_dir("upgraded")
            out_path = str(out_dir / f"upgraded_{in_path.name}")

        if dry_run:
            return (
                f"Dry run: Would upgrade symbol library '{in_path}' "
                f"and save to '{out_path}' (force={force})."
            )

        cmd = ["sym", "upgrade"]
        if force:
            cmd.append("--force")
        cmd.extend(["--output", out_path])
        cmd.append(str(in_path))

        code, stdout, stderr = _run_cli(*cmd)
        if code != 0:
            return f"Symbol upgrade failed: {stderr or stdout or 'unknown error'}"
        return f"Symbol library upgraded and saved to {out_path}"

    mcp.tool()(sym_export)
    mcp.tool()(sym_export_svg)
    mcp.tool()(sym_upgrade)
