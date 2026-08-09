from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any


def _service_type() -> type[Any]:
    spec = importlib.util.find_spec("kicad_mcp.export.sch_vector")
    assert spec is not None, "schematic vector export service module must be extracted"
    module = importlib.import_module("kicad_mcp.export.sch_vector")
    return module.ExportSchVectorService


class FakeResolver:
    def __init__(self, outputs: dict[tuple[str, str], Path] | Exception) -> None:
        self.outputs = outputs
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, subdir: str, raw_name: str, *, default_name: str) -> Path:
        self.calls.append((subdir, raw_name, default_name))
        if isinstance(self.outputs, Exception):
            raise self.outputs
        return self.outputs[(subdir, raw_name)]


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
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, *args: str) -> tuple[int, str, str]:
        self.calls.append(args)
        return self.result


class FakeFormatter:
    def __init__(self) -> None:
        self.calls: list[tuple[list[Path], str]] = []

    def __call__(self, files: list[Path], heading: str) -> str:
        self.calls.append((files, heading))
        return f"formatted::{heading}::{','.join(path.name for path in files)}"


def _service(tmp_path: Path, *, cli: FakeCli | None = None):
    service_type = _service_type()
    svg_dir = tmp_path / "svg"
    dxf_dir = tmp_path / "dxf"
    svg_dir.mkdir(exist_ok=True)
    dxf_dir.mkdir(exist_ok=True)
    ensure = FakeEnsureOutputDir({"svg": svg_dir, "dxf": dxf_dir})
    resolver = FakeResolver(
        {
            ("svg", "custom-svg"): tmp_path / "custom-svg",
            ("dxf", "custom-dxf"): tmp_path / "custom-dxf",
        }
    )
    formatter = FakeFormatter()
    active_cli = cli or FakeCli()
    return (
        service_type(
            get_sch_file=lambda: tmp_path / "demo.kicad_sch",
            ensure_output_dir=ensure,
            resolve_output_file=resolver,
            run_cli=active_cli,
            format_file_list=formatter,
        ),
        ensure,
        resolver,
        active_cli,
        formatter,
    )


def test_svg_default_export_preserves_cli_argv_and_sorted_files(tmp_path: Path) -> None:
    service, ensure, resolver, cli, formatter = _service(tmp_path)
    svg_dir = tmp_path / "svg"
    (svg_dir / "b.svg").write_text("b")
    (svg_dir / "a.svg").write_text("a")

    result = service.export_svg()

    assert ensure.calls == ["svg"]
    assert resolver.calls == []
    assert cli.calls == [
        (
            "sch",
            "export",
            "svg",
            "--output",
            str(svg_dir),
            str(tmp_path / "demo.kicad_sch"),
        )
    ]
    assert formatter.calls == [
        ([svg_dir / "a.svg", svg_dir / "b.svg"], f"Schematic SVG export completed in {svg_dir}:")
    ]
    assert result == f"formatted::Schematic SVG export completed in {svg_dir}:::a.svg,b.svg"


def test_svg_preserves_all_optional_cli_arguments_and_explicit_output(tmp_path: Path) -> None:
    service, ensure, resolver, cli, _formatter = _service(tmp_path)

    result = service.export_svg(
        output_dir="custom-svg",
        pages="1,3",
        variant_name="assembly-a",
        theme="dark",
        black_and_white=True,
        exclude_drawing_sheet=True,
        draw_hop_over=True,
        no_background_color=True,
    )

    out = tmp_path / "custom-svg"
    assert ensure.calls == []
    assert resolver.calls == [("svg", "custom-svg", "")]
    assert cli.calls == [
        (
            "sch",
            "export",
            "svg",
            "--pages",
            "1,3",
            "--variant",
            "assembly-a",
            "--theme",
            "dark",
            "--black-and-white",
            "--exclude-drawing-sheet",
            "--draw-hop-over",
            "--no-background-color",
            "--output",
            str(out),
            str(tmp_path / "demo.kicad_sch"),
        )
    ]
    assert result == f"formatted::Schematic SVG export completed in {out}:::"


