from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any


def _service_type() -> type[Any]:
    spec = importlib.util.find_spec("kicad_mcp.export.drill")
    assert spec is not None, "drill export service module must be extracted"
    module = importlib.import_module("kicad_mcp.export.drill")
    return module.ExportDrillService


class FakeCli:
    def __init__(self, result: tuple[int, str, str] = (0, "", "")) -> None:
        self.result = result
        self.calls: list[list[list[str]]] = []

    def __call__(self, variants: list[list[str]]) -> tuple[int, str, str]:
        self.calls.append(variants)
        return self.result


def test_export_drill_preserves_capability_variant_cli_and_file_reporting(tmp_path: Path) -> None:
    service_type = _service_type()
    pcb = tmp_path / "demo.kicad_pcb"
    out = tmp_path / "fab"
    out.mkdir()
    (out / "b.xnc").write_text("xnc", encoding="utf-8")
    (out / "a.drl").write_text("drl", encoding="utf-8")
    cli = FakeCli()
    formatted: list[tuple[list[Path], str]] = []

    def format_files(files: list[Path], heading: str) -> str:
        formatted.append((files, heading))
        return "formatted"

    service = service_type(
        get_pcb_file=lambda: pcb,
        ensure_output_dir=lambda subdir=None: out,
        get_drill_command=lambda: "drill-v2",
        active_variant_args=lambda name=None: ["--variant", name] if name else [],
        run_cli_variants=cli,
        format_file_list=format_files,
    )

    assert service.export("fab", variant_name="proto") == "formatted"
    assert cli.calls == [
        [
            [
                "pcb",
                "export",
                "drill-v2",
                "--variant",
                "proto",
                "--output",
                str(out),
                str(pcb),
            ],
            [
                "pcb",
                "export",
                "drill-v2",
                "--variant",
                "proto",
                "--input",
                str(pcb),
                "--output",
                str(out),
            ],
        ]
    ]
    assert formatted == [([out / "a.drl", out / "b.xnc"], f"Drill export completed in {out}:")]


def test_export_drill_preserves_invalid_output_and_cli_failure_messages(tmp_path: Path) -> None:
    service_type = _service_type()
    pcb = tmp_path / "demo.kicad_pcb"

    def invalid_output(_subdir: str | None = None) -> Path:
        raise ValueError("outside project")

    invalid_service = service_type(
        get_pcb_file=lambda: pcb,
        ensure_output_dir=invalid_output,
        get_drill_command=lambda: "drill",
        active_variant_args=lambda _name=None: [],
        run_cli_variants=FakeCli(),
        format_file_list=lambda _files, _heading: "unused",
    )
    assert invalid_service.export("../../bad") == "Invalid output path: outside project"

    failed_service = service_type(
        get_pcb_file=lambda: pcb,
        ensure_output_dir=lambda _subdir=None: tmp_path,
        get_drill_command=lambda: "drill",
        active_variant_args=lambda _name=None: [],
        run_cli_variants=FakeCli((2, "", "cli failed")),
        format_file_list=lambda _files, _heading: "unused",
    )
    assert failed_service.export() == "Drill export failed: cli failed"

    unknown_service = service_type(
        get_pcb_file=lambda: pcb,
        ensure_output_dir=lambda _subdir=None: tmp_path,
        get_drill_command=lambda: "drill",
        active_variant_args=lambda _name=None: [],
        run_cli_variants=FakeCli((2, "", "")),
        format_file_list=lambda _files, _heading: "unused",
    )
    assert unknown_service.export() == "Drill export failed: unknown error"
