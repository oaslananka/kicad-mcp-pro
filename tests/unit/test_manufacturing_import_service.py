from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


def _service_module() -> ModuleType:
    spec = importlib.util.find_spec("kicad_mcp.manufacturing.imports")
    assert spec is not None, "Manufacturing import service module must be extracted"
    return importlib.import_module("kicad_mcp.manufacturing.imports")


def _service(tmp_path: Path):  # type: ignore[no-untyped-def]
    module = _service_module()
    calls: list[list[list[str]]] = []

    def resolve_path(path_text: str) -> Path:
        path = (tmp_path / path_text).resolve()
        if not path.is_relative_to(tmp_path.resolve()):
            raise ValueError("outside project")
        return path

    def run_cli_variants(variants: list[list[str]]) -> tuple[int, str, str]:
        calls.append(variants)
        return 0, "imported", ""

    caps = SimpleNamespace(
        supports_allegro_import=True,
        supports_pads_import=False,
        supports_geda_import=True,
        version="10.0.1",
    )
    service = module.ManufacturingImportService(
        resolve_path=resolve_path,
        run_cli_variants=run_cli_variants,
        get_cli_capabilities=lambda: caps,
    )
    return service, calls


def test_import_support_uses_injected_cli_capabilities(tmp_path: Path) -> None:
    service, _calls = _service(tmp_path)

    supported = service.check_import_support(" Allegro ")
    unknown = service.check_import_support("eagle")

    assert "Supported by detected CLI: yes" in supported
    assert "Detected KiCad version: 10.0.1" in supported
    assert unknown == "Supported import formats: allegro, pads, geda."


def test_board_import_preserves_cli_contract_and_path_safety(tmp_path: Path) -> None:
    service, calls = _service(tmp_path)
    source = tmp_path / "legacy.brd"
    source.write_text("legacy", encoding="utf-8")

    result = service.import_board(
        input_file="legacy.brd",
        output_file="imports/board.kicad_pcb",
        import_format="pads",
        report_format="json",
        report_file="imports/report.json",
    )

    assert result == "Board imported successfully. Output: imports/board.kicad_pcb"
    assert calls == [
        [
            [
                "pcb",
                "import",
                "--format",
                "pads",
                "--report-format",
                "json",
                "--report-file",
                str(tmp_path / "imports/report.json"),
                "--output",
                str(tmp_path / "imports/board.kicad_pcb"),
                str(source),
            ]
        ]
    ]

    with pytest.raises(ValueError, match="Unsafe input file path"):
        service.import_board(input_file="../outside.brd")


def test_legacy_import_wrappers_preserve_block_and_result_wording(tmp_path: Path) -> None:
    module = _service_module()
    source = tmp_path / "legacy.brd"
    source.write_text("legacy", encoding="utf-8")

    def resolve_path(path_text: str) -> Path:
        return (tmp_path / path_text).resolve()

    service = module.ManufacturingImportService(
        resolve_path=resolve_path,
        run_cli_variants=lambda _variants: (2, "", "unsupported"),
        get_cli_capabilities=lambda: SimpleNamespace(
            supports_allegro_import=False,
            supports_pads_import=False,
            supports_geda_import=False,
            version="10.0.6",
        ),
    )

    assert service.import_allegro("legacy.brd") == (
        "blocked: KiCad CLI does not support allegro import in 10.0.6"
    )
    assert "pads import failed: unsupported" in service.import_pads("legacy.brd")
    assert "geda import failed: unsupported" in service.import_geda("legacy.brd")
    assert "specctra import failed: unsupported" in service.import_specctra("legacy.brd")


def test_legacy_import_wrappers_preserve_success_wording(tmp_path: Path) -> None:
    module = _service_module()
    source = tmp_path / "legacy.brd"
    source.write_text("legacy", encoding="utf-8")

    service = module.ManufacturingImportService(
        resolve_path=lambda path_text: (tmp_path / path_text).resolve(),
        run_cli_variants=lambda _variants: (0, "imported", ""),
        get_cli_capabilities=lambda: SimpleNamespace(
            supports_allegro_import=False,
            supports_pads_import=True,
            supports_geda_import=True,
            version="10.0.6",
        ),
    )

    assert "pads import completed" in service.import_pads("legacy.brd")
    assert "geda import completed" in service.import_geda("legacy.brd")
    assert "specctra import completed" in service.import_specctra("legacy.brd")
