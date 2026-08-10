"""FastMCP-free PCB SVG/DXF export behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

type GetPcbFile = Callable[[], Path]
type EnsureOutputDir = Callable[[str], Path]
type ActiveVariantArgs = Callable[[], list[str]]
type RunCliVariants = Callable[[list[list[str]]], tuple[int, str, str]]
type FormatFileList = Callable[[list[Path], str], str]


class PcbVectorCapabilities(Protocol):
    """Capability subset required by PCB vector export."""

    @property
    def supports_svg(self) -> bool: ...

    @property
    def supports_dxf(self) -> bool: ...


type GetCapabilities = Callable[[], PcbVectorCapabilities]


@dataclass(frozen=True)
class ExportPcbVectorService:
    """Export PCB SVG/DXF files through injected project and CLI seams."""

    get_pcb_file: GetPcbFile
    get_capabilities: GetCapabilities
    ensure_output_dir: EnsureOutputDir
    active_variant_args: ActiveVariantArgs
    run_cli_variants: RunCliVariants
    format_file_list: FormatFileList

    def export_svg(self, layer: str = "F.Cu") -> str:
        """Export a board layer to SVG while preserving the legacy CLI contract."""
        pcb_file = self.get_pcb_file()
        if not self.get_capabilities().supports_svg:
            return "SVG export is not supported by the detected KiCad CLI."

        out_dir = self.ensure_output_dir("svg")
        variant_args = self.active_variant_args()
        code, _stdout, stderr = self.run_cli_variants(
            [
                [
                    "pcb",
                    "export",
                    "svg",
                    *variant_args,
                    "--mode-multi",
                    "--layers",
                    layer,
                    "--output",
                    str(out_dir),
                    str(pcb_file),
                ]
            ]
        )
        if code != 0:
            return f"SVG export failed: {stderr or 'unknown error'}"
        files = sorted(out_dir.glob("*.svg"))
        return self.format_file_list(files, f"SVG export completed in {out_dir}:")

    def export_dxf(self, layer: str = "Edge.Cuts") -> str:
        """Export a board layer to DXF while preserving the legacy CLI fallbacks."""
        pcb_file = self.get_pcb_file()
        if not self.get_capabilities().supports_dxf:
            return "DXF export is not supported by the detected KiCad CLI."

        out_dir = self.ensure_output_dir("dxf")
        variant_args = self.active_variant_args()
        code, _stdout, stderr = self.run_cli_variants(
            [
                [
                    "pcb",
                    "export",
                    "dxf",
                    *variant_args,
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
                    *variant_args,
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
        return self.format_file_list(files, f"DXF export completed in {out_dir}:")
