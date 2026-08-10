from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any


def _service_type() -> type[Any]:
    spec = importlib.util.find_spec("kicad_mcp.export.pcb_3d_render")
    assert spec is not None, "PCB 3D render service module must be extracted"
    module = importlib.import_module("kicad_mcp.export.pcb_3d_render")
    return module.ExportPcb3dRenderService


def _service(
    tmp_path: Path,
    *,
    supported: bool = True,
    variant_args: list[str] | None = None,
    cli_result: tuple[int, str, str] = (0, "", ""),
):
    service_type = _service_type()
    calls: dict[str, list[Any]] = {
        "pcb": [],
        "supported": [],
        "resolve": [],
        "variant": [],
        "cli": [],
        "human_size": [],
    }

    def get_pcb_file() -> Path:
        calls["pcb"].append(None)
        return tmp_path / "demo.kicad_pcb"

    def is_supported() -> bool:
        calls["supported"].append(None)
        return supported

    def resolve_output_file(subdir: str, output_file: str, *, default_name: str) -> Path:
        calls["resolve"].append((subdir, output_file, default_name))
        if output_file == "bad.png":
            raise ValueError("unsafe output")
        return tmp_path / "output" / subdir / (output_file or default_name)

    def active_variant_args() -> list[str]:
        calls["variant"].append(None)
        return list(variant_args or [])

    def run_cli_variants(variants: list[list[str]]) -> tuple[int, str, str]:
        calls["cli"].append(variants)
        return cli_result

    def human_size(size: int) -> str:
        calls["human_size"].append(size)
        return f"size:{size}"

    service = service_type(
        get_pcb_file=get_pcb_file,
        is_supported=is_supported,
        resolve_output_file=resolve_output_file,
        active_variant_args=active_variant_args,
        run_cli_variants=run_cli_variants,
        human_size=human_size,
    )
    return service, calls


def test_render_preserves_default_argv_and_active_variant_order(tmp_path: Path) -> None:
    service, calls = _service(tmp_path, variant_args=["--variant", "assembly-a"])

    response = service.render()

    out_file = tmp_path / "output" / "3d" / "render.png"
    assert calls["pcb"] == [None]
    assert calls["supported"] == [None]
    assert calls["resolve"] == [("3d", "render.png", "render.png")]
    assert calls["variant"] == [None]
    assert calls["cli"] == [
        [
            [
                "pcb",
                "render",
                "--output",
                str(out_file),
                "--side",
                "top",
                "--zoom",
                "1.0",
                "--variant",
                "assembly-a",
                str(tmp_path / "demo.kicad_pcb"),
            ]
        ]
    ]
    assert response.text == f"Rendered board image exported to {out_file}"
    assert response.image_path is None
    assert response.summary is None


def test_render_preserves_all_optional_flags_and_order(tmp_path: Path) -> None:
    service, calls = _service(tmp_path)

    service.render(
        output_file="custom.jpg",
        side="bottom",
        zoom=2.5,
        width=1920,
        height=1080,
        quality=0.75,
        preset="photo",
        use_board_stackup_colors=True,
        floor=False,
        perspective=False,
        pan_x=1.25,
        pan_y=-2.5,
        rotate_x=10.0,
        rotate_y=20.0,
        rotate_z=30.0,
        light_top=0.1,
        light_bottom=0.2,
        light_side=0.3,
        light_camera=0.4,
        light_side_elevation=45.0,
    )

    out_file = tmp_path / "output" / "3d" / "custom.jpg"
    assert calls["cli"] == [
        [
            [
                "pcb",
                "render",
                "--output",
                str(out_file),
                "--side",
                "bottom",
                "--zoom",
                "2.5",
                "--width",
                "1920",
                "--height",
                "1080",
                "--quality",
                "0.75",
                "--preset",
                "photo",
                "--use-board-stackup-colors",
                "--no-floor",
                "--orthographic",
                "--pan",
                "1.25,-2.5",
                "--rotate",
                "10.0,20.0,30.0",
                "--light-top",
                "0.1",
                "--light-bottom",
                "0.2",
                "--light-side",
                "0.3",
                "--light-camera",
                "0.4",
                "--light-side-elevation",
                "45.0",
                str(tmp_path / "demo.kicad_pcb"),
            ]
        ]
    ]


def test_render_preserves_partial_pan_and_rotation_defaults(tmp_path: Path) -> None:
    service, calls = _service(tmp_path)

    service.render(pan_y=3.0, rotate_y=12.0)

    args = calls["cli"][0][0]
    assert args[args.index("--pan") + 1] == "0.0,3.0"
    assert args[args.index("--rotate") + 1] == "0,12.0,0"


def test_render_preserves_capability_and_path_failures(tmp_path: Path) -> None:
    unsupported, unsupported_calls = _service(tmp_path, supported=False)
    response = unsupported.render()
    assert response.text == "3D render export is not supported by the detected KiCad CLI."
    assert unsupported_calls["pcb"] == [None]
    assert unsupported_calls["resolve"] == []
    assert unsupported_calls["cli"] == []

    invalid, invalid_calls = _service(tmp_path)
    response = invalid.render(output_file="bad.png")
    assert response.text == "Invalid output path: unsafe output"
    assert invalid_calls["cli"] == []


def test_render_preserves_failure_precedence_and_ignores_stdout(tmp_path: Path) -> None:
    stderr_service, _ = _service(tmp_path, cli_result=(2, "stdout detail", "stderr detail"))
    assert stderr_service.render().text == "3D render failed: stderr detail"

    stdout_only_service, _ = _service(tmp_path, cli_result=(2, "stdout detail", ""))
    assert stdout_only_service.render().text == "3D render failed: unknown error"


def test_render_returns_image_response_with_human_size_when_artifact_exists(tmp_path: Path) -> None:
    service, calls = _service(tmp_path)
    out_file = tmp_path / "output" / "3d" / "board.png"
    out_file.parent.mkdir(parents=True)
    out_file.write_bytes(b"png-bytes")

    response = service.render(output_file="board.png")

    assert response.text is None
    assert response.image_path == out_file
    assert response.summary == f"Rendered board image exported to {out_file} (size:9)"
    assert calls["human_size"] == [9]
