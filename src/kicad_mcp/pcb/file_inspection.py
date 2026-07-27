"""Deterministic, FastMCP-free file-backed PCB inspection behavior."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

type FootprintEntry = dict[str, Any]
type FootprintMap = dict[str, FootprintEntry]
type BoardBounds = tuple[float, float, float, float] | None


class BoardFileDiagnostics(Protocol):
    """Build the existing diagnostic payload for a board file."""

    def __call__(self, *, board_file: Path, status: str) -> Mapping[str, object]: ...


type GetBoardFile = Callable[[], Path]
type NormalizeBoardContent = Callable[[str], str]
type ParseBoardFootprints = Callable[[str], FootprintMap]
type FootprintLayers = Callable[[str], Sequence[str]]
type EdgeCutsBounds = Callable[[str], BoardBounds]
type ReadabilityReport = Callable[[FootprintMap, BoardBounds], Mapping[str, Any]]


@dataclass(frozen=True)
class PcbFileInspectionService:
    """Format file-backed PCB inspection results from injected dependencies."""

    get_board_file: GetBoardFile
    normalize_board_content: NormalizeBoardContent
    parse_board_footprints: ParseBoardFootprints
    footprint_layers: FootprintLayers
    board_file_diagnostics: BoardFileDiagnostics
    edge_cuts_bounds: EdgeCutsBounds
    readability_report: ReadabilityReport

    def _board_context(self) -> tuple[Path, str, FootprintMap]:
        board_file = self.get_board_file()
        board_content = self.normalize_board_content(board_file.read_text(encoding="utf-8"))
        return board_file, board_content, self.parse_board_footprints(board_content)

    def footprint_layers_for(self, reference: str) -> str:
        """Return every board layer referenced by one footprint block."""
        board_file, _board_content, footprints = self._board_context()
        entry = footprints.get(reference)
        if entry is None:
            return json.dumps(
                {
                    "reference": reference,
                    "found": False,
                    "layers": [],
                    "diagnostics": self.board_file_diagnostics(
                        board_file=board_file,
                        status="footprint reference not present in board file",
                    ),
                },
                indent=2,
            )

        layers = list(self.footprint_layers(str(entry["block"])))
        return json.dumps(
            {
                "reference": reference,
                "found": True,
                "layers": layers,
                "diagnostics": self.board_file_diagnostics(
                    board_file=board_file,
                    status="using file-backed footprint parser",
                ),
            },
            indent=2,
        )

    def visual_qa(self) -> str:
        """Return the existing file-backed PCB readability report."""
        _board_file, board_content, footprints = self._board_context()
        bounds = self.edge_cuts_bounds(board_content)
        return json.dumps(self.readability_report(footprints, bounds), indent=2)
