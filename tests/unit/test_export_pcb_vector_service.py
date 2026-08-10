from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _service_type() -> type[Any]:
    spec = importlib.util.find_spec("kicad_mcp.export.pcb_vector")
    assert spec is not None, "PCB vector export service module must be extracted"
    module = importlib.import_module("kicad_mcp.export.pcb_vector")
    return module.ExportPcbVectorService


@dataclass(frozen=True)
class FakeCapabilities:
    supports_svg: bool = True
    supports_dxf: bool = True


def _service(
    tmp_path: Path,
    *,
    capabilities: FakeCapabilities | None = None,
    variant_args: list[str] | None = None,
    cli_result: tuple[int, str, str] = (0, "", ""),
):
    service_type = _service_type()
    output_dirs = {"svg": tmp_path / "svg", "dxf": tmp_path / "dxf"}
    for directory in output_dirs.values():
        directory.mkdir(exist_ok=True)

    ensure_calls: list[str] = []
    cli_calls: list[list[list[str]]] = []
    formatter_calls: list[tuple[list[Path], str]] = []

    def ensure_output_dir(subdir: str) -> Path:
        ensure_calls.append(subdir)
        return output_dirs[subdir]

    def run_cli_variants(variants: list[list[str]]) -> tuple[int, str, str]:
        cli_calls.append(variants)
        return cli_result

    def format_file_list(files: list[Path], heading: str) -> str:
        formatter_calls.append((files, heading))
        return f"formatted::{heading}::{','.join(path.name for path in files)}"

    service = service_type(
        get_pcb_file=lambda: tmp_path / "demo.kicad_pcb",
        get_capabilities=lambda: capabilities or FakeCapabilities(),
        ensure_output_dir=ensure_output_dir,
        active_variant_args=lambda: list(variant_args or []),
        run_cli_variants=run_cli_variants,
        format_file_list=format_file_list,
    )
    return service, ensure_calls, cli_calls, formatter_calls


def test_svg_preserves_multi_mode_variant_argv_and_sorted_files(tmp_path: Path) -> None:
    service, ensure_calls, cli_calls, formatter_calls = _service(
        tmp_path,
        variant_args=["--variant", "assembly-a"],
    )
    svg_dir = tmp_path / "svg"
    (svg_dir / "b.svg").write_text("b")
    (svg_dir / "a.svg").write_text("a")

    result = service.export_svg("Edge.Cuts")

    assert ensure_calls == ["svg"]
    assert cli_calls == [
        [
            [
                "pcb",
                "export",
                "svg",
                "--variant",
                "assembly-a",
                "--mode-multi",
                "--layers",
                "Edge.Cuts",
                "--output",
                str(svg_dir),
                str(tmp_path / "demo.kicad_pcb"),
            ]
        ]
    ]
    assert formatter_calls == [
        ([svg_dir / "a.svg", svg_dir / "b.svg"], f"SVG export completed in {svg_dir}:")
    ]
    assert result == f"formatted::SVG export completed in {svg_dir}:::a.svg,b.svg"


def test_dxf_preserves_variant_and_both_cli_fallbacks(tmp_path: Path) -> None:
    service, ensure_calls, cli_calls, formatter_calls = _service(
        tmp_path,
        variant_args=["--variant", "assembly-b"],
    )
    dxf_dir = tmp_path / "dxf"
    (dxf_dir / "z.dxf").write_text("z")
    (dxf_dir / "a.dxf").write_text("a")

    result = service.export_dxf("B.Cu")

    pcb = str(tmp_path / "demo.kicad_pcb")
    assert ensure_calls == ["dxf"]
    assert cli_calls == [
        [
            [
                "pcb",
                "export",
                "dxf",
                "--variant",
                "assembly-b",
                "--layers",
                "B.Cu",
                "--output",
                str(dxf_dir),
                pcb,
            ],
            [
                "pcb",
                "export",
                "dxf",
                "--variant",
                "assembly-b",
                "--input",
                pcb,
                "--layers",
                "B.Cu",
                "--output",
                str(dxf_dir),
            ],
        ]
    ]
    assert formatter_calls == [
        ([dxf_dir / "a.dxf", dxf_dir / "z.dxf"], f"DXF export completed in {dxf_dir}:")
    ]
    assert result == f"formatted::DXF export completed in {dxf_dir}:::a.dxf,z.dxf"


def test_vector_exports_preserve_unsupported_capability_messages(tmp_path: Path) -> None:
    service, ensure_calls, cli_calls, formatter_calls = _service(
        tmp_path,
        capabilities=FakeCapabilities(supports_svg=False, supports_dxf=False),
    )

    assert service.export_svg() == "SVG export is not supported by the detected KiCad CLI."
    assert service.export_dxf() == "DXF export is not supported by the detected KiCad CLI."
    assert ensure_calls == []
    assert cli_calls == []
    assert formatter_calls == []


def test_vector_exports_preserve_failure_text_and_ignore_stdout(tmp_path: Path) -> None:
    svg_service, *_ = _service(tmp_path, cli_result=(2, "stdout detail", "stderr detail"))
    assert svg_service.export_svg() == "SVG export failed: stderr detail"

    dxf_service, *_ = _service(tmp_path, cli_result=(2, "stdout detail", ""))
    assert dxf_service.export_dxf() == "DXF export failed: unknown error"
