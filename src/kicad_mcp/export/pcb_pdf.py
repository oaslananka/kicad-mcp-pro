"""FastMCP-free PCB PDF export behavior."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from ..models.export import ExportPdfInput

type GetPcbFile = Callable[[], Path]
type EnsureOutputDir = Callable[[str | None], Path]
type ActiveVariantArgs = Callable[[], list[str]]
type RunCliVariants = Callable[[list[list[str]]], tuple[int, str, str]]


@dataclass(frozen=True)
class ExportPcbPdfService:
    """Export the PCB to PDF through injected project and CLI seams."""

    get_pcb_file: GetPcbFile
    ensure_output_dir: EnsureOutputDir
    active_variant_args: ActiveVariantArgs
    run_cli_variants: RunCliVariants
    default_layers: Sequence[str]

    def export(self, layers: list[str] | None = None) -> str:
        """Export the board PDF while preserving the legacy CLI fallback contract."""
        payload = ExportPdfInput(layers=layers or [])
        pcb_file = self.get_pcb_file()
        out_dir = self.ensure_output_dir(None)
        out_file = out_dir / "board.pdf"
        layers_arg = ",".join(payload.layers or self.default_layers)
        variant_args = self.active_variant_args()
        code, _stdout, stderr = self.run_cli_variants(
            [
                [
                    "pcb",
                    "export",
                    "pdf",
                    *variant_args,
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
                    *variant_args,
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
