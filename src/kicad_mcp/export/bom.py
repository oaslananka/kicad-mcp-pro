"""FastMCP-free BOM export behavior."""

from __future__ import annotations

import csv
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ..models.export import ExportBOMInput

type GetSchFile = Callable[[], Path]
type EnsureOutputDir = Callable[[], Path]
type ActiveVariantArgs = Callable[[str | None], list[str]]
type RunCliVariants = Callable[[list[list[str]]], tuple[int, str, str]]
type ReadPreview = Callable[[Path], str]
type ProjectSchematicFiles = Callable[[], list[Path]]
type SchematicComponentRows = Callable[[], list[dict[str, str]]]

BOM_FIELDNAMES = [
    "reference",
    "value",
    "footprint",
    "lib_id",
    "lcsc",
    "mpn",
    "manufacturer",
    "populate",
]


@dataclass(frozen=True)
class ExportBomService:
    """Export BOM data through injected project and CLI seams."""

    get_sch_file: GetSchFile
    ensure_output_dir: EnsureOutputDir
    active_variant_args: ActiveVariantArgs
    run_cli_variants: RunCliVariants
    read_preview: ReadPreview
    project_schematic_files: ProjectSchematicFiles
    schematic_component_rows: SchematicComponentRows

    def export(self, format: str = "csv", variant_name: str | None = None) -> str:
        """Export a BOM while preserving consolidation and CLI fallback behavior."""
        payload = ExportBOMInput(format=format)
        sch_file = self.get_sch_file()
        out_dir = self.ensure_output_dir()
        suffix = "csv" if payload.format == "csv" else "xml"
        out_file = out_dir / f"bom.{suffix}"

        if payload.format == "csv":
            try:
                schematic_files = self.project_schematic_files()
                if len(schematic_files) > 1:
                    rows = self.schematic_component_rows()
                    with out_file.open("w", newline="", encoding="utf-8") as handle:
                        writer = csv.DictWriter(handle, fieldnames=BOM_FIELDNAMES)
                        writer.writeheader()
                        writer.writerows(rows)
                    return (
                        f"BOM exported to {out_file}\n"
                        f"Consolidated {len(rows)} reference(s) from "
                        f"{len(schematic_files)} schematic files.\n\n"
                        f"{self.read_preview(out_file)}"
                    )
            except (OSError, ValueError, RuntimeError) as exc:
                return f"BOM export failed: {exc}"

        variant_args = self.active_variant_args(variant_name)
        code, _stdout, stderr = self.run_cli_variants(
            [
                [
                    "sch",
                    "export",
                    "bom",
                    *variant_args,
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
                    *variant_args,
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
        return f"BOM exported to {out_file}\n\n{self.read_preview(out_file)}"
