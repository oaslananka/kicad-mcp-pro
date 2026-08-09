"""FastMCP-free Gerber export behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..models.export import ExportGerberInput

type GetPcbFile = Callable[[], Path]
type EnsureOutputDir = Callable[[str | None], Path]
type GetGerberCommand = Callable[[], str]
type ActiveVariantArgs = Callable[[str | None], list[str]]
type RunCliVariants = Callable[[list[list[str]]], tuple[int, str, str]]
type FormatFileList = Callable[[list[Path], str], str]


@dataclass(frozen=True)
class ExportGerberService:
    """Export Gerbers through injected project and CLI seams."""

    get_pcb_file: GetPcbFile
    ensure_output_dir: EnsureOutputDir
    get_gerber_command: GetGerberCommand
    active_variant_args: ActiveVariantArgs
    run_cli_variants: RunCliVariants
    format_file_list: FormatFileList

    def export(
        self,
        output_subdir: str = "gerber",
        layers: list[str] | None = None,
        variant_name: str | None = None,
    ) -> str:
        """Export Gerbers while preserving the legacy CLI fallback contract."""
        payload = ExportGerberInput(output_subdir=output_subdir, layers=layers or [])
        pcb_file = self.get_pcb_file()
        try:
            out_dir = self.ensure_output_dir(payload.output_subdir)
        except ValueError as exc:
            return f"Invalid output path: {exc}"

        layer_args: list[str] = []
        if payload.layers:
            layer_args = ["--layers", ",".join(payload.layers)]
        variant_args = self.active_variant_args(variant_name)

        gerber_commands = ["gerbers", "gerber"]
        gerber_command = self.get_gerber_command()
        if gerber_command not in gerber_commands:
            gerber_commands.append(gerber_command)

        variants: list[list[str]] = []
        for command in gerber_commands:
            variants.extend(
                [
                    [
                        "pcb",
                        "export",
                        command,
                        *variant_args,
                        "--output",
                        str(out_dir),
                        *layer_args,
                        str(pcb_file),
                    ],
                    [
                        "pcb",
                        "export",
                        command,
                        *variant_args,
                        "--input",
                        str(pcb_file),
                        "--output",
                        str(out_dir),
                        *layer_args,
                    ],
                ]
            )

        code, _stdout, stderr = self.run_cli_variants(variants)
        if code != 0:
            return f"Gerber export failed: {stderr or 'unknown error'}"

        files = sorted(out_dir.glob("*.gbr")) + sorted(out_dir.glob("*.g*"))
        return self.format_file_list(files, f"Gerber export completed in {out_dir}:")
