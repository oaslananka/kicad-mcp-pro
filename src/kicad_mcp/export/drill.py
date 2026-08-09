"""FastMCP-free PCB drill export behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

type GetPcbFile = Callable[[], Path]
type EnsureOutputDir = Callable[[str | None], Path]
type GetDrillCommand = Callable[[], str]
type ActiveVariantArgs = Callable[[str | None], list[str]]
type RunCliVariants = Callable[[list[list[str]]], tuple[int, str, str]]
type FormatFileList = Callable[[list[Path], str], str]


@dataclass(frozen=True)
class ExportDrillService:
    """Export PCB drill files through injected project and CLI seams."""

    get_pcb_file: GetPcbFile
    ensure_output_dir: EnsureOutputDir
    get_drill_command: GetDrillCommand
    active_variant_args: ActiveVariantArgs
    run_cli_variants: RunCliVariants
    format_file_list: FormatFileList

    def export(self, output_subdir: str = "gerber", variant_name: str | None = None) -> str:
        """Export drill files while preserving the legacy CLI fallback contract."""
        pcb_file = self.get_pcb_file()
        try:
            out_dir = self.ensure_output_dir(output_subdir)
        except ValueError as exc:
            return f"Invalid output path: {exc}"
        drill_command = self.get_drill_command()
        variant_args = self.active_variant_args(variant_name)
        code, _stdout, stderr = self.run_cli_variants(
            [
                [
                    "pcb",
                    "export",
                    drill_command,
                    *variant_args,
                    "--output",
                    str(out_dir),
                    str(pcb_file),
                ],
                [
                    "pcb",
                    "export",
                    drill_command,
                    *variant_args,
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
        return self.format_file_list(files, f"Drill export completed in {out_dir}:")
