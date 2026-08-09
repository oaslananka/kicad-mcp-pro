"""FastMCP-free schematic SVG/DXF export behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

type GetSchFile = Callable[[], Path]
type EnsureOutputDir = Callable[[str], Path]
type FormatFileList = Callable[[list[Path], str], str]


class ResolveOutputFile(Protocol):
    """Resolve a safe export path using the composition root's path policy."""

    def __call__(self, subdir: str, raw_name: str, *, default_name: str) -> Path: ...


class RunCli(Protocol):
    """Execute kicad-cli arguments without shell interpolation."""

    def __call__(self, *args: str) -> tuple[int, str, str]: ...


@dataclass(frozen=True)
class ExportSchVectorService:
    """Export schematic SVG/DXF files through injected project and CLI seams."""

    get_sch_file: GetSchFile
    ensure_output_dir: EnsureOutputDir
    resolve_output_file: ResolveOutputFile
    run_cli: RunCli
    format_file_list: FormatFileList

    def _export(
        self,
        format_name: str,
        label: str,
        extension: str,
        *,
        output_dir: str = "",
        pages: str = "",
        variant_name: str = "",
        theme: str = "",
        black_and_white: bool = False,
        exclude_drawing_sheet: bool = False,
        draw_hop_over: bool = False,
        no_background_color: bool = False,
    ) -> str:
        sch_file = self.get_sch_file()
        try:
            out_dir = (
                self.ensure_output_dir(format_name)
                if not output_dir
                else self.resolve_output_file(format_name, output_dir, default_name="")
            )
        except ValueError as exc:
            return f"Invalid output path: {exc}"

        cmd = ["sch", "export", format_name]
        if pages:
            cmd.extend(["--pages", pages])
        if variant_name:
            cmd.extend(["--variant", variant_name])
        if theme:
            cmd.extend(["--theme", theme])
        if black_and_white:
            cmd.append("--black-and-white")
        if exclude_drawing_sheet:
            cmd.append("--exclude-drawing-sheet")
        if draw_hop_over:
            cmd.append("--draw-hop-over")
        if no_background_color:
            cmd.append("--no-background-color")
        cmd.extend(["--output", str(out_dir)])
        cmd.append(str(sch_file))

        code, stdout, stderr = self.run_cli(*cmd)
        if code != 0:
            return f"Schematic {label} export failed: {stderr or stdout or 'unknown error'}"
        files = sorted(out_dir.glob(f"*.{extension}")) if out_dir.is_dir() else []
        return self.format_file_list(files, f"Schematic {label} export completed in {out_dir}:")

    def export_svg(
        self,
        output_dir: str = "",
        pages: str = "",
        variant_name: str = "",
        theme: str = "",
        black_and_white: bool = False,
        exclude_drawing_sheet: bool = False,
        draw_hop_over: bool = False,
        no_background_color: bool = False,
    ) -> str:
        """Export schematic SVG files while preserving the legacy CLI contract."""
        return self._export(
            "svg",
            "SVG",
            "svg",
            output_dir=output_dir,
            pages=pages,
            variant_name=variant_name,
            theme=theme,
            black_and_white=black_and_white,
            exclude_drawing_sheet=exclude_drawing_sheet,
            draw_hop_over=draw_hop_over,
            no_background_color=no_background_color,
        )

    def export_dxf(
        self,
        output_dir: str = "",
        pages: str = "",
        variant_name: str = "",
        theme: str = "",
        black_and_white: bool = False,
        exclude_drawing_sheet: bool = False,
        draw_hop_over: bool = False,
    ) -> str:
        """Export schematic DXF files while preserving the legacy CLI contract."""
        return self._export(
            "dxf",
            "DXF",
            "dxf",
            output_dir=output_dir,
            pages=pages,
            variant_name=variant_name,
            theme=theme,
            black_and_white=black_and_white,
            exclude_drawing_sheet=exclude_drawing_sheet,
            draw_hop_over=draw_hop_over,
        )
