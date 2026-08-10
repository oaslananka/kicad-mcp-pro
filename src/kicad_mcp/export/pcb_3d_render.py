"""FastMCP-independent PCB 3D render export orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ResolveOutputFile(Protocol):
    def __call__(self, subdir: str, raw_name: str, *, default_name: str) -> Path: ...


@dataclass(frozen=True)
class Pcb3dRenderResponse:
    """Internal render result converted to MCP content by the thin adapter."""

    text: str | None = None
    image_path: Path | None = None
    summary: str | None = None


@dataclass(frozen=True)
class ExportPcb3dRenderService:
    """Render the active PCB through the KiCad CLI without MCP dependencies."""

    get_pcb_file: Callable[[], Path]
    is_supported: Callable[[], bool]
    resolve_output_file: ResolveOutputFile
    active_variant_args: Callable[[], list[str]]
    run_cli_variants: Callable[[list[list[str]]], tuple[int, str, str]]
    human_size: Callable[[int], str]

    def render(
        self,
        output_file: str = "render.png",
        side: str = "top",
        zoom: float = 1.0,
        width: int | None = None,
        height: int | None = None,
        quality: float | None = None,
        preset: str | None = None,
        use_board_stackup_colors: bool = False,
        floor: bool = True,
        perspective: bool = True,
        pan_x: float | None = None,
        pan_y: float | None = None,
        rotate_x: float | None = None,
        rotate_y: float | None = None,
        rotate_z: float | None = None,
        light_top: float | None = None,
        light_bottom: float | None = None,
        light_side: float | None = None,
        light_camera: float | None = None,
        light_side_elevation: float | None = None,
    ) -> Pcb3dRenderResponse:
        pcb_file = self.get_pcb_file()
        if not self.is_supported():
            return Pcb3dRenderResponse(
                text="3D render export is not supported by the detected KiCad CLI."
            )

        try:
            out_file = self.resolve_output_file("3d", output_file, default_name="render.png")
        except ValueError as exc:
            return Pcb3dRenderResponse(text=f"Invalid output path: {exc}")

        args: list[str] = [
            "pcb",
            "render",
            "--output",
            str(out_file),
            "--side",
            side,
            "--zoom",
            str(zoom),
        ]
        if width is not None:
            args.extend(["--width", str(width)])
        if height is not None:
            args.extend(["--height", str(height)])
        if quality is not None:
            args.extend(["--quality", str(quality)])
        if preset:
            args.extend(["--preset", preset])
        if use_board_stackup_colors:
            args.append("--use-board-stackup-colors")
        if not floor:
            args.append("--no-floor")
        if not perspective:
            args.append("--orthographic")
        if pan_x is not None or pan_y is not None:
            px = pan_x if pan_x is not None else 0.0
            py = pan_y if pan_y is not None else 0.0
            args.extend(["--pan", f"{px},{py}"])
        if any(value is not None for value in (rotate_x, rotate_y, rotate_z)):
            rx = rotate_x or 0
            ry = rotate_y or 0
            rz = rotate_z or 0
            args.extend(["--rotate", f"{rx},{ry},{rz}"])
        if light_top is not None:
            args.extend(["--light-top", str(light_top)])
        if light_bottom is not None:
            args.extend(["--light-bottom", str(light_bottom)])
        if light_side is not None:
            args.extend(["--light-side", str(light_side)])
        if light_camera is not None:
            args.extend(["--light-camera", str(light_camera)])
        if light_side_elevation is not None:
            args.extend(["--light-side-elevation", str(light_side_elevation)])

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
