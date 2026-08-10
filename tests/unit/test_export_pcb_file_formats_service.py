from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any

import pytest

FORMAT_CASES = [
    ("step", "step", "board.step", "STEP", []),
    ("stepz", "stpz", "board.stepz", "STEPZ", []),
    ("xao", "xao", "board.xao", "XAO", []),
    ("brep", "brep", "board.brep", "BREP", []),
    ("glb", "glb", "board.glb", "GLB", []),
    ("gencad", "gencad", "board.gencad", "GenCAD", []),
    ("ipc_d356", "ipcd356", "board.d356", "IPC-D-356", []),
    ("ply", "ply", "board.ply", "PLY", []),
    ("stl", "stl", "board.stl", "STL", []),
    ("u3d", "u3d", "board.u3d", "U3D", []),
    ("vrml", "vrml", "board.wrl", "VRML", ["--units", "in"]),
    ("ps", "ps", "board.ps", "PostScript", []),
]


def _service_type() -> type[Any]:
    spec = importlib.util.find_spec("kicad_mcp.export.pcb_file_formats")
    assert spec is not None, "PCB single-file export service module must be extracted"
    module = importlib.import_module("kicad_mcp.export.pcb_file_formats")
    return module.ExportPcbFileFormatsService


def _service(
    tmp_path: Path,
    *,
    supported: set[str] | None = None,
    cli_result: tuple[int, str, str] = (0, "", ""),
    resolver_error: ValueError | None = None,
):
    service_type = _service_type()
    calls: dict[str, list[Any]] = {
        "support": [],
        "resolve": [],
        "variant": [],
        "cli": [],
    }
    supported_names = supported if supported is not None else {case[0] for case in FORMAT_CASES}

    def is_supported(format_name: str) -> bool:
        calls["support"].append(format_name)
        return format_name in supported_names

    def resolve_output_file(subdir: str, raw_name: str, *, default_name: str) -> Path:
        calls["resolve"].append((subdir, raw_name, default_name))
        if resolver_error is not None:
            raise resolver_error
        return tmp_path / subdir / (raw_name or default_name)

    def active_variant_args(variant_name: str | None = None) -> list[str]:
        calls["variant"].append(variant_name)
        return ["--variant", variant_name or "assembly-a"]

    def run_cli(*args: str) -> tuple[int, str, str]:
        calls["cli"].append(args)
        return cli_result

    return (
        service_type(
            get_pcb_file=lambda: tmp_path / "demo.kicad_pcb",
            is_supported=is_supported,
            resolve_output_file=resolve_output_file,
            active_variant_args=active_variant_args,
            run_cli=run_cli,
        ),
        calls,
    )


@pytest.mark.parametrize(
    ("format_name", "cli_command", "default_name", "label", "extra_args"),
    FORMAT_CASES,
)
def test_default_exports_preserve_cli_contract(
    tmp_path: Path,
    format_name: str,
    cli_command: str,
    default_name: str,
    label: str,
    extra_args: list[str],
) -> None:
    service, calls = _service(tmp_path)

    result = service.export(format_name)

    out_file = tmp_path / "3d" / default_name
    assert calls["support"] == [format_name]
    assert calls["resolve"] == [("3d", "", default_name)]
    assert calls["variant"] == [None]
    assert calls["cli"] == [
        (
            "pcb",
            "export",
            cli_command,
            "--variant",
            "assembly-a",
            *extra_args,
            "--output",
            str(out_file),
            str(tmp_path / "demo.kicad_pcb"),
        )
    ]
    assert result == f"{label} model exported to {out_file}"


def test_export_preserves_generic_option_and_variant_order(tmp_path: Path) -> None:
    service, calls = _service(tmp_path)

    result = service.export(
        "brep",
        "custom.brep",
        force=True,
        no_unspecified=True,
        no_dnp=True,
        variant_name="fab",
        grid_origin=True,
        drill_origin=True,
        subst_models=True,
        board_only=True,
        cut_vias_in_body=True,
        no_board_body=True,
        no_components=True,
        component_filter="U1,R1",
        include_tracks=True,
        include_pads=True,
        include_zones=True,
        include_inner_copper=True,
        include_silkscreen=True,
        include_soldermask=True,
        fuse_shapes=True,
        fill_all_vias=True,
        no_extra_pad_thickness=True,
        min_distance="0.1mm",
        net_filter="GND",
        user_origin="10x20mm",
        units="mm",
        models_dir="models",
        models_relative=True,
    )

    out_file = tmp_path / "3d" / "custom.brep"
    assert calls["variant"] == ["fab"]
    assert calls["cli"] == [
        (
            "pcb",
            "export",
            "brep",
            "--force",
            "--no-unspecified",
            "--no-dnp",
            "--variant",
            "fab",
            "--grid-origin",
            "--drill-origin",
            "--subst-models",
            "--board-only",
            "--cut-vias-in-body",
            "--no-board-body",
            "--no-components",
            "--component-filter",
            "U1,R1",
            "--include-tracks",
            "--include-pads",
            "--include-zones",
            "--include-inner-copper",
            "--include-silkscreen",
            "--include-soldermask",
            "--fuse-shapes",
            "--fill-all-vias",
            "--no-extra-pad-thickness",
            "--min-distance",
            "0.1mm",
            "--net-filter",
            "GND",
            "--user-origin",
            "10x20mm",
            "--units",
            "mm",
            "--models-dir",
            "models",
            "--models-relative",
            "--output",
            str(out_file),
            str(tmp_path / "demo.kicad_pcb"),
        )
    ]
    assert result == f"BREP model exported to {out_file}"


def test_unsupported_export_stops_before_path_resolution_and_cli(tmp_path: Path) -> None:
    service, calls = _service(tmp_path, supported=set())

    assert service.export("step") == "STEP export is not supported by the detected KiCad CLI."
    assert calls["support"] == ["step"]
    assert calls["resolve"] == []
    assert calls["variant"] == []
    assert calls["cli"] == []


def test_invalid_output_path_preserves_message(tmp_path: Path) -> None:
    service, calls = _service(tmp_path, resolver_error=ValueError("unsafe path"))

    assert service.export("step", "../escape.step") == "Invalid output path: unsafe path"
    assert calls["variant"] == []
    assert calls["cli"] == []


@pytest.mark.parametrize(
    ("cli_result", "expected"),
    [
        ((2, "stdout detail", "stderr detail"), "STEP export failed: stderr detail"),
        ((2, "stdout detail", ""), "STEP export failed: stdout detail"),
        ((2, "", ""), "STEP export failed: unknown error"),
    ],
)
def test_failure_message_precedence(
    tmp_path: Path,
    cli_result: tuple[int, str, str],
    expected: str,
) -> None:
    service, _calls = _service(tmp_path, cli_result=cli_result)
    assert service.export("step") == expected
