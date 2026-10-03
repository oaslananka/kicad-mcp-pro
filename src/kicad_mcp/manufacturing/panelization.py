"""FastMCP-independent PCB panelization orchestration."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class PanelizationProcessResult(Protocol):
    @property
    def returncode(self) -> int: ...

    @property
    def stdout(self) -> str: ...

    @property
    def stderr(self) -> str: ...


PanelizationRunner = Callable[[list[str]], PanelizationProcessResult]


@dataclass(frozen=True)
class PanelizationService:
    """Own KiKit panelization behavior independently of MCP registration."""

    kikit_available: Callable[[], bool]
    get_pcb_file: Callable[[], Path | None]
    ensure_output_dir: Callable[[str], Path]
    resolve_output_path: Callable[[str], Path]
    run_command: PanelizationRunner

    def panelize(
        self,
        *,
        layout: str = "grid",
        rows: int = 2,
        cols: int = 2,
        spacing_mm: float = 2.0,
        frame_width_mm: float = 5.0,
        output_path: str = "",
        dry_run: bool = True,
        confirm: bool = False,
    ) -> str:
        if not self.kikit_available():
            return (
                "KiKit is not installed. "
                "Install it with: pip install kikit\n"
                "KiKit documentation: https://github.com/yaqwsx/KiKit"
            )

        pcb_file = self.get_pcb_file()
        if pcb_file is None or not pcb_file.exists():
            return "No PCB file is configured. Call kicad_set_project() first."

        layout_lower = layout.lower()
        if layout_lower not in ("grid", "mousebites", "vcut"):
            return f"Invalid layout '{layout}'. Choose from: grid, mousebites, vcut."

        if rows < 1 or cols < 1:
            return "rows and cols must both be >= 1."

        out_dir = self.ensure_output_dir("panel")
        if output_path:
            panel_file = self.resolve_output_path(output_path)
        else:
            panel_file = out_dir / f"{pcb_file.stem}_panel_{rows}x{cols}.kicad_pcb"

        cmd = self._command(
            layout=layout_lower,
            rows=rows,
            cols=cols,
            spacing_mm=spacing_mm,
            frame_width_mm=frame_width_mm,
            pcb_file=pcb_file,
            panel_file=panel_file,
        )

        if dry_run:
            return (
                "Dry run: panelization was not executed.\n"
                f"- Output: {panel_file}\n"
                f"- Layout: {layout_lower} {rows}x{cols}, spacing={spacing_mm}mm, "
                f"frame={frame_width_mm}mm\n"
                f"- Command: {' '.join(cmd)}\n"
                "Set dry_run=false and confirm=true to create the panel file."
            )
        if not confirm:
            return (
                "Panelization requires explicit confirmation because it writes a PCB file.\n"
                f"- Intended output: {panel_file}\n"
                "Rerun with dry_run=false and confirm=true."
            )
        if panel_file.exists():
            return (
                "Refusing to overwrite an existing panel file without choosing a new output_path.\n"
                f"- Existing file: {panel_file}"
            )

        try:
            result = self.run_command(cmd)
        except subprocess.TimeoutExpired:
            return "KiKit panelization timed out after 120 seconds."
        except (OSError, FileNotFoundError) as exc:
            return f"Failed to run KiKit: {exc}"

        if result.returncode != 0:
            stderr = (result.stderr or "").strip()[:500]
            return f"KiKit panelization failed (exit {result.returncode}):\n{stderr}"

        return (
            f"Panel created: {panel_file}\n"
            f"Layout: {layout} {rows}x{cols}, spacing={spacing_mm}mm, frame={frame_width_mm}mm\n"
            "Open the panel file in KiCad to verify before submitting to fabricator."
        )

    @staticmethod
    def _command(
        *,
        layout: str,
        rows: int,
        cols: int,
        spacing_mm: float,
        frame_width_mm: float,
        pcb_file: Path,
        panel_file: Path,
    ) -> list[str]:
        if layout == "grid":
            return [
                "kikit",
                "panelize",
                "--layout",
                f"grid; rows: {rows}; cols: {cols}; space: {spacing_mm}mm",
                "--tabs",
                "fixed; width: 3mm; count: 1",
                "--cuts",
                "mousebites; drill: 0.5mm; spacing: 0.8mm",
                "--framing",
                f"railstb; width: {frame_width_mm}mm",
                "--post",
                "millRoundedCorner",
                str(pcb_file),
                str(panel_file),
            ]
        if layout == "mousebites":
            return [
                "kikit",
                "panelize",
                "--layout",
                f"grid; rows: {rows}; cols: {cols}; space: {spacing_mm}mm",
                "--tabs",
                "fixed; width: 3mm; count: 2",
                "--cuts",
                "mousebites; drill: 0.5mm; spacing: 0.8mm; offset: 0.25mm",
                "--framing",
                f"railstb; width: {frame_width_mm}mm",
                str(pcb_file),
                str(panel_file),
            ]
        return [
            "kikit",
            "panelize",
            "--layout",
            f"grid; rows: {rows}; cols: {cols}; space: 0mm",
            "--tabs",
            "full",
            "--cuts",
            "vcuts; clearance: 0.5mm",
            "--framing",
            f"railstb; width: {frame_width_mm}mm",
            str(pcb_file),
            str(panel_file),
        ]
