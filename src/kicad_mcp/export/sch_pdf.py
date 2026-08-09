"""FastMCP-free schematic PDF export behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

type GetSchFile = Callable[[], Path]
type EnsureOutputDir = Callable[[], Path]
type ActiveVariantArgs = Callable[[], list[str]]
type RunCliVariants = Callable[[list[list[str]]], tuple[int, str, str]]


@dataclass(frozen=True)
class ExportSchPdfService:
    """Export the schematic to PDF through injected project and CLI seams."""

    get_sch_file: GetSchFile
    ensure_output_dir: EnsureOutputDir
    active_variant_args: ActiveVariantArgs
    run_cli_variants: RunCliVariants

    def export(self) -> str:
        """Export schematic PDF while preserving the legacy CLI fallback contract."""
        sch_file = self.get_sch_file()
        out_dir = self.ensure_output_dir()
        out_file = out_dir / "schematic.pdf"
        variant_args = self.active_variant_args()
        code, stdout, stderr = self.run_cli_variants(
            [
                ["sch", "export", "pdf", *variant_args, "--output", str(out_file), str(sch_file)],
                [
                    "sch",
                    "export",
                    "pdf",
                    *variant_args,
                    "--input",
                    str(sch_file),
                    "--output",
                    str(out_file),
                ],
            ]
        )
        if code != 0:
            return f"Schematic PDF export failed: {stderr or stdout or 'unknown error'}"
        return f"Schematic PDF exported to {out_file}"
