from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path
from typing import Any

from pydantic import ValidationError


def _service_type() -> type[Any]:
    spec = importlib.util.find_spec("kicad_mcp.export.gerber")
    assert spec is not None, "Gerber export service module must be extracted"
    module = importlib.import_module("kicad_mcp.export.gerber")
    return module.ExportGerberService


class FakeEnsureOutputDir:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.calls: list[str | None] = []

    def __call__(self, subdir: str | None = None) -> Path:
        self.calls.append(subdir)
        if subdir == "../escape":
            raise ValueError("path escapes output directory")
        out = self.root / (subdir or "")
        out.mkdir(parents=True, exist_ok=True)
        return out


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
    gerber_command: str = "gerber",
    cli_result: tuple[int, str, str] = (0, "", ""),
):
    service_type = _service_type()
    ensure = FakeEnsureOutputDir(tmp_path / "output")
    cli = FakeCli(cli_result)
    formatter = FakeFormatter()
    service = service_type(
        get_pcb_file=lambda: tmp_path / "demo.kicad_pcb",
        ensure_output_dir=ensure,
        get_gerber_command=lambda: gerber_command,
        active_variant_args=lambda variant: ["--variant", variant] if variant else [],
        run_cli_variants=cli,
        format_file_list=formatter,
    )
    return service, ensure, cli, formatter


def test_export_preserves_cli_fallbacks_layers_variant_and_file_order(tmp_path: Path) -> None:
    service, ensure, cli, formatter = _service(tmp_path)
    out = tmp_path / "output" / "fab"
    out.mkdir(parents=True)
    (out / "b.gko").write_text("b", encoding="utf-8")
    (out / "a.gbr").write_text("a", encoding="utf-8")

    result = service.export(
        output_subdir="fab",
        layers=["F.Cu", "B.Cu"],
        variant_name="assembly-a",
    )

    assert ensure.calls == ["fab"]
    assert cli.calls == [
        [
            [
                "pcb",
                "export",
                "gerbers",
                "--variant",
                "assembly-a",
                "--output",
                str(out),
                "--layers",
                "F.Cu,B.Cu",
                str(tmp_path / "demo.kicad_pcb"),
            ],
            [
                "pcb",
                "export",
                "gerbers",
                "--variant",
                "assembly-a",
                "--input",
                str(tmp_path / "demo.kicad_pcb"),
                "--output",
                str(out),
                "--layers",
                "F.Cu,B.Cu",
            ],
            [
                "pcb",
                "export",
                "gerber",
                "--variant",
                "assembly-a",
                "--output",
                str(out),
                "--layers",
                "F.Cu,B.Cu",
                str(tmp_path / "demo.kicad_pcb"),
            ],
            [
                "pcb",
                "export",
                "gerber",
                "--variant",
                "assembly-a",
                "--input",
                str(tmp_path / "demo.kicad_pcb"),
                "--output",
                str(out),
                "--layers",
                "F.Cu,B.Cu",
            ],
        ]
    ]
    # Preserve the legacy glob behavior: *.gbr is also included by *.g*.
    assert formatter.calls == [
        ([out / "a.gbr", out / "a.gbr", out / "b.gko"], f"Gerber export completed in {out}:")
    ]
    assert result == f"formatted::Gerber export completed in {out}:::a.gbr,a.gbr,b.gko"


def test_export_appends_capability_command_only_when_distinct(tmp_path: Path) -> None:
    service, _ensure, cli, _formatter = _service(tmp_path, gerber_command="plot-gerber")

    service.export()

    commands = [variant[2] for variant in cli.calls[0]]
    assert commands == ["gerbers", "gerbers", "gerber", "gerber", "plot-gerber", "plot-gerber"]


def test_export_preserves_invalid_output_path_message(tmp_path: Path) -> None:
    service, _ensure, cli, _formatter = _service(tmp_path)

    assert service.export(output_subdir="../escape") == (
        "Invalid output path: path escapes output directory"
    )
    assert cli.calls == []


def test_export_preserves_pydantic_input_validation(tmp_path: Path) -> None:
    service, _ensure, _cli, _formatter = _service(tmp_path)

    try:
        service.export(output_subdir="")
    except ValidationError:
        pass
    else:
        raise AssertionError("empty output_subdir must retain ExportGerberInput validation")


def test_export_preserves_failure_message_contract(tmp_path: Path) -> None:
    service, _ensure, _cli, _formatter = _service(
        tmp_path, cli_result=(2, "stdout detail", "stderr detail")
    )
    assert service.export() == "Gerber export failed: stderr detail"

    service, _ensure, _cli, _formatter = _service(tmp_path, cli_result=(2, "stdout detail", ""))
    assert service.export() == "Gerber export failed: unknown error"
