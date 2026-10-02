"""FastMCP-independent manufacturing board-import orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ImportCapabilities(Protocol):
    @property
    def supports_allegro_import(self) -> bool: ...

    @property
    def supports_pads_import(self) -> bool: ...

    @property
    def supports_geda_import(self) -> bool: ...

    @property
    def version(self) -> str | None: ...


CliRunner = Callable[[list[list[str]]], tuple[int, str, str]]
PathResolver = Callable[[str], Path]
CapabilitiesProvider = Callable[[], ImportCapabilities]


@dataclass(frozen=True)
class ManufacturingImportService:
    """Own board-import behavior without depending on MCP transport types."""

    resolve_path: PathResolver
    run_cli_variants: CliRunner
    get_cli_capabilities: CapabilitiesProvider

    def check_import_support(self, import_format: str) -> str:
        caps = self.get_cli_capabilities()
        lookup = {
            "allegro": caps.supports_allegro_import,
            "pads": caps.supports_pads_import,
            "geda": caps.supports_geda_import,
        }
        key = import_format.strip().casefold()
        if key not in lookup:
            return "Supported import formats: allegro, pads, geda."
        version = caps.version or "unknown"
        return (
            f"Format: {key}\n"
            f"Supported by detected CLI: {'yes' if lookup[key] else 'no'}\n"
            f"Detected KiCad version: {version}"
        )

    def import_board(
        self,
        *,
        input_file: str,
        output_file: str = "",
        import_format: str = "auto",
        report_format: str = "none",
        report_file: str = "",
    ) -> str:
        if import_format.strip().casefold() == "allegro":
            return "blocked: KiCad CLI does not support allegro import in 10.0.6"

        try:
            in_path = self.resolve_path(input_file)
        except Exception as exc:
            raise ValueError(f"Unsafe input file path: {exc}") from exc

        if not in_path.exists():
            return f"Input file was not found: {input_file}"

        cmd = ["pcb", "import", "--format", import_format, "--report-format", report_format]
        if report_file:
            try:
                rep_path = self.resolve_path(report_file)
            except Exception as exc:
                raise ValueError(f"Unsafe report file path: {exc}") from exc
            cmd.extend(["--report-file", str(rep_path)])

        if output_file:
            try:
                out_path = self.resolve_path(output_file)
            except Exception as exc:
                raise ValueError(f"Unsafe output file path: {exc}") from exc
            cmd.extend(["--output", str(out_path)])

        cmd.append(str(in_path))
        code, stdout, stderr = self.run_cli_variants([cmd])
        if code != 0:
            return f"Board import failed: {stderr or stdout or 'unknown error'}"
        return f"Board imported successfully. Output: {output_file or 'default location'}"

    def import_allegro(self, allegro_brd_path: str, output_dir: str = "") -> str:
        _ = allegro_brd_path, output_dir
        return "blocked: KiCad CLI does not support allegro import in 10.0.6"

    def import_pads(self, pads_pcb_path: str, output_dir: str = "") -> str:
        result = self.import_board(
            input_file=pads_pcb_path,
            output_file=output_dir,
            import_format="pads",
        )
        if "Board import failed" in result:
            return result.replace("Board import failed", "pads import failed")
        return result.replace("Board imported successfully", "pads import completed")

    def import_geda(self, geda_pcb_path: str, output_dir: str = "") -> str:
        result = self.import_board(
            input_file=geda_pcb_path,
            output_file=output_dir,
            import_format="geda",
        )
        if "Board import failed" in result:
            return result.replace("Board import failed", "geda import failed")
        return result.replace("Board imported successfully", "geda import completed")

    def import_specctra(self, specctra_ses_path: str, output_dir: str = "") -> str:
        result = self.import_board(
            input_file=specctra_ses_path,
            output_file=output_dir,
            import_format="specctra",
        )
        if "Board import failed" in result:
            return result.replace("Board import failed", "specctra import failed")
        return result.replace("Board imported successfully", "specctra import completed")