def test_dxf_default_export_preserves_cli_argv_and_sorted_files(tmp_path: Path) -> None:
    service, ensure, resolver, cli, formatter = _service(tmp_path)
    dxf_dir = tmp_path / "dxf"
    (dxf_dir / "z.dxf").write_text("z")
    (dxf_dir / "a.dxf").write_text("a")

    result = service.export_dxf()

    assert ensure.calls == ["dxf"]
    assert resolver.calls == []
    assert cli.calls == [
        (
            "sch",
            "export",
            "dxf",
            "--output",
            str(dxf_dir),
            str(tmp_path / "demo.kicad_sch"),
        )
    ]
    assert formatter.calls == [
        ([dxf_dir / "a.dxf", dxf_dir / "z.dxf"], f"Schematic DXF export completed in {dxf_dir}:")
    ]
    assert result == f"formatted::Schematic DXF export completed in {dxf_dir}:::a.dxf,z.dxf"


def test_dxf_preserves_all_optional_cli_arguments_and_explicit_output(tmp_path: Path) -> None:
    service, ensure, resolver, cli, _formatter = _service(tmp_path)

    result = service.export_dxf(
        output_dir="custom-dxf",
        pages="2",
        variant_name="assembly-b",
        theme="light",
        black_and_white=True,
        exclude_drawing_sheet=True,
        draw_hop_over=True,
    )

    out = tmp_path / "custom-dxf"
    assert ensure.calls == []
    assert resolver.calls == [("dxf", "custom-dxf", "")]
    assert cli.calls == [
        (
            "sch",
            "export",
            "dxf",
            "--pages",
            "2",
            "--variant",
            "assembly-b",
            "--theme",
            "light",
            "--black-and-white",
            "--exclude-drawing-sheet",
            "--draw-hop-over",
            "--output",
            str(out),
            str(tmp_path / "demo.kicad_sch"),
        )
    ]
    assert result == f"formatted::Schematic DXF export completed in {out}:::"


def test_vector_exports_preserve_invalid_output_path_messages(tmp_path: Path) -> None:
    service_type = _service_type()
    cli = FakeCli()
    service = service_type(
        get_sch_file=lambda: tmp_path / "demo.kicad_sch",
        ensure_output_dir=FakeEnsureOutputDir({}),
        resolve_output_file=FakeResolver(ValueError("unsafe path")),
        run_cli=cli,
        format_file_list=FakeFormatter(),
    )

    assert service.export_svg(output_dir="../svg") == "Invalid output path: unsafe path"
    assert service.export_dxf(output_dir="../dxf") == "Invalid output path: unsafe path"
    assert cli.calls == []


def test_vector_exports_preserve_failure_message_precedence(tmp_path: Path) -> None:
    service_type = _service_type()

    def service_for(result: tuple[int, str, str]):
        svg_dir = tmp_path / "svg"
        dxf_dir = tmp_path / "dxf"
        svg_dir.mkdir(exist_ok=True)
        dxf_dir.mkdir(exist_ok=True)
        return service_type(
            get_sch_file=lambda: tmp_path / "demo.kicad_sch",
            ensure_output_dir=FakeEnsureOutputDir({"svg": svg_dir, "dxf": dxf_dir}),
            resolve_output_file=FakeResolver({}),
            run_cli=FakeCli(result),
            format_file_list=FakeFormatter(),
        )

    assert service_for((2, "stdout detail", "stderr detail")).export_svg() == (
        "Schematic SVG export failed: stderr detail"
    )
    assert service_for((2, "stdout detail", "")).export_svg() == (
        "Schematic SVG export failed: stdout detail"
    )
    assert service_for((2, "", "")).export_svg() == "Schematic SVG export failed: unknown error"
    assert service_for((2, "stdout detail", "stderr detail")).export_dxf() == (
        "Schematic DXF export failed: stderr detail"
    )
    assert service_for((2, "stdout detail", "")).export_dxf() == (
        "Schematic DXF export failed: stdout detail"
    )
    assert service_for((2, "", "")).export_dxf() == "Schematic DXF export failed: unknown error"
