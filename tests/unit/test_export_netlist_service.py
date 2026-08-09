from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from kicad_mcp.export.netlist import ExportNetlistService


class FakeCli:
    def __init__(self, result: tuple[int, str, str] = (0, "", "")) -> None:
        self.result = result
        self.calls: list[list[list[str]]] = []

    def __call__(self, variants: list[list[str]]) -> tuple[int, str, str]:
        self.calls.append(variants)
        return self.result


def test_export_netlist_preserves_format_mapping_variant_and_output_path(tmp_path: Path) -> None:
    sch = tmp_path / "demo.kicad_sch"
    out = tmp_path / "output"
    out.mkdir()
    cli = FakeCli()
    service = ExportNetlistService(
        get_sch_file=lambda: sch,
        ensure_output_dir=lambda _subdir=None: out,
        active_variant_args=lambda: ["--variant", "proto"],
        run_cli_variants=cli,
    )

    assert service.export("cadstar") == f"Netlist exported to {out / 'netlist.frp'}"
    assert cli.calls == [
        [
            [
                "sch",
                "export",
                "netlist",
                "--variant",
                "proto",
                "--format",
                "cadstar",
                "--output",
                str(out / "netlist.frp"),
                str(sch),
            ]
        ]
    ]


@pytest.mark.parametrize(
    ("format_name", "cli_format", "extension"),
    [
        ("kicad", "kicadsexpr", "net"),
        ("spice", "spice", "cir"),
        ("orcadpcb2", "orcadpcb2", "net"),
    ],
)
def test_export_netlist_preserves_supported_format_contract(
    tmp_path: Path,
    format_name: str,
    cli_format: str,
    extension: str,
) -> None:
    sch = tmp_path / "demo.kicad_sch"
    out = tmp_path / "output"
    out.mkdir()
    cli = FakeCli()
    service = ExportNetlistService(
        get_sch_file=lambda: sch,
        ensure_output_dir=lambda _subdir=None: out,
        active_variant_args=list,
        run_cli_variants=cli,
    )

    assert service.export(format_name) == f"Netlist exported to {out / f'netlist.{extension}'}"
    assert cli.calls[0][0][3:5] == ["--format", cli_format]


def test_export_netlist_preserves_validation_and_failure_message(tmp_path: Path) -> None:
    service = ExportNetlistService(
        get_sch_file=lambda: tmp_path / "demo.kicad_sch",
        ensure_output_dir=lambda _subdir=None: tmp_path,
        active_variant_args=list,
        run_cli_variants=FakeCli((2, "", "bad netlist")),
    )

    assert service.export("spice") == "Netlist export failed: bad netlist"
    with pytest.raises(ValidationError):
        service.export("unsupported")
