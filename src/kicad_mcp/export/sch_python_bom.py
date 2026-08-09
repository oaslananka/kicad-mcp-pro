"""FastMCP-free schematic legacy Python BOM export behavior."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

type GetSchFile = Callable[[], Path]


class ResolveOutputFile(Protocol):
    """Resolve a safe export path using the composition root's path policy."""

    def __call__(self, subdir: str, raw_name: str, *, default_name: str) -> Path: ...


class RunCli(Protocol):
    """Execute kicad-cli arguments without shell interpolation."""

    def __call__(self, *args: str) -> tuple[int, str, str]: ...


@dataclass(frozen=True)
class ExportSchPythonBomService:
    """Export a schematic legacy XML BOM through injected project and CLI seams."""

    get_sch_file: GetSchFile
    resolve_output_file: ResolveOutputFile
    run_cli: RunCli

    def export(self, output_file: str = "") -> str:
        """Export the schematic legacy XML BOM while preserving the existing contract."""
        sch_file = self.get_sch_file()
        try:
            out_file = self.resolve_output_file("bom", output_file, default_name="bom.xml")
        except ValueError as exc:
            return f"Invalid output path: {exc}"

        code, stdout, stderr = self.run_cli(
            "sch",
            "export",
            "python-bom",
            "--output",
            str(out_file),
            str(sch_file),
        )
        if code != 0:
            return f"Legacy Python BOM export failed: {stderr or stdout or 'unknown error'}"
        return f"Legacy Python BOM exported to {out_file}"
