"""KiCad CLI footprint tools.

Wraps ``kicad-cli fp`` subcommands for headless footprint inspection,
export, and format upgrade.
"""

from __future__ import annotations

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from .export_support import _ensure_output_dir, _run_cli, _run_cli_variants
from .metadata import headless_compatible


def register(mcp: FastMCP) -> None:
    """Register footprint management tools."""

    @headless_compatible
    def fp_export(
        output_path: str = "",
        format: str = "step",
    ) -> str:
        """Export a KiCad footprint to an interchange format.

        Supported formats depend on the installed ``kicad-cli`` version.
        Common values: ``step``, ``svg``, ``dxf``, ``wrl`` (VRML).

        Parameters
        ----------
        output_path : str
            Optional output file name (relative to the export directory).
            Defaults to ``<footprint_name>.<format>``.
        format : str
            Target export format.  Defaults to ``step``.
        """
        cfg = get_config()
        if cfg.pcb_file is None:
            return "No PCB file configured. Call kicad_set_project() first."

        out_dir = _ensure_output_dir("footprints")
        board_stem = cfg.pcb_file.stem
        out_name = Path(output_path.strip() or f"{board_stem}.{format}").name
        out_file = out_dir / out_name

        code, _, stderr = _run_cli_variants(
            [
                [
                    "fp",
                    "export",
                    format,
                    "--output",
                    str(out_file),
                    str(cfg.pcb_file),
                ],
                [
                    "fp",
                    "export",
                    format,
                    "--input",
                    str(cfg.pcb_file),
                    "--output",
                    str(out_file),
                ],
            ]
        )
        if code != 0:
            return f"Footprint export failed: {stderr or 'unknown error'}"
        return f"Footprint exported to {out_file}"

    @headless_compatible
    def fp_export_svg(
        input_path: str,
        output_dir: str = "",
        footprint: str = "",
        layers: list[str] | None = None,
        theme: str = "",
        black_and_white: bool = False,
    ) -> str:
        """Export a footprint or footprint library to SVG format.

        Parameters
        ----------
        input_path : str
            Path to the footprint file (.kicad_mod) or library directory (.pretty).
        output_dir : str
            Optional output directory.
        footprint : str
            Specific footprint name to export within the library.
        layers : list[str]
            Optional list of layer names to include.
        theme : str
            Optional color theme name.
        black_and_white : bool
            Export in black and white only.
        """
        cfg = get_config()
        if not input_path:
            return "Error: input_path parameter is required."

        try:
            from ..path_safety import resolve_under

            if cfg.project_dir is not None:
                in_path = resolve_under(cfg.project_dir, input_path)
            else:
                in_path = Path(input_path).expanduser().resolve()
        except Exception as exc:
            raise ValueError(f"Unsafe input path: {exc}") from exc

        if not in_path.exists():
            return f"Input footprint file or directory not found: {input_path}"

        out_dir = _ensure_output_dir("footprints")
        if output_dir:
            try:
                if cfg.project_dir is not None:
                    out_dir = resolve_under(cfg.project_dir, output_dir)
                else:
                    out_dir = Path(output_dir).expanduser().resolve()
            except Exception as exc:
                raise ValueError(f"Unsafe output directory: {exc}") from exc

        cmd = ["fp", "export", "svg"]
        cmd.extend(["--output", str(out_dir)])
        if footprint:
            cmd.extend(["--footprint", footprint])
        if layers:
            cmd.extend(["--layers", ",".join(layers)])
        if theme:
            cmd.extend(["--theme", theme])
        if black_and_white:
            cmd.append("--black-and-white")
        cmd.append(str(in_path))

        code, stdout, stderr = _run_cli(*cmd)
        if code != 0:
            return f"Footprint SVG export failed: {stderr or stdout or 'unknown error'}"
        return f"Footprint SVG exported successfully to {out_dir}"

    @headless_compatible
    def fp_upgrade(
        input_file: str = "",
        output_file: str = "",
        input_path: str = "",
        force: bool = False,
        dry_run: bool = True,
    ) -> str:
        """Upgrade a KiCad footprint library file to the current file format.

        Parameters
        ----------
        input_file : str
            Legacy input file parameter (for backward compatibility).
        output_file : str
            Legacy output file parameter (for backward compatibility).
        input_path : str
            Path to the footprint library to upgrade. If omitted, input_file is used.
        force : bool
            Force resaving regardless of version.
        dry_run : bool
            Only report commands and files that would be affected.
        """
        cfg = get_config()
        raw_in = input_path or input_file
        if not raw_in and cfg.pcb_file is None:
            return (
                "No input file provided and no PCB configured. "
                "Provide an input_path or call kicad_set_project() first."
            )

        in_file = raw_in or str(cfg.pcb_file)

        try:
            from ..path_safety import resolve_under

            if cfg.project_dir is not None:
                in_path_obj = resolve_under(cfg.project_dir, in_file)
            else:
                in_path_obj = Path(in_file).expanduser().resolve()
        except Exception as exc:
            raise ValueError(f"Unsafe input path: {exc}") from exc

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
            out_path = str(out_dir / in_path_obj.name)

        if dry_run:
            return (
                f"Dry run: Would upgrade footprint library '{in_path_obj}' "
                f"and save to '{out_path}' (force={force})."
            )

        cmd = ["fp", "upgrade"]
        if force:
            cmd.append("--force")
        cmd.extend(["--output", out_path])
        cmd.append(str(in_path_obj))

        code, stdout, stderr = _run_cli(*cmd)
        if code != 0:
            return f"Footprint upgrade failed: {stderr or stdout or 'unknown error'}"
        return f"Footprint upgraded and saved to {out_path}"

    @headless_compatible
    def fp_get_info() -> str:
        """Return metadata about the active board's footprint library.

        Runs ``kicad-cli fp get`` to inspect footprint properties such as
        3D model references, layer assignment, and pad count.
        """
        cfg = get_config()
        if cfg.pcb_file is None:
            return "No PCB file configured. Call kicad_set_project() first."

        code, stdout, stderr = _run_cli_variants(
            [
                ["fp", "get", str(cfg.pcb_file)],
                ["fp", "get", "--input", str(cfg.pcb_file)],
            ]
        )
        if code != 0:
            # The command may not be available on older KiCad CLIs.
            return f"Footprint info unavailable: {stderr or stdout or 'unknown error'}"

        return stdout or "Footprint info retrieved."

    mcp.tool()(fp_export)
    mcp.tool()(fp_export_svg)
    mcp.tool()(fp_upgrade)
    mcp.tool()(fp_get_info)
