"""Cross-platform export tools backed by kicad-cli."""

from __future__ import annotations

import subprocess
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from ..config import get_config
from ..discovery import get_cli_capabilities
from ..models.export import (
    ExportBOMInput,
    ExportGerberInput,
    ExportNetlistInput,
    ExportPdfInput,
    ExportRenderInput,
)

DEFAULT_PCB_PDF_LAYERS = ["F.Cu", "Edge.Cuts"]


def _sanitize_cli_text(text: str) -> str:
    cfg = get_config()
    sanitized = text.replace(str(cfg.kicad_cli), "kicad-cli")
    if cfg.project_dir is not None:
        sanitized = sanitized.replace(str(cfg.project_dir), "<project>")
    return sanitized.strip()


def _run_cli(*args: str, timeout: float | None = None) -> tuple[int, str, str]:
    """Run kicad-cli with the supplied arguments."""
    cfg = get_config()
    if not cfg.kicad_cli.exists():
        raise FileNotFoundError(
            "kicad-cli is not available. Set KICAD_MCP_KICAD_CLI to a valid executable."
        )

    result = subprocess.run(
        [str(cfg.kicad_cli), *args],
        capture_output=True,
        text=True,
        timeout=timeout or cfg.cli_timeout,
        check=False,
    )
    return (
        result.returncode,
        _sanitize_cli_text(result.stdout),
        _sanitize_cli_text(result.stderr),
    )


def _run_cli_variants(variants: list[list[str]]) -> tuple[int, str, str]:
    """Try multiple command variants and return the first success."""
    last_result = (1, "", "No CLI variants were attempted.")
    for variant in variants:
        try:
            result = _run_cli(*variant)
        except FileNotFoundError:
            raise
        except subprocess.TimeoutExpired:
            result = (124, "", "The kicad-cli command timed out.")
        if result[0] == 0:
            return result
        last_result = result
    return last_result


def _get_pcb_file() -> Path:
    cfg = get_config()
    if cfg.pcb_file is None or not cfg.pcb_file.exists():
        raise ValueError(
            "No PCB file is configured. Call kicad_set_project() or set KICAD_MCP_PCB_FILE."
        )
    return cfg.pcb_file


def _get_sch_file() -> Path:
    cfg = get_config()
    if cfg.sch_file is None or not cfg.sch_file.exists():
        raise ValueError(
            "No schematic file is configured. Call kicad_set_project() or set KICAD_MCP_SCH_FILE."
        )
    return cfg.sch_file


def _ensure_output_dir(subdir: str | None = None) -> Path:
    return get_config().ensure_output_dir(subdir)


def _format_file_list(files: list[Path], heading: str) -> str:
    if not files:
        return f"{heading}\nNo files were produced."
    lines = [heading]
    lines.extend(f"- {file.name}" for file in files[:25])
    if len(files) > 25:
        lines.append(f"... and {len(files) - 25} more files")
    return "\n".join(lines)


def _read_preview(path: Path) -> str:
    cfg = get_config()
    content = path.read_text(encoding="utf-8", errors="ignore")
    if len(content) > cfg.max_text_response_chars:
        return f"{content[: cfg.max_text_response_chars]}\n... [truncated]"
    return content


