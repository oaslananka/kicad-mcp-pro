"""FastMCP-free schematic netlist export behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..models.export import ExportNetlistInput

type GetSchFile = Callable[[], Path]
type EnsureOutputDir = Callable[[str | None], Path]
type ActiveVariantArgs = Callable[[], list[str]]
type RunCliVariants = Callable[[list[list[str]]], tuple[int, str, str]]


@dataclass(frozen=True)
class ExportNetlistService:
    """Export schematic netlists through injected project and CLI seams."""

    get_sch_file: GetSchFile
    ensure_output_dir: EnsureOutputDir
    active_variant_args: ActiveVariantArgs
    run_cli_variants: RunCliVariants

    def export(self, format_name: str = "kicad") -> str:
        """Export one supported schematic netlist format."""
        payload = ExportNetlistInput(format=format_name)
        sch_file = self.get_sch_file()
        out_dir = self.ensure_output_dir(None)
        extension_map = {
            "kicad": "net",
            "spice": "cir",
            "cadstar": "frp",
            "orcadpcb2": "net",
        }
        cli_format_map = {
            "kicad": "kicadsexpr",
            "spice": "spice",
            "cadstar": "cadstar",
            "orcadpcb2": "orcadpcb2",
        }
        out_file = out_dir / f"netlist.{extension_map[payload.format]}"
        variant_args = self.active_variant_args()
        code, _stdout, stderr = self.run_cli_variants(
            [
                [
                    "sch",
                    "export",
                    "netlist",
                    *variant_args,
                    "--format",
                    cli_format_map[payload.format],
                    "--output",
                    str(out_file),
                    str(sch_file),
                ]
            ]
        )
        if code != 0:
            return f"Netlist export failed: {stderr or 'unknown error'}"
        return f"Netlist exported to {out_file}"
