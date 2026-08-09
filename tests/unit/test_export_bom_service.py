from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError


def _service_type() -> type[Any]:
    spec = importlib.util.find_spec("kicad_mcp.export.bom")
    assert spec is not None, "BOM export service module must be extracted"
    module = importlib.import_module("kicad_mcp.export.bom")
    return module.ExportBomService


class FakeCli:
    def __init__(self, result: tuple[int, str, str] = (0, "", "")) -> None:
        self.result = result
        self.calls: list[list[list[str]]] = []

    def __call__(self, variants: list[list[str]]) -> tuple[int, str, str]:
        self.calls.append(variants)
        return self.result


class VariantArgs:
    def __init__(self) -> None:
        self.calls: list[str | None] = []

    def __call__(self, variant: str | None) -> list[str]:
        self.calls.append(variant)
        return ["--variant", variant] if variant else []


def _service(
    tmp_path: Path,
    *,
    schematic_files: list[Path] | None = None,
    rows: list[dict[str, str]] | None = None,
    cli_result: tuple[int, str, str] = (0, "", ""),
    rows_error: Exception | None = None,
):
    service_type = _service_type()
    out_dir = tmp_path / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    sch = tmp_path / "demo.kicad_sch"
    cli = FakeCli(cli_result)
    variant_args = VariantArgs()
    preview_calls: list[Path] = []

    def read_preview(path: Path) -> str:
        preview_calls.append(path)
        if path.exists():
            return path.read_text(encoding="utf-8")
        return "preview"

    def component_rows() -> list[dict[str, str]]:
        if rows_error is not None:
            raise rows_error
        return rows or []

    service = service_type(
        get_sch_file=lambda: sch,
        ensure_output_dir=lambda: out_dir,
        active_variant_args=variant_args,
        run_cli_variants=cli,
        read_preview=read_preview,
        project_schematic_files=lambda: schematic_files or [sch],
        schematic_component_rows=component_rows,
    )
    return service, out_dir, sch, cli, variant_args, preview_calls


def test_csv_single_schematic_preserves_cli_fallbacks_variant_and_preview(tmp_path: Path) -> None:
    service, out_dir, sch, cli, variant_args, preview_calls = _service(tmp_path)

    result = service.export(format="csv", variant_name="assembly-a")

    out_file = out_dir / "bom.csv"
    assert variant_args.calls == ["assembly-a"]
    assert cli.calls == [
        [
            [
                "sch",
                "export",
                "bom",
                "--variant",
                "assembly-a",
                "--output",
                str(out_file),
                "--format-preset",
                "CSV",
                str(sch),
            ],
            [
                "sch",
                "export",
                "bom",
                "--variant",
                "assembly-a",
                "--input",
                str(sch),
                "--output",
                str(out_file),
                "--format-preset",
                "CSV",
            ],
            ["sch", "export", "python-bom", "--output", str(out_file), str(sch)],
        ]
    ]
    assert preview_calls == [out_file]
    assert result == f"BOM exported to {out_file}\n\npreview"


def test_xml_preserves_suffix_and_existing_cli_contract(tmp_path: Path) -> None:
    service, out_dir, sch, cli, variant_args, preview_calls = _service(tmp_path)

    result = service.export(format="xml")

    out_file = out_dir / "bom.xml"
    assert variant_args.calls == [None]
    assert cli.calls[0][0] == [
        "sch",
        "export",
        "bom",
        "--output",
        str(out_file),
        "--format-preset",
        "CSV",
        str(sch),
    ]
    assert cli.calls[0][2] == ["sch", "export", "python-bom", "--output", str(out_file), str(sch)]
    assert preview_calls == [out_file]
    assert result == f"BOM exported to {out_file}\n\npreview"


def test_csv_multi_schematic_preserves_consolidated_writer_and_skips_cli(tmp_path: Path) -> None:
    sheets = [tmp_path / "demo.kicad_sch", tmp_path / "second.kicad_sch"]
    rows = [
        {
            "reference": "R1",
            "value": "10k",
            "footprint": "R_0805",
            "lib_id": "Device:R",
            "lcsc": "C1",
            "mpn": "MPN1",
            "manufacturer": "Maker1",
            "populate": "",
        },
        {
            "reference": "C1",
            "value": "100n",
            "footprint": "C_0805",
            "lib_id": "Device:C",
            "lcsc": "C2",
            "mpn": "MPN2",
            "manufacturer": "Maker2",
            "populate": "DNP",
        },
    ]
    service, out_dir, _sch, cli, variant_args, preview_calls = _service(
        tmp_path, schematic_files=sheets, rows=rows
    )

    result = service.export(format="csv", variant_name="assembly-a")

    out_file = out_dir / "bom.csv"
    text = out_file.read_text(encoding="utf-8")
    assert "reference,value,footprint,lib_id,lcsc,mpn,manufacturer,populate" in text
    assert "R1,10k,R_0805,Device:R,C1,MPN1,Maker1," in text
    assert "C1,100n,C_0805,Device:C,C2,MPN2,Maker2,DNP" in text
    assert cli.calls == []
    assert variant_args.calls == []
    assert preview_calls == [out_file]
    assert result.startswith(
        f"BOM exported to {out_file}\nConsolidated 2 reference(s) from 2 schematic files.\n\n"
    )


@pytest.mark.parametrize(
    "error",
    [OSError("read failed"), ValueError("bad sheet"), RuntimeError("backend failed")],
)
def test_csv_multi_schematic_preserves_consolidation_failure_messages(
    tmp_path: Path, error: Exception
) -> None:
    service, _out_dir, _sch, cli, variant_args, preview_calls = _service(
        tmp_path,
        schematic_files=[tmp_path / "a.kicad_sch", tmp_path / "b.kicad_sch"],
        rows_error=error,
    )

    assert service.export() == f"BOM export failed: {error}"
    assert cli.calls == []
    assert variant_args.calls == []
    assert preview_calls == []


def test_cli_failure_only_fails_when_output_file_is_absent(tmp_path: Path) -> None:
    service, _out_dir, _sch, _cli, _variant_args, _preview_calls = _service(
        tmp_path, cli_result=(2, "", "cli failed")
    )
    assert service.export() == "BOM export failed: cli failed"

    service, out_dir, _sch, _cli, _variant_args, _preview_calls = _service(
        tmp_path, cli_result=(2, "", "cli failed")
    )
    (out_dir / "bom.csv").write_text("cached\n", encoding="utf-8")
    assert service.export() == f"BOM exported to {out_dir / 'bom.csv'}\n\ncached\n"


def test_export_preserves_pydantic_format_validation(tmp_path: Path) -> None:
    service, *_rest = _service(tmp_path)

    with pytest.raises(ValidationError):
        service.export(format="json")