def register(mcp: FastMCP) -> None:
    """Register export tools."""

    @mcp.tool()
    def export_gerber(output_subdir: str = "gerber", layers: list[str] | None = None) -> str:
        """Export Gerber manufacturing files."""
        payload = ExportGerberInput(output_subdir=output_subdir, layers=layers or [])
        pcb_file = _get_pcb_file()
        out_dir = _ensure_output_dir(payload.output_subdir)
        caps = get_cli_capabilities(get_config().kicad_cli)

        layer_args = []
        if payload.layers:
            layer_args = ["--layers", ",".join(payload.layers)]

        code, _, stderr = _run_cli_variants(
            [
                [
                    "pcb",
                    "export",
                    caps.gerber_command,
                    "--output",
                    str(out_dir),
                    *layer_args,
                    str(pcb_file),
                ],
                [
                    "pcb",
                    "export",
                    caps.gerber_command,
                    "--input",
                    str(pcb_file),
                    "--output",
                    str(out_dir),
                    *layer_args,
                ],
            ]
        )
        if code != 0:
            return f"Gerber export failed: {stderr or 'unknown error'}"

        files = sorted(out_dir.glob("*.gbr")) + sorted(out_dir.glob("*.g*"))
        return _format_file_list(files, f"Gerber export completed in {out_dir}:")

    @mcp.tool()
    def export_drill(output_subdir: str = "gerber") -> str:
        """Export drill files."""
        pcb_file = _get_pcb_file()
        out_dir = _ensure_output_dir(output_subdir)
        caps = get_cli_capabilities(get_config().kicad_cli)
        code, _, stderr = _run_cli_variants(
            [
                ["pcb", "export", caps.drill_command, "--output", str(out_dir), str(pcb_file)],
                [
                    "pcb",
                    "export",
                    caps.drill_command,
                    "--input",
                    str(pcb_file),
                    "--output",
                    str(out_dir),
                ],
            ]
        )
        if code != 0:
            return f"Drill export failed: {stderr or 'unknown error'}"
        files = sorted(out_dir.glob("*.drl")) + sorted(out_dir.glob("*.xnc"))
        return _format_file_list(files, f"Drill export completed in {out_dir}:")

    @mcp.tool()
    def export_bom(format: str = "csv") -> str:
        """Export a bill of materials."""
        payload = ExportBOMInput(format=format)
        sch_file = _get_sch_file()
        out_dir = _ensure_output_dir()
        suffix = "csv" if payload.format == "csv" else "xml"
        out_file = out_dir / f"bom.{suffix}"
        code, _, stderr = _run_cli_variants(
            [
                [
                    "sch",
                    "export",
                    "bom",
                    "--output",
                    str(out_file),
                    "--format-preset",
                    "CSV",
                    str(sch_file),
                ],
                [
                    "sch",
                    "export",
                    "bom",
                    "--input",
                    str(sch_file),
                    "--output",
                    str(out_file),
                    "--format-preset",
                    "CSV",
                ],
                ["sch", "export", "python-bom", "--output", str(out_file), str(sch_file)],
            ]
        )
        if code != 0 and not out_file.exists():
            return f"BOM export failed: {stderr or 'unknown error'}"
        return f"BOM exported to {out_file}\n\n{_read_preview(out_file)}"

    @mcp.tool()
    def export_netlist(format: str = "kicad") -> str:
        """Export a KiCad schematic netlist."""
        payload = ExportNetlistInput(format=format)
        sch_file = _get_sch_file()
        out_dir = _ensure_output_dir()
        extension_map = {"kicad": "net", "spice": "cir", "cadstar": "frp", "orcadpcb2": "net"}
        cli_format_map = {
            "kicad": "kicadsexpr",
            "spice": "spice",
            "cadstar": "cadstar",
            "orcadpcb2": "orcadpcb2",
        }
        out_file = out_dir / f"netlist.{extension_map[payload.format]}"
        code, _, stderr = _run_cli_variants(
            [
                [
                    "sch",
                    "export",
                    "netlist",
                    "--format",
                    cli_format_map[payload.format],
                    "--output",
                    str(out_file),
                    str(sch_file),
                ],
            ]
        )
        if code != 0:
            return f"Netlist export failed: {stderr or 'unknown error'}"
        return f"Netlist exported to {out_file}"

    @mcp.tool()
    def export_spice_netlist() -> str:
        """Export a SPICE netlist."""
        return str(export_netlist("spice"))

    @mcp.tool()
    def export_pcb_pdf(layers: list[str] | None = None) -> str:
        """Export the PCB to PDF."""
        payload = ExportPdfInput(layers=layers or [])
        pcb_file = _get_pcb_file()
        out_dir = _ensure_output_dir()
        out_file = out_dir / "board.pdf"
        layers_arg = ",".join(payload.layers or DEFAULT_PCB_PDF_LAYERS)
        code, _, stderr = _run_cli_variants(
            [
                [
                    "pcb",
                    "export",
                    "pdf",
                    "--output",
                    str(out_file),
                    "--layers",
                    layers_arg,
                    str(pcb_file),
                ],
                [
                    "pcb",
                    "export",
                    "pdf",
                    "--input",
                    str(pcb_file),
                    "--output",
                    str(out_file),
                    "--layers",
                    layers_arg,
                ],
            ]
        )
        if code != 0:
            return f"PCB PDF export failed: {stderr or 'unknown error'}"
        return f"PCB PDF exported to {out_file}"

    @mcp.tool()
    def export_sch_pdf() -> str:
        """Export the schematic to PDF."""
        sch_file = _get_sch_file()
        out_dir = _ensure_output_dir()
        out_file = out_dir / "schematic.pdf"
        code, _, stderr = _run_cli_variants(
            [
                ["sch", "export", "pdf", "--output", str(out_file), str(sch_file)],
                ["sch", "export", "pdf", "--input", str(sch_file), "--output", str(out_file)],
            ]
        )
        if code != 0:
            return f"Schematic PDF export failed: {stderr or 'unknown error'}"
        return f"Schematic PDF exported to {out_file}"

    @mcp.tool()
    def export_3d_step() -> str:
        """Export a STEP model for the active board."""
        return str(export_step(""))

    @mcp.tool()
    def export_step(output_path: str = "") -> str:
        """Alias for STEP export with an optional explicit output path."""
        pcb_file = _get_pcb_file()
        caps = get_cli_capabilities(get_config().kicad_cli)
        if not caps.supports_step:
            return "STEP export is not supported by the detected KiCad CLI."

        out_file = (
            Path(output_path).expanduser().resolve()
            if output_path
            else _ensure_output_dir("3d") / "board.step"
        )
        code, _, stderr = _run_cli_variants(
            [
                ["pcb", "export", "step", "--output", str(out_file), str(pcb_file)],
                ["pcb", "export", "step", "--input", str(pcb_file), "--output", str(out_file)],
            ]
        )
        if code != 0:
            return f"STEP export failed: {stderr or 'unknown error'}"
        return f"STEP model exported to {out_file}"

    @mcp.tool()
    def export_3d_render(
        output_file: str = "render.png",
        side: str = "top",
        zoom: float = 1.0,
    ) -> str:
        """Render the board to a PNG image."""
        payload = ExportRenderInput(output_file=output_file, side=side, zoom=zoom)
        pcb_file = _get_pcb_file()
        caps = get_cli_capabilities(get_config().kicad_cli)
        if not caps.supports_render:
            return "3D rendering is not supported by the detected KiCad CLI."

        out_file = _ensure_output_dir("3d") / payload.output_file
        code, _, stderr = _run_cli_variants(
            [
                [
                    "pcb",
                    "render",
                    "--side",
                    payload.side,
                    "--zoom",
                    str(payload.zoom),
                    "--output",
                    str(out_file),
                    str(pcb_file),
                ],
                [
                    "pcb",
                    "render",
                    "--input",
                    str(pcb_file),
                    "--side",
                    payload.side,
                    "--zoom",
                    str(payload.zoom),
                    "--output",
                    str(out_file),
                ],
            ]
        )
        if code != 0:
            return f"3D render failed: {stderr or 'unknown error'}"
        return f"Rendered board image exported to {out_file}"

    @mcp.tool()
    def export_pick_and_place(format: str = "csv") -> str:
        """Export assembly position data."""
        pcb_file = _get_pcb_file()
        out_dir = _ensure_output_dir("assembly")
        out_file = out_dir / f"pick_and_place.{format}"
        caps = get_cli_capabilities(get_config().kicad_cli)
        code, _, stderr = _run_cli_variants(
            [
                [
                    "pcb",
                    "export",
                    caps.position_command,
                    "--format",
                    format,
                    "--output",
                    str(out_file),
                    str(pcb_file),
                ],
                [
                    "pcb",
                    "export",
                    caps.position_command,
                    "--input",
                    str(pcb_file),
                    "--format",
                    format,
                    "--output",
                    str(out_file),
                ],
                ["pcb", "export", "pos", "--output", str(out_file), str(pcb_file)],
            ]
        )
        if code != 0:
            return f"Pick and place export failed: {stderr or 'unknown error'}"
        return f"Pick and place data exported to {out_file}"

    @mcp.tool()
    def export_ipc2581() -> str:
        """Export IPC-2581 manufacturing data."""
        pcb_file = _get_pcb_file()
        caps = get_cli_capabilities(get_config().kicad_cli)
        if not caps.supports_ipc2581:
            return "IPC-2581 export is not supported by the detected KiCad CLI."

        out_file = _ensure_output_dir("manufacturing") / "board.xml"
        code, _, stderr = _run_cli_variants(
            [
                ["pcb", "export", "ipc2581", "--output", str(out_file), str(pcb_file)],
                ["pcb", "export", "ipc2581", "--input", str(pcb_file), "--output", str(out_file)],
            ]
        )
        if code != 0:
            return f"IPC-2581 export failed: {stderr or 'unknown error'}"
        return f"IPC-2581 exported to {out_file}"

    @mcp.tool()
    def export_svg(layer: str = "F.Cu") -> str:
        """Export a board layer to SVG when supported."""
        pcb_file = _get_pcb_file()
        caps = get_cli_capabilities(get_config().kicad_cli)
        if not caps.supports_svg:
            return "SVG export is not supported by the detected KiCad CLI."

        out_dir = _ensure_output_dir("svg")
        code, _, stderr = _run_cli_variants(
            [
                [
                    "pcb",
                    "export",
                    "svg",
                    "--mode-multi",
                    "--layers",
                    layer,
                    "--output",
                    str(out_dir),
                    str(pcb_file),
                ],
            ]
        )
        if code != 0:
            return f"SVG export failed: {stderr or 'unknown error'}"
        files = sorted(out_dir.glob("*.svg"))
        return _format_file_list(files, f"SVG export completed in {out_dir}:")

    @mcp.tool()
    def export_dxf(layer: str = "Edge.Cuts") -> str:
        """Export a board layer to DXF when supported."""
        pcb_file = _get_pcb_file()
        caps = get_cli_capabilities(get_config().kicad_cli)
        if not caps.supports_dxf:
            return "DXF export is not supported by the detected KiCad CLI."

        out_dir = _ensure_output_dir("dxf")
        code, _, stderr = _run_cli_variants(
            [
                [
                    "pcb",
                    "export",
                    "dxf",
                    "--layers",
                    layer,
                    "--output",
                    str(out_dir),
                    str(pcb_file),
                ],
                [
                    "pcb",
                    "export",
                    "dxf",
                    "--input",
                    str(pcb_file),
                    "--layers",
                    layer,
                    "--output",
                    str(out_dir),
                ],
            ]
        )
        if code != 0:
            return f"DXF export failed: {stderr or 'unknown error'}"
        files = sorted(out_dir.glob("*.dxf"))
        return _format_file_list(files, f"DXF export completed in {out_dir}:")

    @mcp.tool()
    def get_board_stats() -> str:
        """Export board statistics and return a readable preview."""
        pcb_file = _get_pcb_file()
        out_file = _ensure_output_dir() / "board_stats.txt"
        code, stdout, stderr = _run_cli_variants(
            [
                ["pcb", "export", "stats", "--output", str(out_file), str(pcb_file)],
                ["pcb", "export", "stats", "--input", str(pcb_file), "--output", str(out_file)],
            ]
        )
        if out_file.exists():
            return _read_preview(out_file)
        if code != 0:
            return f"Board stats export failed: {stderr or 'unknown error'}"
        return stdout or "Board statistics were generated without a text report."

    @mcp.tool()
    def export_manufacturing_package() -> str:
        """Generate the standard set of manufacturing exports."""
        results = [
            export_gerber(),
            export_drill(),
            export_bom(),
            export_pick_and_place(),
        ]
        ipc_result = export_ipc2581()
        if not ipc_result.startswith("IPC-2581 export is not supported"):
            results.append(ipc_result)
        return "\n\n".join(results)
