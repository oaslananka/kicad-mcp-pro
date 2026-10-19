"""FastMCP-free single-file PCB export format behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

type GetPcbFile = Callable[[], Path]
type IsSupported = Callable[[str], bool]
type ActiveVariantArgs = Callable[[str | None], list[str]]


class ResolveOutputFile(Protocol):
    """Resolve a safe project-local export path."""

    def __call__(self, subdir: str, raw_name: str, *, default_name: str) -> Path: ...


class RunCli(Protocol):
    """Execute kicad-cli arguments without shell interpolation."""

    def __call__(self, *args: str) -> tuple[int, str, str]: ...


@dataclass(frozen=True)
class PcbFileFormatSpec:
    """Static CLI and output contract for one public PCB export format."""

    cli_command: str
    default_name: str
    label: str
    default_units: str = ""


FORMAT_SPECS: dict[str, PcbFileFormatSpec] = {
    "step": PcbFileFormatSpec("step", "board.step", "STEP"),
    "stepz": PcbFileFormatSpec("stpz", "board.stepz", "STEPZ"),
    "xao": PcbFileFormatSpec("xao", "board.xao", "XAO"),
    "brep": PcbFileFormatSpec("brep", "board.brep", "BREP"),
    "glb": PcbFileFormatSpec("glb", "board.glb", "GLB"),
    "gencad": PcbFileFormatSpec("gencad", "board.gencad", "GenCAD"),
    "ipc_d356": PcbFileFormatSpec("ipcd356", "board.d356", "IPC-D-356"),
    "ply": PcbFileFormatSpec("ply", "board.ply", "PLY"),
    "stl": PcbFileFormatSpec("stl", "board.stl", "STL"),
    "u3d": PcbFileFormatSpec("u3d", "board.u3d", "U3D"),
    "vrml": PcbFileFormatSpec("vrml", "board.wrl", "VRML", default_units="in"),
    "ps": PcbFileFormatSpec("ps", "board.ps", "PostScript"),
}


@dataclass(frozen=True)
class PcbExportOptions:
    """Configurable options for single-file PCB export formats."""

    force: bool = False
    no_unspecified: bool = False
    no_dnp: bool = False
    variant_name: str | None = None
    grid_origin: bool = False
    drill_origin: bool = False
    subst_models: bool = False
    board_only: bool = False
    cut_vias_in_body: bool = False
    no_board_body: bool = False
    no_components: bool = False
    component_filter: str = ""
    include_tracks: bool = False
    include_pads: bool = False
    include_zones: bool = False
    include_inner_copper: bool = False
    include_silkscreen: bool = False
    include_soldermask: bool = False
    fuse_shapes: bool = False
    fill_all_vias: bool = False
    no_extra_pad_thickness: bool = False
    min_distance: str = ""
    net_filter: str = ""
    user_origin: str = ""
    units: str = ""
    models_dir: str = ""
    models_relative: bool = False


def _build_export_command(
    spec: PcbFileFormatSpec,
    opts: PcbExportOptions,
    out_file: Path,
    pcb_file: Path,
    active_variant_args: ActiveVariantArgs,
) -> list[str]:
    cmd = ["pcb", "export", spec.cli_command]
    if opts.force:
        cmd.append("--force")
    if opts.no_unspecified:
        cmd.append("--no-unspecified")
    if opts.no_dnp:
        cmd.append("--no-dnp")

    cmd.extend(active_variant_args(opts.variant_name))

    flag_options = (
        (opts.grid_origin, "--grid-origin"),
        (opts.drill_origin, "--drill-origin"),
        (opts.subst_models, "--subst-models"),
        (opts.board_only, "--board-only"),
        (opts.cut_vias_in_body, "--cut-vias-in-body"),
        (opts.no_board_body, "--no-board-body"),
        (opts.no_components, "--no-components"),
    )
    cmd.extend(flag for enabled, flag in flag_options if enabled)
    if opts.component_filter:
        cmd.extend(["--component-filter", opts.component_filter])

    include_options = (
        (opts.include_tracks, "--include-tracks"),
        (opts.include_pads, "--include-pads"),
        (opts.include_zones, "--include-zones"),
        (opts.include_inner_copper, "--include-inner-copper"),
        (opts.include_silkscreen, "--include-silkscreen"),
        (opts.include_soldermask, "--include-soldermask"),
        (opts.fuse_shapes, "--fuse-shapes"),
        (opts.fill_all_vias, "--fill-all-vias"),
        (opts.no_extra_pad_thickness, "--no-extra-pad-thickness"),
    )
    cmd.extend(flag for enabled, flag in include_options if enabled)

    val_options = (
        ("--min-distance", opts.min_distance),
        ("--net-filter", opts.net_filter),
        ("--user-origin", opts.user_origin),
        ("--units", opts.units or spec.default_units),
        ("--models-dir", opts.models_dir),
    )
    for opt_flag, val in val_options:
        if val:
            cmd.extend([opt_flag, val])

    if opts.models_relative:
        cmd.append("--models-relative")

    cmd.extend(["--output", str(out_file), str(pcb_file)])
    return cmd


@dataclass(frozen=True)
class ExportPcbFileFormatsService:
    """Export single-file PCB formats through injected project and CLI seams."""

    get_pcb_file: GetPcbFile
    is_supported: IsSupported
    resolve_output_file: ResolveOutputFile
    active_variant_args: ActiveVariantArgs
    run_cli: RunCli

    def export(
        self,
        format_name: str,
        output_path: str = "",
        *,
        options: PcbExportOptions | None = None,
        **kwargs: object,
    ) -> str:
        """Export one supported format while preserving the legacy CLI option order."""
        opts = options or PcbExportOptions(**kwargs)  # type: ignore[arg-type]
        spec = FORMAT_SPECS[format_name]
        pcb_file = self.get_pcb_file()
        if not self.is_supported(format_name):
            return f"{spec.label} export is not supported by the detected KiCad CLI."

        try:
            out_file = self.resolve_output_file("3d", output_path, default_name=spec.default_name)
        except ValueError as exc:
            return f"Invalid output path: {exc}"

        cmd = _build_export_command(spec, opts, out_file, pcb_file, self.active_variant_args)
        code, stdout, stderr = self.run_cli(*cmd)
        if code != 0:
            return f"{spec.label} export failed: {stderr or stdout or 'unknown error'}"
        return f"{spec.label} model exported to {out_file}"
