"""FastMCP-free PCB board overview and collection inspection."""

from __future__ import annotations

from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass
from typing import Protocol, cast

from ..models.verdict import VerdictReport
from .board_access import (
    BoardAccessError,
    board_footprints,
    board_nets_filtered,
    board_shapes,
    board_tracks,
    board_vias,
    board_zones,
)


class PaginateItems(Protocol):
    """Paginate an iterable while preserving total and page count."""

    def __call__[T](
        self,
        items: Iterable[T],
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[T], int, int]: ...


class LimitItems(Protocol):
    """Apply the configured response limit while preserving total count."""

    def __call__[T](self, items: Iterable[T]) -> tuple[list[T], int]: ...


class BoardSummaryReport(Protocol):
    """Build the established structured board-summary verdict envelope."""

    def __call__(
        self,
        *,
        text: str,
        source: str,
        tracks: int = 0,
        vias: int = 0,
        footprints: int = 0,
        zones: int = 0,
        nets: int = 0,
        shapes: int = 0,
    ) -> VerdictReport: ...


class TracksFallback(Protocol):
    def __call__(
        self,
        ipc_error: BaseException,
        *,
        page: int,
        page_size: int,
        filter_layer: str,
        filter_net: str,
    ) -> str: ...


class FootprintsFallback(Protocol):
    def __call__(
        self,
        ipc_error: BaseException,
        *,
        page: int,
        page_size: int,
        filter_layer: str,
    ) -> str: ...


class BoardInspectionBoard(Protocol):
    def get_tracks(self) -> Collection[object]: ...

    def get_footprints(self) -> Collection[object]: ...

    def get_vias(self) -> Collection[object]: ...

    def get_zones(self) -> Collection[object]: ...

    def get_nets(self, *, netclass_filter: object | None) -> Collection[object]: ...

    def get_shapes(self) -> Collection[object]: ...


class NetLike(Protocol):
    @property
    def name(self) -> str: ...


class TrackLike(Protocol):
    @property
    def start(self) -> object: ...

    @property
    def end(self) -> object: ...

    @property
    def layer(self) -> int: ...

    @property
    def width(self) -> int: ...

    @property
    def net(self) -> NetLike: ...


class ViaLike(Protocol):
    @property
    def position(self) -> object: ...

    @property
    def diameter(self) -> int: ...

    @property
    def drill_diameter(self) -> int: ...

    @property
    def net(self) -> NetLike: ...

    @property
    def type(self) -> int: ...


class TextValueLike(Protocol):
    @property
    def value(self) -> str: ...


class TextFieldLike(Protocol):
    @property
    def text(self) -> TextValueLike: ...


class FootprintLike(Protocol):
    @property
    def reference_field(self) -> TextFieldLike: ...

    @property
    def value_field(self) -> TextFieldLike: ...

    @property
    def position(self) -> object: ...

    @property
    def layer(self) -> int: ...


type GetBoard = Callable[[], object]
type SummaryFallback = Callable[[BaseException], VerdictReport]
type ViasFallback = Callable[[BaseException], str]
type MatchesLayerFilter = Callable[[int, str], bool]
type WithDiagnostics = Callable[[str], str]
type LayerName = Callable[[int], str]
type ViaTypeName = Callable[[int], str]
type FormatSelectionId = Callable[[object], str]
type CoordNm = Callable[[object, str], int]
type NmToMm = Callable[[int], float]
type ConnectionErrors = tuple[type[Exception], ...]


