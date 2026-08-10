"""FastMCP-free PCB 3D PDF export behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

type GetPcbFile = Callable[[], Path]
type Supports3dPdf = Callable[[], bool]
type ResolveOutputFile = Callable[[str], Path]
type ActiveVariantArgs = Callable[[], list[str]]
type RunCliVariants = Callable[[list[list[str]]], tuple[int, str, str]]


@dataclass(frozen=True)
class ExportPcb3dPdfService:
    """Export PCB 3D PDF through injected project and CLI seams."""

    get_pcb_file: GetPcbFile
    supports_3d_pdf: Supports3dPdf
    resolve_output_file: ResolveOutputFile
    active_variant_args: ActiveVariantArgs
    run_cli_variants: RunCliVariants

    def export(self, output_path: str = "") -> str:
        """Export a 3D PDF while preserving the legacy capability and CLI contract."""
        pcb_file = self.get_pcb_file()
        if not self.supports_3d_pdf():
            return "3D PDF export is not supported by the detected KiCad CLI."

        try:
            out_file = self.resolve_output_file(output_path)
        except ValueError as exc:
            return f"Invalid output path: {exc}"

        variant_args = self.active_variant_args()
        code, _stdout, stderr = self.run_cli_variants(
            [
                [
                    "pcb",
                    "export",
                    "3d-pdf",
                    *variant_args,
                    "--output",
                    str(out_file),
                    str(pcb_file),
                ],
                [
                    "pcb",
                    "export",
                    "3d-pdf",
                    *variant_args,
                    "--input",
                    str(pcb_file),
                    "--output",
                    str(out_file),
                ],
            ]
        )
        if code != 0:
            return f"3D PDF export failed: {stderr or 'unknown error'}"
        return f"3D PDF exported to {out_file}"
