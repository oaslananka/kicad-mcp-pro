from __future__ import annotations

import importlib
import importlib.util
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _service_module():  # type: ignore[no-untyped-def]
    spec = importlib.util.find_spec("kicad_mcp.export.pcb_manufacturing_outputs")
    assert spec is not None, "PCB manufacturing outputs service module must be extracted"
    return importlib.import_module("kicad_mcp.export.pcb_manufacturing_outputs")


@dataclass(frozen=True)
class FakeCapabilities:
    position_command: str = "pos"
    supports_ipc2581: bool = True
    supports_odb_export: bool = True


def _service(
    tmp_path: Path,
    *,
    capabilities: FakeCapabilities | None = None,
    cli_result: tuple[int, str, str] = (0, "", ""),
    resolve_error: ValueError | None = None,
):
    module = _service_module()
    calls: dict[str, Any] = {
        "pcb": [],
        "variant": [],
        "ensure": [],
        "resolve": [],
        "cli": [],
        "format": [],
    }

    def get_pcb_file() -> Path:
        calls["pcb"].append(None)
        return tmp_path / "demo.kicad_pcb"

    def ensure_output_dir(subdir: str) -> Path:
        calls["ensure"].append(subdir)
        path = tmp_path / "output" / subdir
        path.mkdir(parents=True, exist_ok=True)
        return path

    def resolve_output_file(subdir: str, raw_name: str, *, default_name: str) -> Path:
        calls["resolve"].append((subdir, raw_name, default_name))
        if resolve_error is not None:
            raise resolve_error
        path = tmp_path / "output" / subdir / default_name
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def active_variant_args(variant_name: str | None = None) -> list[str]:
        calls["variant"].append(variant_name)
        return ["--variant", variant_name or "assembly-a"]

    def run_cli_variants(variants: list[list[str]]) -> tuple[int, str, str]:
        calls["cli"].append(variants)
        return cli_result

    def format_file_list(files: list[Path], heading: str) -> str:
        calls["format"].append((files, heading))
        return f"formatted::{heading}::{','.join(path.name for path in files)}"

    service = module.ExportPcbManufacturingOutputsService(
        get_pcb_file=get_pcb_file,
        get_capabilities=lambda: capabilities or FakeCapabilities(),
        ensure_output_dir=ensure_output_dir,
        resolve_output_file=resolve_output_file,
        active_variant_args=active_variant_args,
        run_cli_variants=run_cli_variants,
        format_file_list=format_file_list,
    )
    return service, calls


def test_pick_and_place_preserves_variant_fallbacks_and_sorted_files(tmp_path: Path) -> None:
    service, calls = _service(tmp_path)
    out_dir = tmp_path / "output" / "pos"
    out_dir.mkdir(parents=True)
    (out_dir / "z.csv").write_text("z", encoding="utf-8")
    (out_dir / "a.csv").write_text("a", encoding="utf-8")

    result = service.export_pick_and_place(format="ascii", variant_name="lite")

    pcb = str(tmp_path / "demo.kicad_pcb")
    assert calls["pcb"] == [None]
    assert calls["ensure"] == ["pos"]
    assert calls["variant"] == ["lite"]
    assert calls["cli"] == [
        [
            [
                "pcb",
                "export",
                "pos",
                "--variant",
                "lite",
                "--format",
                "ascii",
                "--output",
                str(out_dir),
                pcb,
            ],
            [
                "pcb",
                "export",
                "pos",
                "--variant",
                "lite",
                "--format",
                "ascii",
                "--input",
                pcb,
                "--output",
                str(out_dir),
            ],
        ]
    ]
    assert calls["format"] == [
        ([out_dir / "a.csv", out_dir / "z.csv"], f"Pick and place data exported to {out_dir}:")
    ]
    assert result == f"formatted::Pick and place data exported to {out_dir}:::a.csv,z.csv"


def test_pick_and_place_preserves_failure_text_and_ignores_stdout(tmp_path: Path) -> None:
    stderr_service, _ = _service(tmp_path, cli_result=(2, "stdout detail", "stderr detail"))
    assert stderr_service.export_pick_and_place() == "Pick and place export failed: stderr detail"

    stdout_only_service, _ = _service(tmp_path, cli_result=(2, "stdout detail", ""))
    assert (
        stdout_only_service.export_pick_and_place() == "Pick and place export failed: unknown error"
    )


