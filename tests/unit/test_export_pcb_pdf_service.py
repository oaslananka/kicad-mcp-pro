from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any


def _service_type() -> type[Any]:
    spec = importlib.util.find_spec("kicad_mcp.export.pcb_pdf")
    assert spec is not None, "PCB PDF export service module must be extracted"
    module = importlib.import_module("kicad_mcp.export.pcb_pdf")
    return module.ExportPcbPdfService


class FakeCli:
    def __init__(self, result: tuple[int, str, str] = (0, "", "")) -> None:
        self.result = result
        self.calls: list[list[list[str]]] = []

    def __call__(self, variants: list[list[str]]) -> tuple[int, str, str]:
        self.calls.append(variants)
        return self.result


def test_export_pcb_pdf_preserves_default_layers_variant_and_cli_fallbacks(tmp_path: Path) -> None:
    service_type = _service_type()
    pcb = tmp_path / "demo.kicad_pcb"
    out = tmp_path / "output"
    out.mkdir()
    cli = FakeCli()
    service = service_type(
        get_pcb_file=lambda: pcb,
        ensure_output_dir=lambda _subdir=None: out,
        active_variant_args=lambda: ["--variant", "fab"],
        run_cli_variants=cli,
        default_layers=("F.Cu", "Edge.Cuts"),
    )

    assert service.export() == f"PCB PDF exported to {out / 'board.pdf'}"
    assert cli.calls == [
        [
            [
                "pcb",
                "export",
                "pdf",
                "--variant",
                "fab",
                "--output",
                str(out / "board.pdf"),
                "--layers",
                "F.Cu,Edge.Cuts",
                str(pcb),
            ],
            [
                "pcb",
                "export",
                "pdf",
                "--variant",
                "fab",
                "--input",
                str(pcb),
                "--output",
                str(out / "board.pdf"),
                "--layers",
                "F.Cu,Edge.Cuts",
            ],
        ]
    ]


def test_export_pcb_pdf_preserves_explicit_layers_and_failure_text(tmp_path: Path) -> None:
    service_type = _service_type()
    pcb = tmp_path / "demo.kicad_pcb"
    out = tmp_path / "output"
    out.mkdir()
    cli = FakeCli((2, "", "pdf failed"))
    service = service_type(
        get_pcb_file=lambda: pcb,
        ensure_output_dir=lambda _subdir=None: out,
        active_variant_args=lambda: [],
        run_cli_variants=cli,
        default_layers=("F.Cu", "Edge.Cuts"),
    )

    assert service.export(["B.Cu", "Edge.Cuts"]) == "PCB PDF export failed: pdf failed"
    assert cli.calls[0][0][-3:] == ["--layers", "B.Cu,Edge.Cuts", str(pcb)]

    cli.result = (2, "", "")
    assert service.export([]) == "PCB PDF export failed: unknown error"
