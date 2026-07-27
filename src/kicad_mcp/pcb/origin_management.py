"""FastMCP-free PCB drill-origin behavior."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

type GetBoard = Callable[[], object]
type VectorFromXY = Callable[[int, int], object]
type MmToNm = Callable[[float], int]
type CoordNm = Callable[[object, str], int]
type NmToMm = Callable[[int], float]
type ConnectionErrors = tuple[type[Exception], ...]


@dataclass(frozen=True)
class PcbOriginService:
    """Read and update the board drill origin through injected dependencies."""

    get_board: GetBoard
    vector_from_xy: VectorFromXY
    mm_to_nm: MmToNm
    coord_nm: CoordNm
    nm_to_mm: NmToMm
    connection_errors: ConnectionErrors

    def set_origin(self, x_mm: float, y_mm: float) -> str:
        """Set the board drill origin when supported by the active KiCad IPC."""
        try:
            board = self.get_board()
            set_origin = getattr(board, "set_origin", None)
            if not callable(set_origin):
                return "Origin setting is not supported by the current KiCad IPC version."
            origin = self.vector_from_xy(
                int(self.mm_to_nm(x_mm)),
                int(self.mm_to_nm(y_mm)),
            )
            set_origin(origin)
            return f"Board origin set to ({x_mm:.3f}, {y_mm:.3f}) mm."
        except self.connection_errors as exc:
            return f"Failed to set origin: {exc}"

    def get_origin(self) -> str:
        """Return the board drill origin in millimeters when supported."""
        try:
            board = self.get_board()
            get_origin = getattr(board, "get_origin", None)
            if not callable(get_origin):
                return "Origin retrieval is not supported by the current KiCad IPC version."
            origin = get_origin()
            x_mm = self.nm_to_mm(self.coord_nm(origin, "x"))
            y_mm = self.nm_to_mm(self.coord_nm(origin, "y"))
            return json.dumps(
                {"origin_mm": {"x": x_mm, "y": y_mm}, "source": "live-gui"},
                indent=2,
            )
        except self.connection_errors as exc:
            return f"Failed to get origin: {exc}"