@dataclass(frozen=True)
class PcbBoardInspectionService:
    """Inspect board summary, tracks, vias, and footprints without FastMCP."""

    get_board: GetBoard
    file_backed_board_summary: SummaryFallback
    board_summary_report: BoardSummaryReport
    file_backed_tracks: TracksFallback
    file_backed_vias: ViasFallback
    file_backed_footprints: FootprintsFallback
    paginate: PaginateItems
    limit_items: LimitItems
    matches_layer_filter: MatchesLayerFilter
    with_pcb_diagnostics: WithDiagnostics
    layer_name: LayerName
    via_type_name: ViaTypeName
    format_selection_id: FormatSelectionId
    coord_nm: CoordNm
    nm_to_mm: NmToMm
    connection_errors: ConnectionErrors

    @property
    def access_errors(self) -> ConnectionErrors:
        return (BoardAccessError, *self.connection_errors)

    def _board(self) -> BoardInspectionBoard:
        return cast(BoardInspectionBoard, self.get_board())

    def get_board_summary(self) -> VerdictReport:
        """Return the established structured live or file-backed board summary."""
        try:
            board = self._board()
            tracks = board_tracks(board)
            footprints = board_footprints(board)
            vias = board_vias(board)
            zones = board_zones(board)
            nets = board_nets_filtered(board, netclass_filter=None)
            shapes = board_shapes(board)
        except self.access_errors as exc:
            return self.file_backed_board_summary(exc)
        text = "\n".join(
            [
                "Board summary:",
                "- Source: live-gui",
                f"- Tracks: {len(tracks)}",
                f"- Vias: {len(vias)}",
                f"- Footprints: {len(footprints)}",
                f"- Zones: {len(zones)}",
                f"- Nets: {len(nets)}",
                f"- Shapes: {len(shapes)}",
            ]
        )
        return self.board_summary_report(
            text=text,
            source="live-gui",
            tracks=len(tracks),
            vias=len(vias),
            footprints=len(footprints),
            zones=len(zones),
            nets=len(nets),
            shapes=len(shapes),
        )

    def get_tracks(
        self,
        *,
        page: int = 1,
        page_size: int = 100,
        filter_layer: str = "",
        filter_net: str = "",
    ) -> str:
        """List live tracks with filtering and pagination or use the file fallback."""
        try:
            all_tracks = [
                raw_track
                for raw_track in board_tracks(self._board())
                if self.matches_layer_filter(cast(TrackLike, raw_track).layer, filter_layer)
                and (
                    not filter_net
                    or (cast(TrackLike, raw_track).net.name or "").casefold()
                    == filter_net.casefold()
                )
            ]
        except self.access_errors as exc:
            return self.file_backed_tracks(
                exc,
                page=page,
                page_size=page_size,
                filter_layer=filter_layer,
                filter_net=filter_net,
            )
        tracks, total, page_count = self.paginate(
            all_tracks,
            page=page,
            page_size=page_size,
        )
        if total == 0:
            if filter_layer or filter_net:
                return self.with_pcb_diagnostics(
                    "No tracks match the supplied filters on the active board."
                )
            return self.with_pcb_diagnostics("No tracks are present on the active board.")
        if not tracks:
            return f"Track page {page} is out of range. Available pages: 1-{page_count}."

        lines = [
            f"Tracks ({total} total):",
            "- Source: live-gui",
            f"- Page {page}/{page_count} | Showing {len(tracks)}",
        ]
        for index, raw_track in enumerate(tracks, start=1):
            track = cast(TrackLike, raw_track)
            lines.append(
                f"{index}. "
                f"({self.nm_to_mm(self.coord_nm(track.start, 'x')):.2f}, "
                f"{self.nm_to_mm(self.coord_nm(track.start, 'y')):.2f}) -> "
                f"({self.nm_to_mm(self.coord_nm(track.end, 'x')):.2f}, "
                f"{self.nm_to_mm(self.coord_nm(track.end, 'y')):.2f}) mm "
                f"layer={self.layer_name(track.layer)} "
                f"width={self.nm_to_mm(track.width):.3f} mm "
                f"net={track.net.name or '(none)'} id={self.format_selection_id(raw_track)}"
            )
        return "\n".join(lines)

    def get_vias(self) -> str:
        """List live vias with the configured response limit or use the file fallback."""
        try:
            vias, total = self.limit_items(board_vias(self._board()))
        except self.access_errors as exc:
            return self.file_backed_vias(exc)
        if not vias:
            return self.with_pcb_diagnostics("No vias are present on the active board.")

        lines = [f"Vias ({total} total):", "- Source: live-gui"]
        for index, raw_via in enumerate(vias, start=1):
            via = cast(ViaLike, raw_via)
            lines.append(
                f"{index}. "
                f"({self.nm_to_mm(self.coord_nm(via.position, 'x')):.2f}, "
                f"{self.nm_to_mm(self.coord_nm(via.position, 'y')):.2f}) mm "
                f"diameter={self.nm_to_mm(via.diameter):.3f} mm "
                f"drill={self.nm_to_mm(via.drill_diameter):.3f} mm "
                f"net={via.net.name or '(none)'} type={self.via_type_name(via.type)}"
            )
        return "\n".join(lines)

    def get_footprints(
        self,
        *,
        page: int = 1,
        page_size: int = 50,
        filter_layer: str = "",
    ) -> str:
        """List live footprints with filtering/pagination or use the file fallback."""
        try:
            all_footprints = [
                raw_footprint
                for raw_footprint in board_footprints(self._board())
                if self.matches_layer_filter(
                    cast(FootprintLike, raw_footprint).layer,
                    filter_layer,
                )
            ]
        except self.access_errors as exc:
            return self.file_backed_footprints(
                exc,
                page=page,
                page_size=page_size,
                filter_layer=filter_layer,
            )
        footprints, total, page_count = self.paginate(
            all_footprints,
            page=page,
            page_size=page_size,
        )
        if total == 0:
            if filter_layer:
                return self.with_pcb_diagnostics(
                    "No footprints match the supplied layer filter on the active board."
                )
            return self.with_pcb_diagnostics("No footprints are present on the active board.")
        if not footprints:
            return f"Footprint page {page} is out of range. Available pages: 1-{page_count}."

        lines = [
            f"Footprints ({total} total):",
            "- Source: live-gui",
            f"- Page {page}/{page_count} | Showing {len(footprints)}",
        ]
        for raw_footprint in footprints:
            footprint = cast(FootprintLike, raw_footprint)
            lines.append(
                f"- {footprint.reference_field.text.value} "
                f"({footprint.value_field.text.value}) "
                f"@ ({self.nm_to_mm(self.coord_nm(footprint.position, 'x')):.2f}, "
                f"{self.nm_to_mm(self.coord_nm(footprint.position, 'y')):.2f}) mm "
                f"layer={self.layer_name(footprint.layer)} "
                f"id={self.format_selection_id(raw_footprint)}"
            )
        return "\n".join(lines)
