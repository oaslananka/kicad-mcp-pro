"""FastMCP-free board statistics export behavior."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

type GetPcbFile = Callable[[], Path]
type EnsureOutputDir = Callable[[str | None], Path]
type RunCliVariants = Callable[[list[list[str]]], tuple[int, str, str]]
type ReadPreview = Callable[[Path], str]


@dataclass(frozen=True)
class ExportBoardStatsService:
    """Export board statistics through injected filesystem and CLI seams."""

    get_pcb_file: GetPcbFile
    ensure_output_dir: EnsureOutputDir
    run_cli_variants: RunCliVariants
    read_preview: ReadPreview

    def get_board_stats(self) -> str:
        """Export board statistics and return a readable preview."""
        pcb_file = self.get_pcb_file()
        out_file = self.ensure_output_dir(None) / "board_stats.txt"
        code, stdout, stderr = self.run_cli_variants(
            [
                ["pcb", "export", "stats", "--output", str(out_file), str(pcb_file)],
                [
                    "pcb",
                    "export",
                    "stats",
                    "--input",
                    str(pcb_file),
                    "--output",
                    str(out_file),
                ],
            ]
        )
        if out_file.exists():
            return self.read_preview(out_file)
        if code != 0:
            return f"Board stats export failed: {stderr or 'unknown error'}"
        return stdout or "Board statistics were generated without a text report."

    def export_board_stats(self, output_name: str | None = None) -> str:
        """Export board statistics to JSON-compatible output when available."""
        pcb_file = self.get_pcb_file()
        out_dir = self.ensure_output_dir("stats")
        out_file = out_dir / (output_name.strip() if output_name else "board_stats.json")
        if "/" in str(out_file.relative_to(out_dir)) or "\\" in str(out_file.relative_to(out_dir)):
            raise ValueError("Output name must be a single file name, not a path.")

        code, _stdout, stderr = self.run_cli_variants(
            [
                [
                    "pcb",
                    "export",
                    "stats",
                    "--output",
                    str(out_file),
                    str(pcb_file),
                ],
                [
                    "pcb",
                    "export",
                    "stats",
                    "--input",
                    str(pcb_file),
                    "--output",
                    str(out_file),
                ],
            ]
        )
        if code != 0:
            return f"Board stats export failed: {stderr or 'unknown error'}"
        if not out_file.exists():
            return "Board stats export completed but no output file was produced."

        try:
            stats = json.loads(out_file.read_text(encoding="utf-8"))
            return json.dumps(stats, indent=2)
        except (json.JSONDecodeError, OSError):
            return f"Board stats exported to {out_file}."
