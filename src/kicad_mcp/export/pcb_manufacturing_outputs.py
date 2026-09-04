"""FastMCP-independent low-level PCB manufacturing output exports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class PcbManufacturingCapabilities(Protocol):
    @property
    def position_command(self) -> str: ...

    @property
    def supports_ipc2581(self) -> bool: ...

    @property
    def supports_odb_export(self) -> bool: ...


class ResolveOutputFile(Protocol):
    def __call__(self, subdir: str, raw_name: str, *, default_name: str) -> Path: ...


@dataclass(frozen=True)
class _SingleFileSpec:
    command: str
    label: str
    output_subdir: str
    default_name: str
    support_name: str
    extra_args: tuple[str, ...] = ()
    report_success_stderr: bool = False


_IPC2581 = _SingleFileSpec(
    command="ipc2581",
    label="IPC-2581",
    output_subdir="ipc2581",
    default_name="board.ipc2581",
    support_name="supports_ipc2581",
    report_success_stderr=True,
)
_ODB = _SingleFileSpec(
    command="odb",
    label="ODB++",
    output_subdir="odb",
    default_name="board.odb",
    support_name="supports_odb_export",
    extra_args=("--compression",),
)


@dataclass(frozen=True)
class ExportPcbManufacturingOutputsService:
    """Export low-level assembly and manufacturing artifacts without MCP dependencies."""

    get_pcb_file: Callable[[], Path]
    get_capabilities: Callable[[], PcbManufacturingCapabilities]
    ensure_output_dir: Callable[[str], Path]
    resolve_output_file: ResolveOutputFile
    active_variant_args: Callable[[str | None], list[str]]
    run_cli_variants: Callable[[list[list[str]]], tuple[int, str, str]]
    format_file_list: Callable[[list[Path], str], str]

    def export_pick_and_place(
        self,
        format: str = "csv",
        variant_name: str | None = None,
    ) -> str:
        pcb_file = self.get_pcb_file()
        position_command = self.get_capabilities().position_command
        out_dir = self.ensure_output_dir("pos")
        variant_args = self.active_variant_args(variant_name)
        code, _, stderr = self.run_cli_variants(
            [
                [
                    "pcb",
                    "export",
                    position_command,
                    *variant_args,
                    "--format",
                    format,
                    "--output",
                    str(out_dir),
                    str(pcb_file),
                ],
                [
                    "pcb",
                    "export",
                    position_command,
                    *variant_args,
                    "--format",
                    format,
                    "--input",
                    str(pcb_file),
                    "--output",
                    str(out_dir),
                ],
            ]
        )
        if code != 0:
            return f"Pick and place export failed: {stderr or 'unknown error'}"
        files = sorted(out_dir.iterdir()) if out_dir.exists() else []
        return self.format_file_list(files, f"Pick and place data exported to {out_dir}:")

    def export_ipc2581(self, variant_name: str | None = None) -> str:
        return self._export_single_file(_IPC2581, variant_name)

    def export_odb(self, variant_name: str | None = None) -> str:
        return self._export_single_file(_ODB, variant_name)

    def _export_single_file(
        self,
        spec: _SingleFileSpec,
        variant_name: str | None,
    ) -> str:
        pcb_file = self.get_pcb_file()
        capabilities = self.get_capabilities()
        if not bool(getattr(capabilities, spec.support_name)):
            return f"{spec.label} export is not supported by the detected KiCad CLI."

        try:
            out_file = self.resolve_output_file(
                spec.output_subdir,
                "",
                default_name=spec.default_name,
            )
        except ValueError as exc:
            return f"Invalid output path: {exc}"

        variant_args = self.active_variant_args(variant_name)
        prefix = ["pcb", "export", spec.command, *variant_args, *spec.extra_args]
        code, _, stderr = self.run_cli_variants(
            [
                [*prefix, "--output", str(out_file), str(pcb_file)],
                [*prefix, "--input", str(pcb_file), "--output", str(out_file)],
            ]
        )
        if code != 0:
            return f"{spec.label} export failed: {stderr or 'unknown error'}"
        result = f"{spec.label} exported to {out_file}"
        warning = stderr.strip()
        if spec.report_success_stderr and warning:
            return f"{result}\nWarnings:\n{warning}"
        return result
