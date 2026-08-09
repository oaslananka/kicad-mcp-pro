from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any


def _service_type() -> type[Any]:
    spec = importlib.util.find_spec("kicad_mcp.export.sch_pdf")
    assert spec is not None, "schematic PDF export service module must be extracted"
    module = importlib.import_module("kicad_mcp.export.sch_pdf")
    return module.ExportSchPdfService


class FakeCli:
    def __init__(self, result: tuple[int, str, str] = (0, "", "")) -> None:
        self.result = result
        self.calls: list[list[list[str]]] = []

    def __call__(self, variants: list[list[str]]) -> tuple[int, str, str]:
        self.calls.append(variants)
        return self.result


def test_export_sch_pdf_preserves_variant_output_and_cli_fallbacks(tmp_path: Path) -> None:
    service_type = _service_type()
    sch = tmp_path / "demo.kicad_sch"
    out = tmp_path / "output"
    out.mkdir()
    cli = FakeCli()
    service = service_type(
        get_sch_file=lambda: sch,
        ensure_output_dir=lambda _subdir=None: out,
        active_variant_args=lambda: ["--variant", "assembly-a"],
        run_cli_variants=cli,
    )

    assert service.export() == f"Schematic PDF exported to {out / 'schematic.pdf'}"
    assert cli.calls == [
        [
            [
                "sch",
                "export",
                "pdf",
                "--variant",
                "assembly-a",
                "--output",
                str(out / "schematic.pdf"),
                str(sch),
            ],
            [
                "sch",
                "export",
                "pdf",
                "--variant",
                "assembly-a",
                "--input",
                str(sch),
                "--output",
                str(out / "schematic.pdf"),
            ],
        ]
    ]


def test_export_sch_pdf_preserves_failure_message_precedence(tmp_path: Path) -> None:
    service_type = _service_type()

    def service_for(result: tuple[int, str, str]):
        return service_type(
            get_sch_file=lambda: tmp_path / "demo.kicad_sch",
            ensure_output_dir=lambda _subdir=None: tmp_path,
            active_variant_args=list,
            run_cli_variants=FakeCli(result),
        )

    assert service_for((2, "stdout detail", "stderr detail")).export() == (
        "Schematic PDF export failed: stderr detail"
    )
    assert service_for((2, "stdout detail", "")).export() == (
        "Schematic PDF export failed: stdout detail"
    )
    assert service_for((2, "", "")).export() == "Schematic PDF export failed: unknown error"
