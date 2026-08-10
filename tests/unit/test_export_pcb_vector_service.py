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


class FakeEnsureOutputDir:
    def __init__(self, outputs: dict[str, Path]) -> None:
        self.outputs = outputs
        self.calls: list[str] = []

    def __call__(self, subdir: str) -> Path:
        self.calls.append(subdir)
        return self.outputs[subdir]


class FakeCli:
    def __init__(self, result: tuple[int, str, str] = (0, "", "")) -> None:
        self.result = result
        self.calls: list[list[list[str]]] = []

    def __call__(self, variants: list[list[str]]) -> tuple[int, str, str]:
        self.calls.append(variants)
        return self.result


class FakeFormatter:
    def __init__(self) -> None:
        self.calls: list[tuple[list[Path], str]] = []

    def __call__(self, files: list[Path], heading: str) -> str:
        self.calls.append((files, heading))
        return f"formatted::{heading}::{','.join(path.name for path in files)}"


def _service(
    tmp_path: Path,
    *,
    capabilities: FakeCapabilities | None = None,
    variant_args: list[str] | None = None,
    cli: FakeCli | None = None,
):
    service_type = _service_type()
    svg_dir = tmp_path / "svg"
    dxf_dir = tmp_path / "dxf"
    svg_dir.mkdir(exist_ok=True)
    dxf_dir.mkdir(exist_ok=True)
    ensure = FakeEnsureOutputDir({"svg": svg_dir, "dxf": dxf_dir})
    active_cli = cli or FakeCli()
    formatter = FakeFormatter()
    service = service_type(
        get_pcb_file=lambda: tmp_path / "demo.kicad_pcb",
        get_capabilities=lambda: capabilities or FakeCapabilities(),
        ensure_output_dir=ensure,
        active_variant_args=lambda: list(variant_args or []),
        run_cli_variants=active_cli,
        format_file_list=formatter,
    )
    return service, ensure, active_cli, formatter


def test_svg_preserves_multi_mode_variant_argv_and_sorted_files(tmp_path: Path) -> None:
    service, ensure, cli, formatter = _service(
        tmp_path,
        variant_args=["--variant", "assembly-a"],
    )
    svg_dir = tmp_path / "svg"
    (svg_dir / "b.svg").write_text("b")
    (svg_dir / "a.svg").write_text("a")

    result = service.export_svg("Edge.Cuts")

    assert ensure.calls == ["svg"]
    assert cli.calls == [
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
    assert formatter.calls == [
        ([svg_dir / "a.svg", svg_dir / "b.svg"], f"SVG export completed in {svg_dir}:")
    ]
    assert result == f"formatted::SVG export completed in {svg_dir}:::a.svg,b.svg"


def test_dxf_preserves_variant_and_both_cli_fallbacks(tmp_path: Path) -> None:
    service, ensure, cli, formatter = _service(
        tmp_path,
        variant_args=["--variant", "assembly-b"],
    )
    dxf_dir = tmp_path / "dxf"
    (dxf_dir / "z.dxf").write_text("z")
    (dxf_dir / "a.dxf").write_text("a")

    result = service.export_dxf("B.Cu")

    pcb = str(tmp_path / "demo.kicad_pcb")
    assert ensure.calls == ["dxf"]
    assert cli.calls == [
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
    assert formatter.calls == [
        ([dxf_dir / "a.dxf", dxf_dir / "z.dxf"], f"DXF export completed in {dxf_dir}:")
    ]
    assert result == f"formatted::DXF export completed in {dxf_dir}:::a.dxf,z.dxf"


def test_vector_exports_preserve_unsupported_capability_messages(tmp_path: Path) -> None:
    service, ensure, cli, formatter = _service(
        tmp_path,
        capabilities=FakeCapabilities(supports_svg=False, supports_dxf=False),
    )

    assert service.export_svg() == "SVG export is not supported by the detected KiCad CLI."
    assert service.export_dxf() == "DXF export is not supported by the detected KiCad CLI."
    assert ensure.calls == []
    assert cli.calls == []
    assert formatter.calls == []


def test_vector_exports_preserve_failure_text_and_ignore_stdout(tmp_path: Path) -> None:
    svg_cli = FakeCli((2, "stdout detail", "stderr detail"))
    svg_service, _ensure, _cli, _formatter = _service(tmp_path, cli=svg_cli)
    assert svg_service.export_svg() == "SVG export failed: stderr detail"

    dxf_cli = FakeCli((2, "stdout detail", ""))
    dxf_service, _ensure, _cli, _formatter = _service(tmp_path, cli=dxf_cli)
    assert dxf_service.export_dxf() == "DXF export failed: unknown error"