def test_ipc2581_preserves_capability_path_variant_and_cli_fallbacks(tmp_path: Path) -> None:
    unsupported, unsupported_calls = _service(
        tmp_path,
        capabilities=FakeCapabilities(supports_ipc2581=False),
    )
    assert (
        unsupported.export_ipc2581()
        == "IPC-2581 export is not supported by the detected KiCad CLI."
    )
    assert unsupported_calls["pcb"] == [None]
    assert unsupported_calls["resolve"] == []
    assert unsupported_calls["cli"] == []

    invalid, invalid_calls = _service(tmp_path, resolve_error=ValueError("unsafe output"))
    assert invalid.export_ipc2581() == "Invalid output path: unsafe output"
    assert invalid_calls["resolve"] == [("ipc2581", "", "board.ipc2581")]
    assert invalid_calls["cli"] == []

    service, calls = _service(tmp_path)
    result = service.export_ipc2581(variant_name="fab")
    pcb = str(tmp_path / "demo.kicad_pcb")
    out_file = str(tmp_path / "output" / "ipc2581" / "board.ipc2581")
    assert calls["variant"] == ["fab"]
    assert calls["cli"] == [
        [
            ["pcb", "export", "ipc2581", "--variant", "fab", "--output", out_file, pcb],
            [
                "pcb",
                "export",
                "ipc2581",
                "--variant",
                "fab",
                "--input",
                pcb,
                "--output",
                out_file,
            ],
        ]
    ]
    assert result == f"IPC-2581 exported to {out_file}"


def test_ipc2581_surfaces_success_stderr_warnings(tmp_path: Path) -> None:
    service, _ = _service(
        tmp_path,
        cli_result=(0, "", "Board outline is invalid or missing.  Please run DRC.\n"),
    )
    out_file = tmp_path / "output" / "ipc2581" / "board.ipc2581"

    assert service.export_ipc2581() == (
        f"IPC-2581 exported to {out_file}\n"
        "Warnings:\nBoard outline is invalid or missing.  Please run DRC."
    )


def test_odb_success_does_not_change_output_contract_for_stderr(tmp_path: Path) -> None:
    service, _ = _service(tmp_path, cli_result=(0, "", "non-fatal diagnostic\n"))
    out_file = tmp_path / "output" / "odb" / "board.odb"

    assert service.export_odb() == f"ODB++ exported to {out_file}"


def test_ipc2581_preserves_failure_text_and_ignores_stdout(tmp_path: Path) -> None:
    stderr_service, _ = _service(tmp_path, cli_result=(2, "stdout detail", "stderr detail"))
    assert stderr_service.export_ipc2581() == "IPC-2581 export failed: stderr detail"

    stdout_only_service, _ = _service(tmp_path, cli_result=(2, "stdout detail", ""))
    assert stdout_only_service.export_ipc2581() == "IPC-2581 export failed: unknown error"


def test_odb_preserves_capability_compression_variant_and_cli_fallbacks(tmp_path: Path) -> None:
    unsupported, unsupported_calls = _service(
        tmp_path,
        capabilities=FakeCapabilities(supports_odb_export=False),
    )
    assert unsupported.export_odb() == "ODB++ export is not supported by the detected KiCad CLI."
    assert unsupported_calls["pcb"] == [None]
    assert unsupported_calls["resolve"] == []
    assert unsupported_calls["cli"] == []

    service, calls = _service(tmp_path)
    result = service.export_odb(variant_name="fab")
    pcb = str(tmp_path / "demo.kicad_pcb")
    out_file = str(tmp_path / "output" / "odb" / "board.odb")
    assert calls["resolve"] == [("odb", "", "board.odb")]
    assert calls["variant"] == ["fab"]
    assert calls["cli"] == [
        [
            [
                "pcb",
                "export",
                "odb",
                "--variant",
                "fab",
                "--compression",
                "--output",
                out_file,
                pcb,
            ],
            [
                "pcb",
                "export",
                "odb",
                "--variant",
                "fab",
                "--compression",
                "--input",
                pcb,
                "--output",
                out_file,
            ],
        ]
    ]
    assert result == f"ODB++ exported to {out_file}"


def test_odb_preserves_path_and_failure_text(tmp_path: Path) -> None:
    invalid, invalid_calls = _service(tmp_path, resolve_error=ValueError("unsafe output"))
    assert invalid.export_odb() == "Invalid output path: unsafe output"
    assert invalid_calls["cli"] == []

    failed, _ = _service(tmp_path, cli_result=(2, "stdout detail", ""))
    assert failed.export_odb() == "ODB++ export failed: unknown error"
