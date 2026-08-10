from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any


def _service_type() -> type[Any]:
    spec = importlib.util.find_spec("kicad_mcp.export.pcb_3d_pdf")
    assert spec is not None, "PCB 3D PDF service module must be extracted"
    module = importlib.import_module("kicad_mcp.export.pcb_3d_pdf")
    return module.ExportPcb3dPdfService


class FakeResolver:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[str] = []

    def __call__(self, raw_path: str) -> Path:
        self.calls.append(raw_path)
        if raw_path == "../escape.pdf":
            raise ValueError("path escapes output directory")
        return self.root / (raw_path or "board-3d.pdf")


class FakeCli:
    def __init__(self, result: tuple[int, str, str] = (0, "", "")) -> None:
        self.result = result
        self.calls: list[list[list[str]]] = []

    def __call__(self, variants: list[list[str]]) -> tuple[int, str, str]:
        self.calls.append(variants)
        return self.result


def _service(
    tmp_path: Path,
    *,
    supported: bool = True,
    result: tuple[int, str, str] = (0, "", ""),
):
    service_type = _service_type()
    resolver = FakeResolver(tmp_path / "output" / "pdf")
    cli = FakeCli(result)
    service = service_type(
        get_pcb_file=lambda: tmp_path / "demo.kicad_pcb",
        supports_3d_pdf=lambda: supported,
        resolve_output_file=resolver,
        active_variant_args=lambda: ["--variant", "assembly-a"],
        run_cli_variants=cli,
    )
    return service, resolver, cli


def test_export_preserves_capability_gate_without_resolving_output(tmp_path: Path) -> None:
    service, resolver, cli = _service(tmp_path, supported=False)

    assert service.export() == "3D PDF export is not supported by the detected KiCad CLI."
    assert resolver.calls == []
    assert cli.calls == []


def test_export_preserves_default_output_variant_and_cli_fallbacks(tmp_path: Path) -> None:
    service, resolver, cli = _service(tmp_path)

    result = service.export()

    out = tmp_path / "output" / "pdf" / "board-3d.pdf"
    pcb = tmp_path / "demo.kicad_pcb"
    assert resolver.calls == [""]
    assert cli.calls == [
        [
            [
                "pcb",
                "export",
                "3d-pdf",
                "--variant",
                "assembly-a",
                "--output",
                str(out),
                str(pcb),
            ],
            [
                "pcb",
                "export",
                "3d-pdf",
                "--variant",
                "assembly-a",
                "--input",
                str(pcb),
                "--output",
                str(out),
            ],
        ]
    ]
    assert result == f"3D PDF exported to {out}"


def test_export_preserves_explicit_output_path(tmp_path: Path) -> None:
    service, resolver, _cli = _service(tmp_path)

    assert service.export("custom.pdf") == (
        f"3D PDF exported to {tmp_path / 'output' / 'pdf' / 'custom.pdf'}"
    )
    assert resolver.calls == ["custom.pdf"]


def test_export_preserves_invalid_output_path_message(tmp_path: Path) -> None:
    service, _resolver, cli = _service(tmp_path)

    assert service.export("../escape.pdf") == "Invalid output path: path escapes output directory"
    assert cli.calls == []


def test_export_preserves_failure_message_contract(tmp_path: Path) -> None:
    service, _resolver, _cli = _service(tmp_path, result=(2, "stdout detail", "stderr detail"))
    assert service.export() == "3D PDF export failed: stderr detail"

    service, _resolver, _cli = _service(tmp_path, result=(2, "stdout detail", ""))
    assert service.export() == "3D PDF export failed: unknown error"
