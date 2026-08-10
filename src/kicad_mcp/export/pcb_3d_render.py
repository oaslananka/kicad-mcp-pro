"""FastMCP-independent PCB 3D render export orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ResolveOutputFile(Protocol):
    def __call__(self, subdir: str, raw_name: str, *, default_name: str) -> Path: ...


@dataclass(frozen=True)
class Pcb3dRenderOptions:
    """Typed internal options for the public 3D-render tool contract."""

    output_file: str = "render.png"
    side: str = "top"
    zoom: float = 1.0
    width: int | None = None
    height: int | None = None
    quality: float | None = None
    preset: str | None = None
    use_board_stackup_colors: bool = False
    floor: bool = True
    perspective: bool = True
    pan_x: float | None = None
    pan_y: float | None = None
    rotate_x: float | None = None
    rotate_y: float | None = None
    rotate_z: float | None = None
    light_top: float | None = None
    light_bottom: float | None = None
    light_side: float | None = None
    light_camera: float | None = None
    light_side_elevation: float | None = None


@dataclass(frozen=True)
class Pcb3dRenderResponse:
    """Internal render result converted to MCP content by the thin adapter."""

    text: str | None = None
    image_path: Path | None = None
    summary: str | None = None


def _append_optional(args: list[str], flag: str, value: object | None) -> None:
    if value is not None:
        args.extend([flag, str(value)])


def _camera_args(options: Pcb3dRenderOptions) -> list[str]:
    args: list[str] = []
    if options.pan_x is not None or options.pan_y is not None:
        px = options.pan_x if options.pan_x is not None else 0.0
        py = options.pan_y if options.pan_y is not None else 0.0
        args.extend(["--pan", f"{px},{py}"])
    if any(value is not None for value in (options.rotate_x, options.rotate_y, options.rotate_z)):
        rx = options.rotate_x or 0
        ry = options.rotate_y or 0
        rz = options.rotate_z or 0
        args.extend(["--rotate", f"{rx},{ry},{rz}"])
    return args


def _render_args(options: Pcb3dRenderOptions, out_file: Path) -> list[str]:
    args = [
        "pcb",
        "render",
        "--output",
        str(out_file),
        "--side",
        options.side,
        "--zoom",
        str(options.zoom),
    ]
    _append_optional(args, "--width", options.width)
    _append_optional(args, "--height", options.height)
    _append_optional(args, "--quality", options.quality)
    if options.preset:
        args.extend(["--preset", options.preset])
    if options.use_board_stackup_colors:
        args.append("--use-board-stackup-colors")
    if not options.floor:
        args.append("--no-floor")
    if not options.perspective:
        args.append("--orthographic")
    args.extend(_camera_args(options))
    _append_optional(args, "--light-top", options.light_top)
    _append_optional(args, "--light-bottom", options.light_bottom)
    _append_optional(args, "--light-side", options.light_side)
    _append_optional(args, "--light-camera", options.light_camera)
    _append_optional(args, "--light-side-elevation", options.light_side_elevation)
    return args


@dataclass(frozen=True)
class ExportPcb3dRenderService:
    """Render the active PCB through the KiCad CLI without MCP dependencies."""

    get_pcb_file: Callable[[], Path]
    is_supported: Callable[[], bool]
    resolve_output_file: ResolveOutputFile
    active_variant_args: Callable[[], list[str]]
    run_cli_variants: Callable[[list[list[str]]], tuple[int, str, str]]
    human_size: Callable[[int], str]

    def render(self, options: Pcb3dRenderOptions | None = None) -> Pcb3dRenderResponse:
        options = options or Pcb3dRenderOptions()
        pcb_file = self.get_pcb_file()
        if not self.is_supported():
            return Pcb3dRenderResponse(
                text="3D render export is not supported by the detected KiCad CLI."
            )

        try:
            out_file = self.resolve_output_file(
                "3d", options.output_file, default_name="render.png"
            )
        except ValueError as exc:
            return Pcb3dRenderResponse(text=f"Invalid output path: {exc}")

        args = _render_args(options, out_file)
        args.extend(self.active_variant_args())
        args.append(str(pcb_file))
        code, _, stderr = self.run_cli_variants([args])
        if code != 0:
            return Pcb3dRenderResponse(text=f"3D render failed: {stderr or 'unknown error'}")
        if not out_file.exists():
            return Pcb3dRenderResponse(text=f"Rendered board image exported to {out_file}")

        size = self.human_size(out_file.stat().st_size)
        return Pcb3dRenderResponse(
            image_path=out_file,
            summary=f"Rendered board image exported to {out_file} ({size})",
        )
